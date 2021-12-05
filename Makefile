AWS_REGION ?= us-east-1

GITHUB_OWNER ?= neuro-inc

IMAGE_TAG ?= latest

IMAGE_REPO_aws    = $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com
IMAGE_REPO_github = ghcr.io/$(GITHUB_OWNER)

IMAGE_REGISTRY ?= aws

IMAGE_NAME      = platformregistryapi
IMAGE_REPO_BASE = $(IMAGE_REPO_$(IMAGE_REGISTRY))
IMAGE_REPO      = $(IMAGE_REPO_BASE)/$(IMAGE_NAME)

HELM_ENV           ?= dev
HELM_CHART          = platform-registry
HELM_CHART_VERSION ?= 1.0.0
HELM_APP_VERSION   ?= 1.0.0

export IMAGE_REPO_BASE

setup init:
	pip install -U pip
	pip install -e .[dev]
	pre-commit install

lint: format
	mypy platform_registry_api tests

format:
ifdef CI_LINT_RUN
	pre-commit run --all-files --show-diff-on-failure
else
	pre-commit run --all-files
endif

test_unit:
	pytest -vv tests/unit

test_integration: docker_build
	docker-compose -f tests/docker/docker-compose.yaml pull -q; \
	docker-compose --project-directory=`pwd` -f tests/docker/docker-compose.yaml up -d; \
	pytest -vv tests/integration; \
	exit_code=$$?; \
	docker-compose -f tests/docker/docker-compose.yaml kill; \
	docker-compose -f tests/docker/docker-compose.yaml rm -f; \
	exit $$exit_code

test_e2e: docker_build
	docker-compose --project-directory=`pwd` -f tests/docker/docker-compose.yaml up -d registry; \
	tests/e2e/tests.sh; \
	exit_code=$$?; \
	docker-compose -f tests/docker/docker-compose.yaml kill; \
	docker-compose -f tests/docker/docker-compose.yaml rm -f; \
	exit $$exit_code

docker_build:
	rm -rf build dist
	pip install -U build
	python -m build
	docker build -t $(IMAGE_NAME):latest .

docker_push: docker_build
	docker tag $(IMAGE_NAME):latest $(IMAGE_REPO):$(IMAGE_TAG)
	docker push $(IMAGE_REPO):$(IMAGE_TAG)

	docker tag $(IMAGE_NAME):latest $(IMAGE_REPO):latest
	docker push $(IMAGE_REPO):latest

build_up: docker_build
	docker-compose --project-directory=`pwd` -f tests/docker/docker-compose.yaml up

helm_create_chart:
	export IMAGE_REPO=$(IMAGE_REPO); \
	export IMAGE_TAG=$(IMAGE_TAG); \
	export CHART_VERSION=$(HELM_CHART_VERSION); \
	export APP_VERSION=$(HELM_APP_VERSION); \
	VALUES=$$(cat charts/$(HELM_CHART)/values.yaml | envsubst); \
	echo "$$VALUES" > charts/$(HELM_CHART)/values.yaml; \
	CHART=$$(cat charts/$(HELM_CHART)/Chart.yaml | envsubst); \
	echo "$$CHART" > charts/$(HELM_CHART)/Chart.yaml

helm_deploy: helm_create_chart
	helm upgrade $(HELM_CHART) charts/$(HELM_CHART) \
		-f charts/$(HELM_CHART)/values-$(HELM_ENV).yaml \
		--namespace platform --install --wait --timeout 600s
