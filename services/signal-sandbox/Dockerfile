FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1

WORKDIR /opt/byq-signal-sandbox

COPY services/signal-sandbox/pyproject.toml ./
COPY services/signal-sandbox/server.py ./server.py
COPY services/signal-sandbox/runner.py ./runner.py

RUN pip install --no-cache-dir . \
    && groupadd --system --gid 10002 sandbox \
    && useradd --system --uid 10002 --gid sandbox --no-create-home \
       --shell /usr/sbin/nologin sandbox

USER sandbox

EXPOSE 8500

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8500", "--workers", "1"]
