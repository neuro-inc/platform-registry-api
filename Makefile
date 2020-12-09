IMAGE_NAME ?= platformregistryapi
IMAGE_TAG ?= latest
ARTIFACTORY_TAG ?=$(shell echo "$(CIRCLE_TAG)" | awk -F/ '{print $$2}')
IMAGE_NAME_K8S ?= $(IMAGE_NAME)
ISORT_DIRS := platform_registry_api tests setup.py
FLAKE8_DIRS := $(ISORT_DIRS)
BLACK_DIRS := $(ISORT_DIRS)
MYPY_DIRS := $(ISORT_DIRS)

ifdef CIRCLECI
    PIP_EXTRA_INDEX_URL ?= "https://$(DEVPI_USER):$(DEVPI_PASS)@$(DEVPI_HOST)/$(DEVPI_USER)/$(DEVPI_INDEX)"
else
	ifdef GITHUB_ACTIONS
		PIP_EXTRA_INDEX_URL ?= https://$(DEVPI_USER):$(DEVPI_PASS)@$(DEVPI_HOST)/$(DEVPI_USER)/$(DEVPI_INDEX)
	else
		PIP_EXTRA_INDEX_URL ?= $(shell python pip_extra_index_url.py)
	endif
endif
export PIP_EXTRA_INDEX_URL

IMAGE_REPO_gke   ?= $(GKE_DOCKER_REGISTRY)/$(GKE_PROJECT_ID)
IMAGE_REPO_aws   ?= $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com
IMAGE_REPO_azure ?= $(AZURE_ACR_NAME).azurecr.io

IMAGE_REPO  ?= ${IMAGE_REPO_${CLOUD_PROVIDER}}

export IMAGE_REPO

CLOUD_IMAGE  ?=$(IMAGE_REPO)/$(IMAGE_NAME)

setup init:
	pip install -r requirements-test.txt
	pre-commit install

build:
	python setup.py sdist
	docker build -f Dockerfile -t $(IMAGE_NAME):$(IMAGE_TAG) \
	--build-arg PIP_EXTRA_INDEX_URL \
	--build-arg DIST_FILENAME=`python setup.py --fullname`.tar.gz .

pull:
	-docker-compose --project-directory=`pwd` -p platformregistryapi \
	    -f tests/docker/e2e.compose.yml pull

build_test: build
	docker build -t platformregistryapi-test -f tests/Dockerfile .

build_up: build
	docker-compose --project-directory=`pwd` -p platformregistryapi \
            -f tests/docker/e2e.compose.yml up

test_e2e_built: pull
	docker-compose --project-directory=`pwd` -p platformregistryapi \
	    -f tests/docker/e2e.compose.yml up -d registry; \
	tests/e2e/tests.sh; exit_code=$$?; \
	docker-compose --project-directory=`pwd` \
	    -f tests/docker/e2e.compose.yml kill; \
	docker-compose --project-directory=`pwd` \
	    -f tests/docker/e2e.compose.yml rm -f; \
	exit $$exit_code

test_e2e: build test_e2e_built


test_unit: build_test test_unit_built

test_unit_built:
	docker run --rm platformregistryapi-test make _test_unit

_test_unit:
	pytest -vv tests/unit

test_integration: build_test test_integration_built

test_integration_built: pull
	docker-compose --project-directory=`pwd` \
	    -f tests/docker/e2e.compose.yml run test make _test_integration; \
	exit_code=$$?; \
	docker-compose --project-directory=`pwd` \
	    -f tests/docker/e2e.compose.yml kill; \
	docker-compose --project-directory=`pwd` \
	    -f tests/docker/e2e.compose.yml rm -f; \
	exit $$exit_code

_test_integration:
	pytest -vv tests/integration

lint: format
	mypy $(MYPY_DIRS)

format:
ifdef CI_LINT_RUN
	pre-commit run --all-files --show-diff-on-failure
else
	pre-commit run --all-files
endif


gke_k8s_login:
	@echo $(GKE_ACCT_AUTH) | base64 --decode > $(HOME)/gcloud-service-key.json
	gcloud auth activate-service-account --key-file $(HOME)/gcloud-service-key.json
	gcloud config set project $(GKE_PROJECT_ID)
	gcloud --quiet config set container/cluster $(GKE_CLUSTER_NAME)
	gcloud config set $(SET_CLUSTER_ZONE_REGION)
	gcloud auth configure-docker

aws_k8s_login:
	aws eks --region $(AWS_REGION) update-kubeconfig --name $(CLUSTER_NAME)

azure_k8s_login:
	az aks get-credentials --resource-group $(AZURE_RG_NAME) --name $(CLUSTER_NAME)

helm_install:
	curl https://raw.githubusercontent.com/kubernetes/helm/master/scripts/get | bash -s -- -v $(HELM_VERSION)
	helm init --client-only

gke_docker_push: build
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(IMAGE_K8S):$(IMAGE_TAG)
	docker tag $(IMAGE_K8S):$(IMAGE_TAG) $(IMAGE_K8S):$(GITHUB_SHA)
	docker push $(IMAGE_K8S)

ecr_login: build
	$$(aws ecr get-login --no-include-email --region $(AWS_REGION) )

docker_push: build
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(CLOUD_IMAGE):$(IMAGE_TAG)
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(CLOUD_IMAGE):$(GITHUB_SHA)
	docker push $(CLOUD_IMAGE):$(IMAGE_TAG)
	docker push $(CLOUD_IMAGE):$(GITHUB_SHA)

helm_deploy:
	helm init --client-only
	helm -f deploy/platformregistryapi/values-$(HELM_ENV)-$(CLOUD_PROVIDER).yaml --set "IMAGE=$(CLOUD_IMAGE):$(GITHUB_SHA)" upgrade --install platformregistryapi deploy/platformregistryapi --namespace platform --wait --timeout 600


artifactory_docker_push: build
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(ARTIFACTORY_DOCKER_REPO)/$(IMAGE_NAME):$(ARTIFACTORY_TAG)
	docker login $(ARTIFACTORY_DOCKER_REPO) --username=$(ARTIFACTORY_USERNAME) --password=$(ARTIFACTORY_PASSWORD)
	docker push $(ARTIFACTORY_DOCKER_REPO)/$(IMAGE_NAME):$(ARTIFACTORY_TAG)

artifactory_helm_push: helm_install
	mkdir -p temp_deploy/platformregistryapi
	cp -Rf deploy/platformregistryapi/. temp_deploy/platformregistryapi
	cp temp_deploy/platformregistryapi/values-template.yaml temp_deploy/platformregistryapi/values.yaml
	sed -i "s/IMAGE_TAG/$(ARTIFACTORY_TAG)/g" temp_deploy/platformregistryapi/values.yaml
	find temp_deploy/platformregistryapi -type f -name 'values-*' -delete
	helm init --client-only
	helm package --app-version=$(ARTIFACTORY_TAG) --version=$(ARTIFACTORY_TAG) temp_deploy/platformregistryapi/
	helm plugin install https://github.com/belitre/helm-push-artifactory-plugin
	helm push-artifactory $(IMAGE_NAME)-$(ARTIFACTORY_TAG).tgz $(ARTIFACTORY_HELM_REPO) --username $(ARTIFACTORY_USERNAME) --password $(ARTIFACTORY_PASSWORD)
