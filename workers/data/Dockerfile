FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/backend/pyproject.toml ./
COPY services/backend/app ./app
COPY workers/data/worker.py ./worker.py

RUN pip install --no-cache-dir . \
    && groupadd --system --gid 10004 byq \
    && useradd --system --uid 10004 --gid byq --no-create-home \
       --shell /usr/sbin/nologin byq

USER byq

CMD ["python", "worker.py"]
