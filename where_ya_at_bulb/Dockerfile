ARG BUILD_FROM=ghcr.io/hassio-addons/base:14.0.2
FROM ${BUILD_FROM}

ENV PYTHONUNBUFFERED=1

RUN apk add --no-cache \
  python3 \
  py3-flask \
  py3-yaml

COPY rootfs /

WORKDIR /app
COPY app /app

EXPOSE 8099

CMD ["/usr/bin/python3", "-m", "app.server"]
