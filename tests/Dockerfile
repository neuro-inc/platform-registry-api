FROM platformregistryapi:latest

COPY requirements-test.txt ./
RUN pip install -r requirements.txt

COPY Makefile ./

COPY tests tests
