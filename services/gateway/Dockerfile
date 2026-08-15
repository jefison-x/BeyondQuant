FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BYQ_WORKFLOW_TRACE_ROOT=/var/lib/byq/workflow-traces

WORKDIR /app

COPY services/gateway/pyproject.toml ./
COPY services/gateway/app ./app
COPY services/gateway/tests ./tests
COPY packages/contracts ./packages/contracts

RUN pip install --no-cache-dir ".[test]"

RUN groupadd --system --gid 10001 byq \
    && useradd --system --uid 10001 --gid byq --no-create-home \
       --shell /usr/sbin/nologin byq \
    && mkdir -p /var/lib/byq/workflow-traces \
    && chown -R byq:byq /var/lib/byq/workflow-traces

USER byq

EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
