build:
	docker build \
	    -t platformregistryapi:latest \
	    -t gcr.io/light-reality-205619/platformregistryapi:latest .

build_test: build
	docker build -t platformregistryapi-test -f tests/Dockerfile .

test_e2e_built:
	docker-compose --project-directory=`pwd` \
	    -f tests/docker/e2e.compose.yml up -d; \
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

_lint:
	flake8 platform_registry_api tests

format:
	isort -rc platform_registry_api tests
