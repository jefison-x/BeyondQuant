FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/backend/pyproject.toml ./
COPY services/backend/app ./app
COPY packages/contracts ./packages/contracts
COPY workers/optimization/worker.py ./worker.py

RUN pip install --no-cache-dir . \
    && groupadd --system --gid 10006 byq \
    && groupadd --system --gid 10001 byq-backtest-results \
    && useradd --system --uid 10006 --gid byq --groups byq-backtest-results --no-create-home \
       --shell /usr/sbin/nologin byq

USER byq

CMD ["python", "worker.py"]
