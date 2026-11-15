FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY runner/app/runner.py /app/runner.py

USER 65532:65532
ENTRYPOINT ["python", "-I", "/app/runner.py"]
