# ---- Base Stage ----
FROM python:3.10-slim-bullseye AS base
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
WORKDIR /app

# ---- Builder Stage ----
FROM base AS builder
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt

# ---- Final Stage ----
FROM base

COPY --from=builder /app/wheels /wheels
RUN pip install --no-cache /wheels/*

# --- ADD THIS SECTION TO INSTALL FONTS ---
# 1. Install fontconfig, the standard Linux tool for managing fonts.
#    Playwright's browser depends on this to find and use new fonts.
RUN apt-get update && apt-get install -y --no-install-recommends fontconfig && rm -rf /var/lib/apt/lists/*

# 2. Copy your local font files into the container's standard font directory.
COPY Geist-Regular.otf Geist-Bold.otf /usr/share/fonts/opentype/

# 3. Rebuild the system's font cache so the new fonts are recognized immediately.
RUN fc-cache -f -v
# --- END FONT INSTALLATION SECTION ---

# Install Playwright browsers and their system dependencies
RUN playwright install --with-deps

# Copy the application source code
COPY main.py .
EXPOSE 8002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]