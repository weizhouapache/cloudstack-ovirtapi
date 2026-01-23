# ovirt-imageio Service

This service implements the ovirt-imageio functionality for uploading and downloading of disks and snapshots using HTTPS.

## Features

- Direct service on port 54322: Exposes images over HTTPS, allowing clients to read and write images
- Proxy service on port 54323: Allows clients without access to the host network to read and write images
- Range requests support for efficient image transfers
- Integration with the existing image transfer system

## Architecture

The service acts in two different roles:
1. As a service exposing images over HTTPS (port 54322)
2. As a proxy service for clients without direct network access (port 54323)

## Endpoints

### Direct Service (Port 54322)
- `GET /images/{transfer_id}` - Download image data
- `PUT /images/{transfer_id}` - Upload image data
- `PATCH /images/{transfer_id}` - Incremental image updates

### Proxy Service (Port 54323)
- `GET /images/{transfer_id}` - Download image data via proxy
- `PUT /images/{transfer_id}` - Upload image data via proxy
- `PATCH /images/{transfer_id}` - Incremental image updates via proxy

## Configuration

The service integrates with the existing image transfer system and uses the same transfer data stored in the application's memory.

## Security

HTTPS is used for all communications. In production, proper SSL certificates should be configured.
