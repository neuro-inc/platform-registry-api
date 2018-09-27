FROM python:3.6.6-stretch

WORKDIR /neuromation

ARG PIP_INDEX_URL

# installing dependencies ONLY
COPY setup.py ./
RUN pip install -e . && \
    pip uninstall -y platform-registry-api

# installing platform-registry-api
COPY platform_registry_api platform_registry_api
RUN pip install -e .

ENV NP_REGISTRY_API_PORT=8080
EXPOSE $NP_REGISTRY_API_PORT

CMD platform-registry-api
