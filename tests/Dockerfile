FROM platformregistryapi:latest

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY Makefile ./

COPY tests tests
