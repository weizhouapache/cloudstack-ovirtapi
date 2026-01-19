#!/bin/bash

# Check if required packages are installed
echo "Checking if required packages are installed..."
missing_packages=false

while IFS= read -r requirement; do
    # Skip empty lines and comments
    [[ -z "$requirement" || "$requirement" =~ ^[[:space:]]*# ]] && continue

    # Extract package name (remove version specifiers)
    package=$(echo "$requirement" | sed 's/[>=<~!].*//' | sed 's/[[:space:]]*$//' | sed 's/^[[:space:]]*//')

    # Skip if package name is empty after trimming
    [[ -z "$package" ]] && continue

    # Special handling for packages with different import names
    case "$package" in
        "fastapi") check_import="from fastapi import FastAPI" ;;
        "uvicorn") check_import="import uvicorn" ;;
        "httpx") check_import="import httpx" ;;
        "lxml") check_import="from lxml import etree" ;;
        "cryptography") check_import="from cryptography.fernet import Fernet" ;;
        "python-multipart") check_import="import multipart" ;;
        *) check_import="import $(echo $package | sed 's/-/_/g')" ;;
    esac

    if ! python -c "$check_import" &>/dev/null; then
        echo "Missing package: $package"
        missing_packages=true
    fi
done < requirements.txt

if [ "$missing_packages" = true ]; then
    echo "Some required packages are missing. Installing..."
    sudo pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "Failed to install required packages. Exiting."
        exit 1
    fi
else
    echo "All required packages are already installed."
fi

echo "Starting the application..."
sudo python -m app.main >/dev/null 2>&1 &
