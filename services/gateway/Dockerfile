FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/gateway/pyproject.toml ./
COPY services/gateway/app ./app
COPY services/gateway/tests ./tests

RUN pip install --no-cache-dir ".[test]"

EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
