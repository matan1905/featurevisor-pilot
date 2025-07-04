# Multi-stage build for FeatureVisor Thompson Sampling Service
FROM node:18-alpine AS builder

# Install build dependencies
RUN apk add --no-cache python3 make g++ git

# Set working directory to parent (FeatureVisor root)
WORKDIR /app

# Copy FeatureVisor files (assuming this Dockerfile is in a submodule)
# Copy package files first for better caching
COPY package*.json ./
COPY yarn.lock* ./

# Install FeatureVisor dependencies
RUN npm ci || yarn install --frozen-lockfile

# Copy FeatureVisor source files
COPY . .

# Build FeatureVisor datafiles
RUN npx featurevisor build --schema-version=2

# Python service stage
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy built datafiles from builder stage
COPY --from=builder /app/dist /app/dist

# Copy service files
COPY ./services/pilot/requirements.txt .

# Add gunicorn to requirements.txt or install it here
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application code
COPY ./services/pilot/ .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 5050

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5050/stats')"

# Run with gunicorn instead of python app.py
CMD ["gunicorn", "--bind", "0.0.0.0:5050", "--workers", "4", "--timeout", "120", "app:app"]