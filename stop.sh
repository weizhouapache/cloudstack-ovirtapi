#!/bin/bash

# Find and kill the Python application process
echo "Stopping the CloudStack oVirt-Compatible API Server..."

# Find the process ID of the application
PID=$(ps aux | grep "python -m app.main" | grep -v grep | awk "{print \$2}")

if [ -n "$PID" ]; then
    echo "Found process with PID: $PID"
    sudo kill $PID
    if [ $? -eq 0 ]; then
        echo "Successfully stopped the application."
    else
        echo "Failed to stop the application with PID: $PID"
        exit 1
    fi
else
    echo "Application is not running or could not be found."
fi
