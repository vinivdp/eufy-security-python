# ============================================
# Stage 1: Builder - Install dependencies
# ============================================
FROM python:3.11-slim as builder

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
ENV POETRY_VERSION=1.7.1
ENV POETRY_HOME=/opt/poetry
ENV POETRY_NO_INTERACTION=1
ENV POETRY_VIRTUALENVS_IN_PROJECT=1
ENV POETRY_VIRTUALENVS_CREATE=1
ENV PATH="$POETRY_HOME/bin:$PATH"

RUN curl -sSL https://install.python-poetry.org | python3 -

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml ./

# Create minimal poetry.lock if it doesn't exist
RUN touch poetry.lock

# Install dependencies (without dev dependencies)
RUN poetry install --no-root --only main --no-ansi || \
    (poetry lock --no-update && poetry install --no-root --only main --no-ansi)

# ============================================
# Stage 2: Runtime - Lean production image
# ============================================
FROM python:3.11-slim as runtime

# Install ffmpeg for video processing
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -u 1000 eufy && \
    mkdir -p /app /mnt/recordings /app/logs && \
    chown -R eufy:eufy /app /mnt/recordings

# Set working directory
WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder --chown=eufy:eufy /app/.venv /app/.venv

# Copy application code
COPY --chown=eufy:eufy src/ /app/src/
COPY --chown=eufy:eufy config/ /app/config/

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1
ENV PORT=10000

# Switch to non-root user
USER eufy

# Expose port
EXPOSE 10000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:10000/health')" || exit 1

# Run the application
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "10000"]