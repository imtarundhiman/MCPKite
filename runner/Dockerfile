FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY runner/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app/__init__.py /app/shared/__init__.py
COPY backend/app/sandbox_limits.py /app/shared/sandbox_limits.py
COPY runner/app ./app

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
