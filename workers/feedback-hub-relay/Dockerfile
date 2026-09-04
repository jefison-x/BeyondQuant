FROM python:3.13-slim-bookworm

WORKDIR /opt/byq-feedback-hub-relay
RUN groupadd --system --gid 10007 byq-relay \
    && useradd --system --uid 10007 --gid byq-relay --no-create-home --shell /usr/sbin/nologin byq-relay
COPY workers/feedback-hub-relay/relay.py ./relay.py

USER 10007:10007
CMD ["python", "relay.py"]
