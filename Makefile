.PHONY: all test clean
all test clean:

.PHONY: setup
setup:
	pip install -U pip pipx
	pipx install poetry
	poetry self add "poetry-dynamic-versioning[plugin]"
	poetry self add "poetry-plugin-export"
	poetry install --with dev
	poetry run pre-commit install

#.PHONY: venv
#venv:
#	poetry lock
#	poetry install --with dev;
#
#.PHONY: build
#build: venv poetry-plugins
#
#.PHONY: poetry-plugins
#poetry-plugins:
#	poetry self add "poetry-dynamic-versioning[plugin]"; \
#    poetry self add "poetry-plugin-export";

.PHONY: lint
lint:
	poetry run pre-commit run --all-files
	poetry run mypy

.PHONY: test_unit
test_unit:
	poetry run pytest -vv tests/unit

.PHONY: test_integration
test_integration: docker_build
	docker compose -f tests/docker/docker-compose.yaml pull -q; \
	docker compose --project-directory=`pwd` -f tests/docker/docker-compose.yaml up -d; \
	pytest -vv tests/integration; \
	exit_code=$$?; \
	docker compose -f tests/docker/docker-compose.yaml kill; \
	docker compose -f tests/docker/docker-compose.yaml rm -f; \
	exit $$exit_code

.PHONY: docker_build
docker_build: .python-version dist
	PY_VERSION=$$(cat .python-version) && \
	docker build -t platformregistryapi:latest --build-arg PY_VERSION=$$PY_VERSION .

.python-version:
	@echo "Error: .python-version file is missing!" && exit 1

.PHONY: dist
dist:
	rm -rf build dist; \
	poetry export -f requirements.txt --without-hashes -o requirements.txt; \
	poetry build -f wheel; \



#setup init:
#	pip install -U pip
#	pip install -e .[dev]
#	pre-commit install
#
#lint: format
#	mypy platform_registry_api tests
#
#format:
#ifdef CI
#	pre-commit run --all-files --show-diff-on-failure
#else
#	pre-commit run --all-files
#endif
#
#test_unit:
#	pytest -vv tests/unit
#
#test_integration: docker_build
#	docker compose -f tests/docker/docker-compose.yaml pull -q; \
#	docker compose --project-directory=`pwd` -f tests/docker/docker-compose.yaml up -d; \
#	pytest -vv tests/integration; \
#	exit_code=$$?; \
#	docker compose -f tests/docker/docker-compose.yaml kill; \
#	docker compose -f tests/docker/docker-compose.yaml rm -f; \
#	exit $$exit_code
#
#test_e2e: docker_build
#	docker compose --project-directory=`pwd` -f tests/docker/docker-compose.yaml up -d registry; \
#	tests/e2e/tests.sh; \
#	exit_code=$$?; \
#	docker compose -f tests/docker/docker-compose.yaml kill; \
#	docker compose -f tests/docker/docker-compose.yaml rm -f; \
#	exit $$exit_code
#
#docker_build: .docker_build
#
#.docker_build: $(find platform_registry_api -name "*.py") setup.cfg pyproject.toml Dockerfile
#	rm -rf build dist
#	pip install -U build
#	python -m build
#	docker build -t platformregistryapi:latest .
#	touch .docker_build
#
#build_up: docker_build
#	docker compose --project-directory=`pwd` -f tests/docker/docker-compose.yaml up
