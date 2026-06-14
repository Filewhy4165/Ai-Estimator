# ── Stage 1: Builder ────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies (gcc for native extensions like bcrypt/cryptography)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy requirement files first for cache efficiency
COPY requirements/runtime.lock.txt requirements/runtime.lock.txt

# Install Python packages into a separate prefix
RUN pip install --no-cache-dir --prefix=/install \
    -r requirements/runtime.lock.txt

# ── Stage 2: Runtime ────────────────────────────────────────────────────
FROM python:3.11-slim

# Install runtime system dependencies (libpq for asyncpg, curl for healthcheck)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY ai_estimator/ ai_estimator/
COPY service/ service/
COPY config/ config/
COPY pyproject.toml pyproject.toml

# Install the app itself so metadata.version() works
RUN pip install --no-cache-dir --no-deps .

# Switch to non-root user
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "service.app:app", "--host", "0.0.0.0", "--port", "8000"]
