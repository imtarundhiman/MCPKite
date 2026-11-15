FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY runner/app/egress_proxy.py /app/egress_proxy.py

USER 65532:65532
ENTRYPOINT ["python", "-I", "/app/egress_proxy.py"]
