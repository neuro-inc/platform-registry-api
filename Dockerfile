ARG PY_VERSION=3.13.1
FROM python:${PY_VERSION}-slim-bookworm AS builder

ENV PATH=/root/.local/bin:$PATH

WORKDIR /tmp
COPY requirements.txt /tmp/

RUN pip install --user --no-cache-dir -r requirements.txt

COPY dist /tmp/dist/
RUN pip install --user --no-cache-dir --find-links /tmp/dist platform-registry-api

FROM python:${PY_VERSION}-slim-bookworm AS runtime

LABEL org.opencontainers.image.source="https://github.com/neuro-inc/platform-registry-api"

ARG SERVICE_NAME="platform-registry-api"
ARG SERVICE_UID=1001
ARG SERVICE_GID=1001

RUN addgroup --gid $SERVICE_GID $SERVICE_NAME && \
    adduser --uid $SERVICE_UID --gid $SERVICE_GID \
    --home /home/$SERVICE_NAME --shell /bin/false \
    --disabled-password --gecos "" $SERVICE_NAME

COPY --from=builder /root/.local /home/$SERVICE_NAME/.local

WORKDIR /app

USER $SERVICE_NAME
ENV PATH=/home/$SERVICE_NAME/.local/bin:$PATH
ENV REGISTRY_API_PORT=8080
EXPOSE $REGISTRY_API_PORT

CMD ["platform-registry-api"]




## uvloop requires full image for compilation from sources
#FROM python:3.9.9-bullseye AS installer
#
#ENV PATH=/root/.local/bin:$PATH
#
## Copy to tmp folder to don't pollute home dir
#RUN mkdir -p /tmp/dist
#COPY dist /tmp/dist
#
#RUN ls /tmp/dist
#RUN pip install --user --find-links /tmp/dist platform-registry-api
#
#
#FROM python:3.9.9-slim-bullseye AS service
#
#LABEL org.opencontainers.image.source = "https://github.com/neuro-inc/platform-registry-api"
#
#WORKDIR /app
#
#COPY --from=installer /root/.local/ /root/.local/
#
#ENV PATH=/root/.local/bin:$PATH
#ENV NP_REGISTRY_API_PORT=8080
#EXPOSE $NP_REGISTRY_API_PORT
#
#CMD platform-registry-api
