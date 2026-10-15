FROM python:3.11-slim

WORKDIR /app

COPY collector/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared module first
COPY shared /app/shared

# Copy collector code
COPY collector /app

CMD ["python", "main.py"]
