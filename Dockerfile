# ── AgroNexus Backend ────────────────────────────────────────────────────────
FROM python:3.12-slim

# System deps needed by psycopg2, Pillow, reportlab
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc libjpeg-dev zlib1g-dev libfreetype6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Collect static files (whitenoise serves them at runtime).
# SECRET_KEY is only needed so Django can start during build — not used at runtime.
ARG SECRET_KEY="build-time-dummy-key-collectstatic-only"
RUN SECRET_KEY=${SECRET_KEY} DEBUG=False python manage.py collectstatic --noinput

# Run as non-root
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--config", "gunicorn.conf.py"]
