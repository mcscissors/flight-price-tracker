FROM python:3.12-slim

WORKDIR /app

# System deps for Playwright/Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium + its system dependencies
RUN playwright install --with-deps chromium

# Project code
COPY scripts/ scripts/
COPY config/ config/

# Cron job: run daily at 07:00
RUN echo "0 7 * * * cd /app && python -m scripts.run_all >> /app/data/logs/cron.log 2>&1" \
    | crontab -

# Data directory (mount as volume to persist logs + results)
RUN mkdir -p data/logs data/results

ENTRYPOINT ["cron", "-f"]
