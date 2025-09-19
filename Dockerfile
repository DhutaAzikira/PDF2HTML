# ---- Base Stage ----
# UPGRADE: Switched to bullseye for modern Playwright dependencies
FROM python:3.10-slim-bullseye AS base
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
WORKDIR /app

# ---- Builder Stage ----
FROM base AS builder
# NOTE: The sed command to fix repository URLs is not needed for bullseye
# Install build-time dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*
# Copy and install Python dependencies
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt

# ---- Final Stage ----
FROM base

# Copy and install the pre-built wheels
COPY --from=builder /app/wheels /wheels
RUN pip install --no-cache /wheels/*

# Install Playwright browsers and their system dependencies
# This will now succeed on the newer bullseye base image
RUN playwright install --with-deps

# Copy the application source code
COPY main.py .
EXPOSE 8002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]