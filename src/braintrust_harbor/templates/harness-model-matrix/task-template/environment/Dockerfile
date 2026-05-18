FROM python:3.12-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends bash ca-certificates git \
  && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app /logs/artifacts

COPY bin/demo-tool /usr/local/bin/demo-tool
RUN chmod +x /usr/local/bin/demo-tool

COPY install-tooling.sh /tmp/install-tooling.sh
COPY bootstrap-repo.sh /tmp/bootstrap-repo.sh
RUN bash /tmp/install-tooling.sh && bash /tmp/bootstrap-repo.sh

WORKDIR /app
