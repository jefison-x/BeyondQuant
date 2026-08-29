FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY services/backend/pyproject.toml ./
COPY services/backend/app ./app
COPY workers/ml/worker.py ./worker.py

RUN pip install --no-cache-dir . \
    && pip install --no-cache-dir "numpy==2.3.3" "lightgbm==4.7.0" \
    && groupadd --system --gid 10005 byq \
    && useradd --system --uid 10005 --gid byq --no-create-home \
       --shell /usr/sbin/nologin byq \
    && mkdir -p /var/lib/byq/ml-objects \
    && chown -R byq:byq /var/lib/byq/ml-objects

USER byq

HEALTHCHECK --interval=15s --timeout=5s --retries=4 \
  CMD ["python", "worker.py", "--healthcheck"]

CMD ["python", "worker.py"]
