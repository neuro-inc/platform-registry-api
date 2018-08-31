FROM platformregistryapi:latest

COPY setup.cfg requirements-test.txt ./
RUN pip install -r requirements-test.txt

COPY Makefile ./

COPY tests tests
