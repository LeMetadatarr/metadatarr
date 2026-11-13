FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# `git` is required at install time: several dependencies are pinned to
# `git+https://...@dev` refs until they are published to PyPI.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN pip install --upgrade pip \
    && pip install ".[server]"

# HTTP response cache + user mappings overlay live outside the image.
ENV METADATARR_HTTP_CACHE=/data/http-cache \
    XDG_CONFIG_HOME=/config
VOLUME ["/data", "/config"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["metadatarr", "serve", "--host", "0.0.0.0", "--port", "8000"]
