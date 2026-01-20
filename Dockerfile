# Use Ubuntu 24.04 as the base image
FROM ubuntu:24.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV APP_HOME=/app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR ${APP_HOME}

# Copy the requirements file
COPY requirements.txt .

# Install Python dependencies using apt
RUN apt-get update && apt-get install -y \
    python3-fastapi \
    python3-uvicorn \
    python3-httpx \
    python3-lxml \
    python3-cryptography \
    python3-multipart \
    && rm -rf /var/lib/apt/lists/*

# Copy the application code
COPY . .

# Create logs directory
RUN mkdir -p logs

# Create certs directory
RUN mkdir -p certs

# Create a script to update config.ini with environment variables using sed
RUN echo '#!/bin/bash' > /update_config.sh && \
    echo '' >> /update_config.sh && \
    echo '# Update config.ini with environment variables if they are set' >> /update_config.sh && \
    echo 'if [ ! -z "$SERVER_HOST" ]; then sed -i "s/^host = .*/host = $SERVER_HOST/" config.ini; fi' >> /update_config.sh && \
    echo 'if [ ! -z "$SERVER_PORT" ]; then sed -i "s/^port = .*/port = $SERVER_PORT/" config.ini; fi' >> /update_config.sh && \
    echo 'if [ ! -z "$SERVER_PATH" ]; then sed -i "s@^path = .*@path = $SERVER_PATH@" config.ini; fi' >> /update_config.sh && \
    echo 'if [ ! -z "$PUBLIC_IP" ]; then sed -i "s/^public_ip = .*/public_ip = $PUBLIC_IP/" config.ini; fi' >> /update_config.sh && \
    echo 'if [ ! -z "$SSL_CERT_FILE" ]; then sed -i "s@^cert_file = .*@cert_file = $SSL_CERT_FILE@" config.ini; fi' >> /update_config.sh && \
    echo 'if [ ! -z "$SSL_KEY_FILE" ]; then sed -i "s@^key_file = .*@key_file = $SSL_KEY_FILE@" config.ini; fi' >> /update_config.sh && \
    echo 'if [ ! -z "$CLOUDSTACK_ENDPOINT" ]; then sed -i "s@^endpoint = .*@endpoint = $CLOUDSTACK_ENDPOINT@" config.ini; fi' >> /update_config.sh && \
    echo 'if [ ! -z "$HMAC_SECRET" ]; then sed -i "s/^hmac_secret = .*/hmac_secret = $HMAC_SECRET/" config.ini; fi' >> /update_config.sh && \
    echo 'if [ ! -z "$LOG_LEVEL" ]; then sed -i "s/^level = .*/level = $LOG_LEVEL/" config.ini; fi' >> /update_config.sh && \
    echo 'if [ ! -z "$LOG_FILE" ]; then sed -i "s@^file = .*@file = $LOG_FILE@" config.ini; fi' >> /update_config.sh && \
    chmod +x /update_config.sh

# Expose the application port
EXPOSE 443

# Set the command to run the application
CMD ["/bin/bash", "-c", "/update_config.sh && python3 -m app.main"]
