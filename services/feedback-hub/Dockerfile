FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY services/feedback-hub/pyproject.toml ./
COPY services/feedback-hub/app ./app
COPY services/feedback-hub/tests ./tests
RUN pip install --no-cache-dir ".[test]" \
    && groupadd --system --gid 10008 byq-hub \
    && useradd --system --uid 10008 --gid byq-hub --no-create-home --shell /usr/sbin/nologin byq-hub
USER 10008:10008
EXPOSE 8800
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8800", "--proxy-headers", "--forwarded-allow-ips", "*"]
