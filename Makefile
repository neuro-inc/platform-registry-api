IMAGE_NAME ?= platformregistryapi
IMAGE_TAG ?= latest
IMAGE_NAME_K8S ?= $(IMAGE_NAME)
IMAGE_K8S ?= $(GKE_DOCKER_REGISTRY)/$(GKE_PROJECT_ID)/$(IMAGE_NAME_K8S)

ifdef CIRCLECI
    PIP_INDEX_URL ?= "https://$(DEVPI_USER):$(DEVPI_PASS)@$(DEVPI_HOST)/$(DEVPI_USER)/$(DEVPI_INDEX)"
else
    PIP_INDEX_URL ?= "$(shell python pip_extra_index_url.py)"
endif

build:
	@docker build --build-arg PIP_INDEX_URL="$(PIP_INDEX_URL)" -t $(IMAGE_NAME):$(IMAGE_TAG) --no-cache .

pull:
	-docker-compose --project-directory=`pwd` -p platformregistryapi \
	    -f tests/docker/e2e.compose.yml pull

build_test: build
	docker build -t platformregistryapi-test -f tests/Dockerfile .

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

lint: build_test lint_built

lint_built:
	docker run --rm platformregistryapi-test make _lint

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

_lint:
	flake8 platform_registry_api tests

format:
	isort -rc platform_registry_api tests

gke_login:
	sudo /opt/google-cloud-sdk/bin/gcloud --quiet components update --version 204.0.0
	sudo /opt/google-cloud-sdk/bin/gcloud --quiet components update --version 204.0.0 kubectl
	sudo chown circleci:circleci -R $$HOME
	@echo $(GKE_ACCT_AUTH) | base64 --decode > $(HOME)/gcloud-service-key.json
	gcloud auth activate-service-account --key-file $(HOME)/gcloud-service-key.json
	gcloud config set project $(GKE_PROJECT_ID)
	gcloud --quiet config set container/cluster $(GKE_CLUSTER_NAME)
	gcloud config set compute/zone $(GKE_COMPUTE_ZONE)
	gcloud auth configure-docker

_helm:
	curl https://raw.githubusercontent.com/kubernetes/helm/master/scripts/get | bash


gke_docker_push: build
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(IMAGE_K8S):$(IMAGE_TAG)
	docker tag $(IMAGE_K8S):$(IMAGE_TAG) $(IMAGE_K8S):$(CIRCLE_SHA1)
	docker push $(IMAGE_K8S)

gke_k8s_deploy_dev: _helm
	gcloud --quiet container clusters get-credentials $(GKE_CLUSTER_NAME)
	sudo chown -R circleci: $(HOME)/.kube
	helm --set "global.env=dev" --set "IMAGE.dev=$(IMAGE_K8S):$(CIRCLE_SHA1)" --wait --timeout 600 upgrade platformregistryapi deploy/platformregistryapi

gke_k8s_deploy_staging: _helm
	gcloud --quiet container clusters get-credentials $(GKE_STAGE_CLUSTER_NAME)
	sudo chown -R circleci: $(HOME)/.kube
	helm --set "global.env=staging" --set "IMAGE.staging=$(IMAGE_K8S):$(CIRCLE_SHA1)" --wait --timeout 600 upgrade platformregistryapi deploy/platformregistryapi
