setup init:
	pip install -U pip
	pip install -e .[dev]
	pre-commit install

lint: format
	mypy platform_registry_api tests

format:
ifdef CI
	pre-commit run --all-files --show-diff-on-failure
else
	pre-commit run --all-files
endif

test_unit:
	pytest -vv tests/unit

test_integration: docker_build
	docker compose -f tests/docker/docker-compose.yaml pull -q; \
	docker compose --project-directory=`pwd` -f tests/docker/docker-compose.yaml up -d; \
	pytest -vv tests/integration; \
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

docker_build: .docker_build

.docker_build: $(find platform_registry_api -name "*.py") setup.cfg pyproject.toml Dockerfile
	rm -rf build dist
	pip install -U build
	python -m build
	docker build -t platformregistryapi:latest .
	touch .docker_build

build_up: docker_build
	docker compose --project-directory=`pwd` -f tests/docker/docker-compose.yaml up
