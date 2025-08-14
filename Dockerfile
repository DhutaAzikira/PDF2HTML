# ---- Base Stage ----
# Use an official Python runtime as a parent image.
# Using a specific version is better for reproducibility.
FROM python:3.10-slim-buster AS base

# Set environment variables
# Prevents python from writing .pyc files to disc
ENV PYTHONDONTWRITEBYTECODE 1
# Prevents python from buffering stdout and stderr
ENV PYTHONUNBUFFERED 1

# Set the working directory in the container
WORKDIR /app

# ---- Builder Stage ----
# This stage installs the dependencies
FROM base AS builder

# Install build-time dependencies that might be needed by Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy the requirements file and install dependencies
# This is done in a separate step to leverage Docker's layer caching
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt


# ---- Final Stage ----
# This is the final, production-ready image
FROM base

# Install runtime dependencies for pdfkit
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    wget \
    libxrender1 \
    libfontconfig1 \
    libxext6 \
    xfonts-75dpi \
    xfonts-base && \
    wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.buster_amd64.deb && \
    dpkg -i wkhtmltox_0.12.6-1.buster_amd64.deb && \
    apt-get -f install -y && \
    rm wkhtmltox_0.12.6-1.buster_amd64.deb && \
    rm -rf /var/lib/apt/lists/*

# Copy the pre-built wheels from the builder stage
COPY --from=builder /app/wheels /wheels

# Install the Python dependencies from the local wheels
# This is faster and doesn't require build tools in the final image
RUN pip install --no-cache /wheels/*

# Copy the application source code into the container
COPY main.py .

# Expose the port the app will run on.
# CapRover expects the application to listen on port 80.
EXPOSE 8002

# Define the command to run the application.
# This command starts the Uvicorn server to listen on all interfaces on port 80.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
