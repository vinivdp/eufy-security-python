# Simple single-stage Dockerfile
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=10000

# Install system dependencies including ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 eufy && \
    mkdir -p /app /mnt/recordings /app/logs && \
    chown -R eufy:eufy /app /mnt/recordings

# Set working directory
WORKDIR /app

# Install Poetry
RUN pip install --no-cache-dir poetry==1.7.1

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Install dependencies globally (no venv)
RUN poetry config virtualenvs.create false && \
    poetry install --no-root --only main --no-interaction --no-ansi

# Copy application code
COPY --chown=eufy:eufy src/ ./src/
COPY --chown=eufy:eufy config/ ./config/

# Switch to non-root user
USER eufy

# Expose port
EXPOSE 10000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:10000/health').read()" || exit 1

# Run the application
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "10000"]
