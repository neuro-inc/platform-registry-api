IMAGE_NAME ?= platformregistryapi
IMAGE_TAG ?= latest
ARTIFACTORY_TAG ?=$(shell echo "$(CIRCLE_TAG)" | awk -F/ '{print $$2}')
IMAGE_NAME_K8S ?= $(IMAGE_NAME)
IMAGE_K8S ?= $(GKE_DOCKER_REGISTRY)/$(GKE_PROJECT_ID)/$(IMAGE_NAME_K8S)
IMAGE_K8S_AWS ?= $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/$(IMAGE_NAME)
ISORT_DIRS := platform_registry_api tests setup.py
FLAKE8_DIRS := $(ISORT_DIRS)
BLACK_DIRS := $(ISORT_DIRS)

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

ifdef AWS_CLUSTER
    IMAGE_REPO ?= $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com
else
    IMAGE_REPO ?= $(GKE_DOCKER_REGISTRY)/$(GKE_PROJECT_ID)
endif
export IMAGE_REPO

init:
	@echo $(PIP_EXTRA_INDEX_URL)
	pip install -r requirements-test.txt

build:
	@docker build --build-arg PIP_INDEX_URL="$(PIP_EXTRA_INDEX_URL)" -t $(IMAGE_NAME):$(IMAGE_TAG) .

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

lint_after_building: build_test lint_built

lint_built:
	docker run --rm platformregistryapi-test make lint

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

lint:
	black --check $(BLACK_DIRS)
	flake8 $(FLAKE8_DIRS)
	isort -c -rc ${ISORT_DIRS}

format:
	isort -rc $(ISORT_DIRS)
	black $(BLACK_DIRS)

gke_login:
	sudo /opt/google-cloud-sdk/bin/gcloud --quiet components update --version 204.0.0
	sudo /opt/google-cloud-sdk/bin/gcloud --quiet components update --version 204.0.0 kubectl
	sudo chown circleci:circleci -R $$HOME
	@echo $(GKE_ACCT_AUTH) | base64 --decode > $(HOME)/gcloud-service-key.json
	gcloud auth activate-service-account --key-file $(HOME)/gcloud-service-key.json
	gcloud config set project $(GKE_PROJECT_ID)
	gcloud --quiet config set container/cluster $(GKE_CLUSTER_NAME)
	gcloud config set $(SET_CLUSTER_ZONE_REGION)
	gcloud auth configure-docker

aws_login:
	pip install --upgrade awscli
	aws eks --region $(AWS_REGION) update-kubeconfig --name $(AWS_CLUSTER_NAME)

_helm:
	curl https://raw.githubusercontent.com/kubernetes/helm/master/scripts/get | bash -s -- -v v2.11.0


gke_docker_push: build
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(IMAGE_K8S):$(IMAGE_TAG)
	docker tag $(IMAGE_K8S):$(IMAGE_TAG) $(IMAGE_K8S):$(CIRCLE_SHA1)
	docker push $(IMAGE_K8S)

ecr_login: build
	$$(aws ecr get-login --no-include-email --region $(AWS_REGION) )

aws_docker_push: build ecr_login
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(IMAGE_K8S_AWS):$(IMAGE_TAG)
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(IMAGE_K8S_AWS):$(CIRCLE_SHA1)
	docker push $(IMAGE_K8S_AWS):$(IMAGE_TAG)
	docker push $(IMAGE_K8S_AWS):$(CIRCLE_SHA1)

gke_k8s_deploy: _helm
	gcloud --quiet container clusters get-credentials $(GKE_CLUSTER_NAME) $(CLUSTER_ZONE_REGION)
	sudo chown -R circleci: $(HOME)/.kube
	helm -f deploy/platformregistryapi/values-$(HELM_ENV).yaml --set "IMAGE=$(IMAGE_K8S):$(CIRCLE_SHA1)" upgrade --install platformregistryapi deploy/platformregistryapi --wait --timeout 600

aws_k8s_deploy: _helm
	helm -f deploy/platformregistryapi/values-$(HELM_ENV)-aws.yaml --set "IMAGE=$(IMAGE_K8S_AWS):$(CIRCLE_SHA1)" upgrade --install platformregistryapi deploy/platformregistryapi --namespace platform --wait --timeout 600


artifactory_docker_push: build
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(ARTIFACTORY_DOCKER_REPO)/$(IMAGE_NAME):$(ARTIFACTORY_TAG)
	docker login $(ARTIFACTORY_DOCKER_REPO) --username=$(ARTIFACTORY_USERNAME) --password=$(ARTIFACTORY_PASSWORD)
	docker push $(ARTIFACTORY_DOCKER_REPO)/$(IMAGE_NAME):$(ARTIFACTORY_TAG)

artifactory_helm_push: _helm
	mkdir -p temp_deploy/platformregistryapi
	cp -Rf deploy/platformregistryapi/. temp_deploy/platformregistryapi
	cp temp_deploy/platformregistryapi/values-template.yaml temp_deploy/platformregistryapi/values.yaml
	sed -i "s/IMAGE_TAG/$(ARTIFACTORY_TAG)/g" temp_deploy/platformregistryapi/values.yaml
	find temp_deploy/platformregistryapi -type f -name 'values-*' -delete
	helm init --client-only
	helm package --app-version=$(ARTIFACTORY_TAG) --version=$(ARTIFACTORY_TAG) temp_deploy/platformregistryapi/
	helm plugin install https://github.com/belitre/helm-push-artifactory-plugin
	helm push-artifactory $(IMAGE_NAME)-$(ARTIFACTORY_TAG).tgz $(ARTIFACTORY_HELM_REPO) --username $(ARTIFACTORY_USERNAME) --password $(ARTIFACTORY_PASSWORD)

