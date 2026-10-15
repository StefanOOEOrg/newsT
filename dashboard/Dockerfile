FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for SSL/TLS and yfinance
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libssl3 \
    && rm -rf /var/lib/apt/lists/*

# Install all requirements (dashboard + collector dependencies for direct initialization)
COPY dashboard/requirements.txt ./dashboard_requirements.txt
COPY collector/requirements.txt ./collector_requirements.txt
RUN pip install --no-cache-dir -r dashboard_requirements.txt && \
    pip install --no-cache-dir -r collector_requirements.txt

# Copy dashboard code first
COPY dashboard /app

# Copy shared module (may override dashboard/shared if it exists)
COPY shared /app/shared

# Copy collector module (needed for direct initialization)
COPY collector /app/collector

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
