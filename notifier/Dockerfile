FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY notifier/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy notifier code
COPY notifier /app
COPY shared /app/shared

# Run notifier
CMD ["python", "main.py"]
