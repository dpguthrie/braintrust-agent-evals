FROM python:3.12-alpine

RUN apk add --no-cache bash coreutils curl git jq nodejs npm ripgrep

RUN adduser -D -s /bin/bash agent \
  && mkdir -p /home/agent/.npm-global \
  && chown -R agent:agent /home/agent/.npm-global

WORKDIR /app

COPY bin/acme /usr/local/bin/acme
COPY app/ /app/

RUN chmod +x /usr/local/bin/acme \
  && mkdir -p /logs/artifacts /logs/verifier \
  && chown -R agent:agent /app /logs \
  && chmod -R a-w /app/src

ENV NPM_CONFIG_PREFIX="/home/agent/.npm-global" \
    PATH="/home/agent/.npm-global/bin:/usr/local/bin:${PATH}" \
    ACME_COMMAND_LOG="/logs/artifacts/command-log.jsonl"
