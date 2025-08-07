.PHONY: all test clean
all test clean:

.PHONY: install-poetry
install-poetry:
	pip install -U pip pipx
	pipx install poetry

.PHONY: venv
venv:
	poetry lock
	poetry install --with dev

.PHONY: poetry-plugins
poetry-plugins:
	poetry self add "poetry-dynamic-versioning[plugin]"; \
	poetry self add "poetry-plugin-export";

.PHONY: setup
setup: install-poetry poetry-plugins venv
	poetry run pre-commit install

.PHONY: lint
lint:
	poetry run pre-commit run --all-files
	poetry run mypy

.python-version:
	@echo "Error: .python-version file is missing!" && exit 1

.PHONY: docker_build
docker_build: .python-version dist
	PY_VERSION=$$(cat .python-version) && \
	docker build -t platformregistryapi:latest --build-arg PY_VERSION=$$PY_VERSION .

.PHONY: build_up
build_up: docker_build
	docker compose --project-directory=`pwd` -f tests/docker/docker-compose.yaml up

.PHONY: dist
dist:
	rm -rf build dist; \
	poetry export -f requirements.txt --without-hashes -o requirements.txt; \
	poetry build -f wheel; \

.PHONY: test_unit
test_unit:
	poetry run pytest -svv tests/unit

.PHONY: test_integration
test_integration: docker_build
	docker compose -f tests/docker/docker-compose.yaml pull -q; \
	docker compose --project-directory=`pwd` -f tests/docker/docker-compose.yaml up -d; \
	bash tests/integration/project_deleter_fixture.sh; \
	poetry run pytest -svv tests/integration; \
	exit_code=$$?; \
	docker compose -f tests/docker/docker-compose.yaml kill; \
	docker compose -f tests/docker/docker-compose.yaml rm -f; \
	exit $$exit_code

test_e2e: docker_build
	docker compose --project-directory=`pwd` -f tests/docker/docker-compose.yaml up -d registry; \
	tests/e2e/tests.sh; \
	exit_code=$$?; \
	docker compose -f tests/docker/docker-compose.yaml kill; \
	docker compose -f tests/docker/docker-compose.yaml rm -f; \
	exit $$exit_code
