# --- Stage 1: Builder ---
# Install dependencies in a full Python image (has build tools for C extensions)
FROM python:3.11-slim AS builder

WORKDIR /app

COPY requirements.txt .

# Install only production dependencies (skip test/load-test packages)
# --no-cache-dir keeps the image smaller
RUN pip install --no-cache-dir --prefix=/install \
    fastapi==0.115.12 \
    "uvicorn[standard]==0.34.2" \
    pydantic-settings==2.8.1 \
    redis==5.3.0


# --- Stage 2: Runtime ---
# Slim image with just the Python runtime — no pip, no build tools
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY main.py config.py ./
COPY algorithms/ ./algorithms/
COPY routers/ ./routers/
COPY models/ ./models/
COPY services/ ./services/
COPY storage/ ./storage/

# Non-root user for security (like running a .NET app under a service account)
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Health check — Docker/Compose uses this to determine container health
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
