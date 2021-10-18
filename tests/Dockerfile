FROM platformregistryapi:latest

COPY pyproject.toml ./
COPY setup.cfg ./
RUN pip install -e .[dev]

COPY Makefile ./

COPY tests tests
