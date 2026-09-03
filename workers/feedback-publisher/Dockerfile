FROM python:3.13-slim-bookworm

WORKDIR /opt/byq-feedback-publisher
RUN pip install --no-cache-dir cryptography==45.0.6 \
    && groupadd --system --gid 10006 byq-publisher \
    && useradd --system --uid 10006 --gid byq-publisher --no-create-home --shell /usr/sbin/nologin byq-publisher
COPY workers/feedback-publisher/publisher.py ./publisher.py

USER 10006:10006
CMD ["python", "publisher.py"]
