#!/bin/sh
set -e

# Cron does not inherit the container's runtime environment — vars passed via
# `docker run -e` / docker-compose `environment:` (GMAIL_APP_PASSWORD, etc.)
# never reach a job cron launches. Dump the current environment to a file
# cron sources before running the job (see the crontab line in Dockerfile).
printenv | grep -Ev '^(HOME|PWD|SHLVL|_|OLDPWD)=' > /etc/environment

# The build-time `mkdir -p data/logs data/results` (Dockerfile) lives inside
# the image layer. docker-compose normally bind-mounts ./data over /app/data
# at runtime, which hides that layer completely. Recreate the directories on
# every start so a fresh host ./data (or one missing subfolders) doesn't
# leave cron's log redirect and the results writer pointed at a path that
# doesn't exist.
mkdir -p /app/data/logs /app/data/results

exec "$@"
