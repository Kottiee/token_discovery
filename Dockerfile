# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY token-pipeline/pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e "." --target /app/deps

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy installed packages
COPY --from=builder /app/deps /app/deps
ENV PYTHONPATH=/app/deps:/app

# Copy application source
COPY token-pipeline/ .

# Create data directory for SQLite
RUN mkdir -p /data
ENV DATABASE_URL=sqlite:////data/token_pipeline.db

# Non-root user
RUN useradd -m -u 1000 pipeline
RUN chown -R pipeline:pipeline /app /data
USER pipeline

# Health check: just verify the Python environment
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "from src.db import init_db; init_db(); print('OK')" || exit 1

ENTRYPOINT ["python", "-m", "src.main"]
