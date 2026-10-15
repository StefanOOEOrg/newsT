FROM python:3.11-slim

WORKDIR /app

COPY analyzer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared module first
COPY shared /app/shared

# Copy analyzer code
COPY analyzer /app

CMD ["python", "main.py"]
