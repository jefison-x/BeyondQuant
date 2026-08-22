FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/backend/pyproject.toml ./
COPY services/backend/app ./app
COPY workers/signal/worker.py ./worker.py

RUN pip install --no-cache-dir . \
    && groupadd --system --gid 10003 byq \
    && useradd --system --uid 10003 --gid byq --no-create-home \
       --shell /usr/sbin/nologin byq

USER byq

CMD ["python", "worker.py"]
