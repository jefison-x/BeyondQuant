FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/backend/pyproject.toml ./
COPY services/backend/app ./app
COPY services/backend/tests ./tests

RUN pip install --no-cache-dir ".[test]"

RUN groupadd --system --gid 10001 byq \
    && useradd --system --uid 10001 --gid byq --no-create-home \
       --shell /usr/sbin/nologin byq

USER byq

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
