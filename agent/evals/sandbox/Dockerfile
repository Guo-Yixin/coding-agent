# Minimal repeatable runtime for the independent Python benchmark repository.
# The OpenSandbox service supplies the outer isolation; this image only pins
# the tools the fixed taskboard cases need inside each disposable container.
FROM docker.m.daocloud.io/library/python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --disable-pip-version-check pytest
