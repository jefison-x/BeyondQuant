FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/backend/pyproject.toml ./
COPY services/backend/app ./app
COPY services/backend/tests ./tests
COPY plugins/dsh-byq/registry/plugins.json /app/plugin-registry/plugins.json
COPY config/dsh/generated/product-plugin-registry.json /app/plugin-registry/product-plugins.json
COPY config/dsh/generated/qualified-web-evidence-provenance.json /app/qualified-web-evidence-provenance.json
COPY config/dsh/generated/qualified-rollback-web-evidence-provenance.json /app/qualified-rollback-web-evidence-provenance.json
COPY config/dsh/generated/web-evidence-provenance.json /app/web-evidence-provenance.json
COPY config/dsh/generated/dsh-0.1.2rc1.web-evidence-provenance.json /app/dsh-0.1.2rc1.web-evidence-provenance.json

RUN pip install --no-cache-dir ".[test]"

RUN groupadd --system --gid 10001 byq \
    && useradd --system --uid 10001 --gid byq --no-create-home \
       --shell /usr/sbin/nologin byq \
    && mkdir -p /var/lib/byq/domain \
    && chown -R byq:byq /var/lib/byq/domain

USER byq

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
