build:
	docker build \
	    -t platformregistryapi:latest \
	    -t gcr.io/light-reality-205619/platformregistryapi:latest .

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

format:
	isort -rc platform_registry_api tests
