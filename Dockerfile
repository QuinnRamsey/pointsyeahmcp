# Production Dockerfile for PointsYeah MCP Middleware Server
# Targeted for Google Cloud Run deployment

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    HOST=0.0.0.0

WORKDIR /app

# Create non-privileged user for container security
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -m appuser

# Install production dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY src/ /app/src/

# Change ownership to non-privileged user
RUN chown -R appuser:appgroup /app

# Switch to non-privileged user
USER appuser

# Expose port (Cloud Run sets dynamic $PORT, defaulting to 8080)
EXPOSE 8080

# Start server (dynamically binds to $PORT via src.server)
CMD ["python3", "-m", "src.server"]
