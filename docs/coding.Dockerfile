FROM python:3.12-slim
COPY actron/model_cli.py /opt/actron_model_cli.py
USER 65534:65534
WORKDIR /work
