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

# Cron job: run daily at 07:00. Sources /etc/environment first — cron does
# not inherit the container's runtime env, so docker-entrypoint.sh writes it
# there on every container start (see that script for why).
RUN echo "0 7 * * * . /etc/environment && cd /app && python -m scripts.run_all >> /app/data/logs/cron.log 2>&1" \
    | crontab -

# Data directory (mount as volume to persist logs + results). Recreated at
# runtime by docker-entrypoint.sh too, since the volume mount replaces this
# build-time layer.
RUN mkdir -p data/logs data/results

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["cron", "-f"]
