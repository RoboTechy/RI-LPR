FROM python:3.11-slim

# pip's default per-chunk read timeout (15s) can be too short on a
# slower connection - more time + retries instead of giving up.
ENV PIP_DEFAULT_TIMEOUT=180
ENV PIP_RETRIES=10

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
# The PIP_DEFAULT_TIMEOUT/PIP_RETRIES above weren't enough on their own -
# on a flaky connection, pip can fail to even fetch a package's version
# list within 180s and give up outright ("from versions: none") rather
# than retrying a fresh attempt. Retrying the whole command a few times
# (successful earlier steps elsewhere in this project suggest the link
# drops in and out rather than being dead) works around that.
RUN set -e; \
    for i in 1 2 3 4 5; do \
      pip install --no-cache-dir -r /app/backend/requirements.txt && exit 0; \
      echo "pip install attempt $i failed, retrying in 15s..."; \
      sleep 15; \
    done; \
    echo "pip install failed after 5 attempts"; exit 1

COPY backend /app/backend

ENV PYTHONPATH=/app/backend
WORKDIR /app/backend

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
