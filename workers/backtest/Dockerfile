FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/backend/pyproject.toml ./
COPY services/backend/app ./app
COPY workers/backtest/worker.py ./worker.py

RUN pip install --no-cache-dir ".[test]" \
    && groupadd --system --gid 10001 byq \
    && useradd --system --uid 10001 --gid byq --no-create-home \
       --shell /usr/sbin/nologin byq \
    && mkdir -p /var/lib/byq/domain /var/lib/byq/backtest-objects \
    && chown -R byq:byq /var/lib/byq

USER byq

CMD ["python", "worker.py"]
