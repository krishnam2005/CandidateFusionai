# ── Build stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL maintainer="Eightfold AI Engineering <engineering@eightfold.ai>"
LABEL description="CandidateFusion AI — Multi-Source Candidate Data Transformer"
LABEL version="1.0.0"

# Security: create non-root user
RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

# Runtime system dependencies (for PDF processing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application code
COPY --chown=appuser:appgroup . .

# Create required directories
RUN mkdir -p inputs outputs logs \
    && chown -R appuser:appgroup /app

# Copy default .env if not present
RUN cp -n .env.example .env || true

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health', timeout=5)" || exit 1

# Default: run FastAPI server
CMD ["python", "-m", "uvicorn", "api.app:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

# Expose API port
EXPOSE 8000
