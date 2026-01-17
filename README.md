# CloudStack oVirt-Compatible API Server
oVirt-Compatible REST API server for Apache CloudStack written in Python

# Overview

This project implements an oVirt / UHAPI–compatible REST API server that enables
Veeam Backup & Replication to integrate with Apache CloudStack (KVM).

The service translates oVirt API calls from Veeam into CloudStack API calls,
returning oVirt-compatible XML responses.

# Key Features

- Python + FastAPI
- HTTPS only (self-managed certificates)
- oVirt Basic Auth and OAuth/Bearer support
- Deterministic, non-reversible credential handling
- CloudStack authentication bridge
- XML-only responses (Veeam compatible)
- Extensible UHAPI surface

# HTTPS & Certificate Management

This service always runs over HTTPS.

## Certificate loading order

- Load certificate/key from config.ini
- If not configured:
  - Load default certificate paths
- If still missing:
  - Generate a self-signed certificate
  - Persist it locally for reuse

Self-signed certificates are supported.
Veeam will prompt the user to trust the certificate once.

# Authentication

## Supported Methods

- oVirt Basic Authentication
- oVirt Bearer / OAuth token

## Basic Authentication Flow

Veeam sends:
```
Authorization: Basic base64(username@domain:password)
```

Decoded format:
```
username@domain:password
```

Behavior:

- Credentials are validated via CloudStack login
- A session is created and cached

## Credential Security Model (Important)

**Design Requirements**

- Same input → same output
- Cannot be decrypted
- Safe to store in memory / cache
- No plaintext secrets stored or logged

**Solution: HMAC-SHA256 (One-Way Hash)**
```
hash = HMAC_SHA256(server_secret, auth_value)
```

- Deterministic
- Non-reversible
- Industry standard
- Matches oVirt / Veeam internal behavior

**What Is Hashed**
- Basic Auth: username@domain:password
- Bearer Auth: full bearer token string

Raw credentials are never stored or logged.

# CloudStack Integration

## Login Flow

- Extract credentials from oVirt auth header
- Call CloudStack API:
```
POST command=login?username=User&password=Password&domain=Domain
```

CloudStack returns:
- sessionkey
- userid
- account
- domainid
- apikey
- secretkey

Session is cached internally
Subsequent CloudStack calls reuse the session

# Response Format

- XML only
- Content-Type: application/xml
- oVirt-compatible structure
- JSON intentionally not supported

Example:
```
<api>
  <product_info>
    <name>CloudStack oVirt-API</name>
    <vendor>weizhouapache</vendor>
    <version>1.0</version>
  </product_info>
</api>
```

# Implemented API (Initial)

```
HEAD /ovirt-engine/api
GET  /ovirt-engine/api
```

Purpose:
- Authentication handshake
- Capability discovery
- Required by Veeam

# APIs Used by Veeam (Planned)

## Inventory

```
GET /ovirt-engine/api/datacenters
GET /ovirt-engine/api/clusters
GET /ovirt-engine/api/hosts
GET /ovirt-engine/api/storageDomains
GET /ovirt-engine/api/vms
```

## Backup & Snapshot Control

```
POST   /ovirt-engine/api/vms/{vm_id}/backups
GET    /ovirt-engine/api/vms/{vm_id}/backups/{backup_id}
POST   /ovirt-engine/api/vms/{vm_id}/backups/{backup_id}/finalize
DELETE /ovirt-engine/api/vms/{vm_id}/checkpoints/{checkpoint_id}
```

## Image Transfer

```
POST /ovirt-engine/api/imagetransfers
GET  /ovirt-engine/api/imagetransfers/{id}
POST /ovirt-engine/api/imagetransfers/{id}/finalize
```

## Disk Extents

```
GET /images/{image_id}/extents
GET /images/{image_id}
```

## Restore

```
POST /ovirt-engine/api/vms
POST /ovirt-engine/api/disks
POST /ovirt-engine/api/imagetransfers   (write mode)
```

# Configuration Example

Example **config.ini**

```
[server]
host = 0.0.0.0
port = 8443

[ssl]
cert_file = ./certs/server.crt
key_file  = ./certs/server.key

[cloudstack]
endpoint = https://cloudstack.mgmt.server/client/api

[security]
hmac_secret = very-long-random-secret
```

# Logging

- No plaintext credentials
- Authentication events logged (hashed IDs only)
- CloudStack calls logged without secrets
- Designed for correlation with Veeam logs

# Design Principles

- Behavioral compatibility > schema perfection
- HTTPS only
- Stateless API + session cache
- Minimal UHAPI surface
- Security first

# License

Apache License 2.0

# Getting Started

Build and run:

```
python -m app.main
```
