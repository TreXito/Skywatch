# ---- Stage 1: build dependencies ----
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Stage 2: runtime ----
FROM python:3.11-slim

# Non-root user
RUN groupadd -r skywatch && useradd -r -g skywatch skywatch

WORKDIR /app

COPY --from=builder /install /usr/local
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY config.example.yaml ./config.example.yaml

# Runtime dirs owned by the non-root user
RUN mkdir -p /app/data /app/logs && chown -R skywatch:skywatch /app

USER skywatch

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0 if urllib.request.urlopen('http://localhost:8080/api/health').status==200 else 1)"

CMD ["python", "-m", "backend.main"]
