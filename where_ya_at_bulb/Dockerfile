ARG BUILD_FROM=ghcr.io/hassio-addons/base:14.0.2
FROM ${BUILD_FROM}

ENV PYTHONUNBUFFERED=1

RUN apk add --no-cache python3 py3-pip \
  && pip3 install --no-cache-dir flask==3.0.0 pyyaml==6.0.1

COPY rootfs /

WORKDIR /app
COPY app /app

EXPOSE 8099

CMD ["/usr/bin/python3", "-m", "app.server"]
