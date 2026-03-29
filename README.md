# CloudStack oVirt-Compatible API Server

oVirt-Compatible REST API server for Apache CloudStack written in Python

# Overview

This project implements an oVirt / UHAPI–compatible REST API server that enables
Veeam Backup & Replication to integrate with Apache CloudStack (KVM).

The service translates oVirt API calls from Veeam into CloudStack API calls,
returning oVirt-compatible XML responses.

# Architecture

The project consists of three services deployed across two types of hosts:

```
  Veeam Backup & Replication
          |
          | HTTPS :443
          v
  ┌─────────────────────────────────────────────────────┐
  │  CloudStack Management Server (or connected server) │
  │                                                     │
  │  App (API Server)              port 443             │
  │    - oVirt-compatible REST API                      │
  │    - Translates oVirt → CloudStack API calls        │
  │                                                     │
  │  ImageIO Proxy                 port 54323           │
  │    - Routes transfer requests to KVM hosts          │
  └─────────────────────────────────────────────────────┘
          |
          | HTTPS :54322
          v
  ┌─────────────────────────────────────────────────────┐
  │  KVM Host (one or more)                             │
  │                                                     │
  │  ImageIO Service               port 54322           │
  │    - Handles disk backup via libvirt + NBD          │
  │    - Manages backup checkpoints                     │
  │    - Streams disk data for backup/restore           │
  └─────────────────────────────────────────────────────┘
```

| Service | Runs On | Port | Start Script | Stop Script |
|---------|---------|------|--------------|-------------|
| App (API Server) | CloudStack management server | 443 | `run.sh` | `stop.sh` |
| ImageIO Proxy | CloudStack management server | 54323 | `proxy_run.sh` | `proxy_stop.sh` |
| ImageIO Service | KVM host | 54322 | `imageio_run.sh` | `imageio_stop.sh` |

# Key Features

- Python + FastAPI
- HTTPS only across all services (self-managed certificates)
- oVirt Basic Auth and OAuth/Bearer support
- Deterministic, non-reversible credential handling
- CloudStack authentication bridge
- XML-only responses (Veeam compatible)
- Incremental backup via libvirt checkpoints and NBD (Network Block Device)
- Extensible UHAPI surface

# HTTPS & Certificate Management

All three services run over HTTPS and share the same certificate infrastructure.

## Certificate loading order

- Load certificate/key from config.ini
- If not configured:
  - Load default certificate paths
- If still missing:
  - Generate a self-signed certificate and CA
  - Persist it locally for reuse

Self-signed certificates are supported.
Veeam will prompt the user to trust the certificate once.

The CA certificate is distributed to clients via:
```
GET /ovirt-engine/services/pki-resource?resource=ca-certificate&format=X509-PEM-CA
```

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

Session is cached internally.
Subsequent CloudStack calls reuse the session.

# Response Format

- XML only
- Content-Type: application/xml
- oVirt-compatible structure
- JSON intentionally not supported

Example:
```xml
<api>
  <product_info>
    <name>CloudStack oVirt-API</name>
    <vendor>weizhouapache</vendor>
    <version>1.0</version>
  </product_info>
</api>
```

# Configuration

## App Configuration (`config.ini`)

Located at the project root. Used by the API server and referenced when contacting the ImageIO service.

```ini
[server]
host = 0.0.0.0
port = 443
path = /ovirt-engine
public_ip =                         # Auto-detected if empty

[ssl]
ca_cert_file = ./certs/root-ca.crt
ca_key_file = ./certs/root-ca.key   # Required only if cert_file or key_file are missing
cert_file = ./certs/server.crt
key_file = ./certs/server.key

[cloudstack]
endpoint = http://localhost:8080/client/api

[security]
hmac_secret = very-long-random-secret

[logging]
level = DEBUG
file = ./logs/app.log

[imageio]
internal_token = 1234567890         # Shared secret for App ↔ ImageIO communication
```

## ImageIO Configuration (`imageio/config.ini`)

Located in the `imageio/` directory. Must be present on each KVM host running the ImageIO service, and on the management server running the ImageIO proxy.

```ini
[imageio]
listen_host = 0.0.0.0
listen_port = 54322
path = /images
public_ip =                         # Auto-detected if empty
internal_token = 1234567890         # Must match the token in the app's config.ini

[proxy]
proxy_listen_host = 0.0.0.0
proxy_listen_port = 54323
proxy_public_ip =
proxy_internal_token = 1234567890

[ssl]
ca_cert_file = ./certs/root-ca.crt
ca_key_file = ./certs/root-ca.key   # Required only if cert_file or key_file are missing
cert_file = ./certs/server.crt
key_file = ./certs/server.key

[logging]
level = DEBUG
file = ./logs/imageio.log
```

# ImageIO Service

The ImageIO service runs on each **KVM host** (port 54322) and handles disk-level data operations for backup and restore. It is contacted directly by the API server and by Veeam (via the ImageIO proxy).

## Purpose

- Performs VM disk backups using libvirt checkpoints (full and incremental)
- Streams disk data via NBD (Network Block Device) for efficient transfer
- Hosts transfer sessions that Veeam uses to download or upload disk images

## Backup Mechanism

1. The API server contacts the ImageIO service at `https://{kvm_host_ip}:54322/images/internal/backup/{vm_name}`
2. The ImageIO service uses libvirt to:
   - Create a backup checkpoint for each disk
   - Track the checkpoint ID for incremental backup support
3. Disk data is streamed via NBD (libnbd)
4. Checkpoint metadata is stored persistently in `/backup/meta/{vm}.json`
5. Old checkpoints are automatically cleaned up

**Note**: Backups require the VM to be running (libvirt CBT checkpoints only work on active VMs).

## ImageIO Service Endpoints

These are internal endpoints used by the API server and proxy. They are not called directly by Veeam.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/images/internal/backup/{vm_name}` | POST | Start a backup session for a VM |
| `/images/internal/backup/{vm_name}/status` | GET | Check backup session status |
| `/images/internal/backup/{vm_name}/finalize` | POST | Finalize backup and clean up |
| `/images/internal/download` | POST | Create a download transfer session |
| `/images/transfers/{transfer_id}` | GET | Get transfer status |
| `/images/transfers/{transfer_id}/upload` | POST | Upload data (restore) |
| `/images/transfers/{transfer_id}/download` | GET | Download data (backup) |
| `/images/transfers/{transfer_id}/finalize` | POST | Finalize a transfer |

## Running the ImageIO Service (on each KVM host)

```bash
# Start
./imageio_run.sh

# Stop
./imageio_stop.sh

# Manual start
sudo python -m imageio.service
```

# ImageIO Proxy

The ImageIO proxy runs on the **CloudStack management server** (port 54323) alongside the API server. It routes Veeam's image transfer requests to the correct KVM host.

## Purpose

- Veeam connects to a single proxy endpoint for all disk transfers
- The proxy maps each transfer ID to the appropriate target KVM host IP
- Transparently forwards GET/POST/PUT/DELETE requests to `https://{kvm_host}:54322`

## Running the ImageIO Proxy

```bash
# Start
./proxy_run.sh

# Stop
./proxy_stop.sh

# Manual start
sudo python -m imageio.proxy
```

# Logging

- No plaintext credentials are ever logged
- Authentication events logged with hashed IDs only
- CloudStack API calls logged without secrets
- All three services write to separate configurable log files

# Design Principles

- Behavioral compatibility > schema perfection
- HTTPS only across all services
- Stateless API + in-memory session cache
- Minimal UHAPI surface
- Security first

# License

Apache License 2.0

# Getting Started

## Prerequisites

Before running the application, ensure all required packages from `requirements.txt` are installed:

```bash
pip install -r requirements.txt
```

On Ubuntu systems, you can alternatively install the required packages using apt:

```bash
sudo apt update
sudo apt install python3-fastapi python3-uvicorn python3-httpx python3-lxml python3-cryptography python3-multipart python3-libvirt python3-libnbd
```

## Deployment Steps

**1. On the CloudStack management server (or a connected server):**

- Configure `config.ini` with your CloudStack endpoint, HMAC secret, and `internal_token`
- Start the API server: `./run.sh`
- Start the ImageIO proxy: `./proxy_run.sh`

**2. On each KVM host:**

- Copy the project (use `sync.sh` to rsync to multiple hosts)
- Configure `imageio/config.ini` — ensure `internal_token` matches the value in `config.ini`
- Start the ImageIO service: `./imageio_run.sh`

## Syncing Code to KVM Hosts

The `sync.sh` script deploys the code to one or more KVM hosts via rsync over SSH:

```bash
# Sync to default hosts defined in sync.sh
./sync.sh

# Sync to specific hosts
./sync.sh 192.168.1.10 192.168.1.11
```

## Build and run

### Manual run

```bash
python -m app.main
```

### Using run.sh script

The project includes a `run.sh` script that runs the application as a background service with sudo privileges:

```bash
./run.sh
```

**Note**: The `run.sh` script assumes all required packages from `requirements.txt` are already installed. Make sure to install them before running the script:

```bash
pip install -r requirements.txt
./run.sh
```

## Stopping the application

To stop the running application, use the `stop.sh` script:

```bash
./stop.sh
```

This will find and terminate the running instance of the CloudStack oVirt-Compatible API Server.

## Docker Support

The application can be deployed using Docker. A Dockerfile is provided to build an image based on Ubuntu 24.04.

**Note**: The Docker image runs only the API server. The ImageIO service must be run separately on each KVM host.

### Building the Docker Image

To build the Docker image:

```bash
docker build -t cloudstack-ovirtapi .
```

### Running with Docker

To run the application with Docker, mounting a local config.ini file:

```bash
docker run -d -p 443:443 -v /path/to/local/config.ini:/app/config.ini --name cloudstack-ovirtapi cloudstack-ovirtapi
```

Alternatively, you can configure the application using environment variables:

```bash
docker run -d -p 443:443 \
  -e SERVER_HOST=0.0.0.0 \
  -e SERVER_PORT=443 \
  -e PUBLIC_IP= \
  -e SSL_CERT_FILE=./certs/server.crt \
  -e SSL_KEY_FILE=./certs/server.key \
  -e CLOUDSTACK_ENDPOINT=https://cloudstack.example.com/client/api \
  -e HMAC_SECRET=very-long-random-secret \
  -e LOG_LEVEL=INFO \
  -e LOG_FILE=./logs/app.log \
  --name cloudstack-ovirtapi cloudstack-ovirtapi
```

Or a simple example with just the CloudStack HTTP endpoint:

```bash
docker run -d -p 443:443 \
  -e CLOUDSTACK_ENDPOINT=http://cloudstack.example.com:8080/client/api \
  --name cloudstack-ovirtapi cloudstack-ovirtapi
```

The Docker image will update the config.ini file with the provided environment variables at startup.

## Basic Authentication

- GET request to retrieve a list of virtual machines:

```bash
curl -k -X GET -H "Authorization: Basic $(echo -n 'admin:password' | base64)" https://localhost:443/ovirt-engine/api/vms
```

- POST request to start a virtual machine:

```bash
curl -k -X POST -H "Authorization: Basic $(echo -n 'admin:password' | base64)" https://localhost:443/ovirt-engine/api/vms/fef1d5a5-1598-4710-a50c-a4dcc5b2051d/start
```

## OAuth Authentication

To authenticate using OAuth, you can follow these steps:

- Obtain an access token by making a POST request to the `/sso/oauth/token` endpoint with the appropriate grant type, username, and password.

For example:

```bash
curl -k -X POST "https://localhost:443/ovirt-engine/sso/oauth/token" -d "grant_type=password&username=admin&password=password"
```

The response will include an access token in the `access_token` field. For example:

```json
{
  "access_token": "ji2mBN46rlzdlzFwzNLtRc_V9OrMFXmcDpCKzWzxUFo",
  "token_type": "Bearer",
  "expires_in": 86400,
  "scope": "ovirt-engine-api"
}
```

- Use the obtained access token to authenticate subsequent requests by setting the Authorization header with the value `Bearer {access_token}`. For example:

```bash
curl -k -H "Authorization: Bearer ji2mBN46rlzdlzFwzNLtRc_V9OrMFXmcDpCKzWzxUFo" https://localhost:443/ovirt-engine/api/vms
```

Make sure to replace `localhost:443` with the appropriate host and port for your environment.

# Full list of APIs (In progress)

The oVirt REST API guide can be found at https://www.ovirt.org/documentation/doc-REST_API_Guide/

| API Endpoints | Method | Response & Possible Status Codes | Reference section in oVirt Guide |
|---------------|--------|--------------------------------|---------------------------------|
| **/services/pki-resource?resource=ca-certificate&format=X509-PEM-CA** | GET | Returns the CA certificate in PEM format. Codes: 200 OK, 400 Bad Request, 404 Not Found | 2.1. Obtaining the CA Certificate Method 2. Downloads the .crt file |
| **/sso/oauth/token** | POST | Returns an OAuth authorization token. Codes: 200 OK, 400 Bad Request, 401 Unauthorized | 3.1 OAuth Auth. Sends user name/pw Gets auth token back. **Note**: Authentication in the latest plugin follows best practices from the ovirt platform and uses PUT instead of GET. |
| **/api/vms** | GET | List of virtual machines (XML/JSON) Codes: 200 OK POST creates VM → 201 Created, 400 Bad Request, 409 Conflict | Dumps full list of VMs with parameters |
| /api/vms/{id}/backups | GET | List of backups for the VM. Codes: 200 OK. POST creates backup → 202 Accepted, 400 Bad Request, 409 Conflict | 282.2. get GET, 285.2. list GET |
| /api/vms/{id}/backups/{backupId} | GET | Backup details. Codes: 200 OK, 404 Not Found | 282.2. get GET, 285.2. list GET |
| /api/vms/{id}/backups/{backupId}/disks | GET | List of disks in the backup. Codes: 200 OK, 404 Not Found | 282.2. get GET, 285.2. list GET |
| /api/vms/{id}/backups/{backupId}/finalize | POST | Finalizes the backup. Codes: 200 OK, 202 Accepted, 400 Bad Request, 409 Conflict | 282.2. get GET, 285.1. add POST |
| **/api/vms/{id}/start** | POST | Starts the VM. Codes: 202 Accepted, 400 Bad Request, 409 Conflict | 279.19. start POST |
| **/api/vms/{id}/stop** | POST | Stops the VM. Codes: 202 Accepted, 400 Bad Request, 409 Conflict | 279.20. stop POST |
| **/api/vms/{id}/shutdown** | POST | Gracefully shuts down the VM. Codes: 202 Accepted, 400 Bad Request, 409 Conflict | 279.18. shutdown POST |
| /api/jobs/{id} | GET | Job status. Codes: 200 OK, 404 Not Found | 163.2. list GET |
| **/api/vms/{id}** | GET | VM details. Codes: 200 OK, 404 Not Found. PUT updates VM → 200 OK, 400 Bad Request. DELETE removes VM → 200 OK, 202 Accepted, 404 Not Found | 279.8.1. all_content 433. GuestOperating- System |
| /api/vms/{vmId}/diskattachments | GET | List of disks attached to the VM. Codes: 200 OK POST attaches disk → 201 Created, 400 Bad Request, 409 Conflict | 83.1. get GET |
| /api/vms/{vmId}/diskattachments/{diskId}?detach_only=true | DELETE | Detaches a disk from the VM. Codes: 200 OK, 202 Accepted, 404 Not Found | 83.2. remove DELETE |
| /api/vms/{vmId}/nics | GET | List of VM network interfaces. Codes: 200 OK. POST creates NIC → 201 Created, 400 Bad Request | 11 Following links |
| /api/vms/{vmId}/nics/{nicId} | GET | NIC details. Codes: 200 OK, 404 Not Found. PUT updates NIC → 200 OK, 400 Bad Request. DELETE removes NIC → 200 OK, 404 Not Found | 300.3. get GET |
| /api/vms/{vmId}/checkpoints | GET | List of checkpoints. Codes: 200 OK | 291.1. list GET |
| /api/vms/{vmId}/checkpoints/{checkpointId} | DELETE | Deletes a checkpoint. Codes: 200 OK, 404 Not Found | 291.1. list GET |
| /api/vms/{vmId}/snapshots | GET | List of snapshots. Codes: 200 OK. POST creates snapshot → 202 Accepted, 400 Bad Request | 578 Snapshot struct |
| /api/vms/{vmId}/snapshots/{snapshotId} | GET | Snapshot details. Codes: 200 OK, 404 Not Found | 578 Snapshot struct, 216.1 get GET |
| /api/vms/{vmId}/snapshots/{snapshotId}/restore | POST | Restores VM from snapshot. Codes: 202 Accepted, 400 Bad Request, 409 Conflict | 578 Snapshot struct |
| /api/vms/{vmId}/snapshots/{snapshotId}?async=false | DELETE | Deletes a snapshot. Codes: 200 OK, 202 Accepted, 404 Not Found | 216.2 remove DELETE |
| **/api/datacenters** | GET | List of data centers. Codes: 200 OK | 368.1. version |
| **/api/datacenters/{id}/networks** | GET | List of networks in a data center. Codes: 200 OK, 404 Not Found | 80.2. list GET |
| **/api/datacenters/{id}/storagedomains** | GET | List of storage domains in a data center. Codes: 200 OK, 404 Not Found | 56.3. get GET |
| **/api/networks** | GET | List of networks. Codes: 200 OK | 178.2. list GET |
| **/api/networks/{id}** | GET | Network details. Codes: 200 OK, 404 Not Found | 171.1. get GET |
| /api/vnicprofiles | GET | List of vNIC profiles. Codes: 200 OK | 314.2. list GET, 314. VnicProfiles |
| /api/vnicprofiles/{id} | GET | vNIC profile details. Codes: 200 OK, 404 Not Found | 314.2. list GET, 314. VnicProfiles |
| **/api/clusters** | GET | List of clusters. Codes: 200 OK | 351 Cluster struct, 64 Cluster, 74.2. list GET |
| /api/clusters/{id} | GET | Cluster details. Codes: 200 OK, 404 Not Found | 64.1. get GET |
| **/api** | GET | API root info (version, links). Codes: 200 OK | 14 Access API entry point, information about the environment and management engine id |
| /api/disks | Get | List of disks. Codes: 200 OK. POST creates disk → 201 Created, 400 Bad Request | 89.2. list GET |
| /api/disks/{id} | Get | Disk details. Codes: 200 OK, 404 Not Found. PUT updates disk → 200 OK, 400 Bad Request. DELETE removes disk → 200 OK, 404 Not Found | 82.4. get GET |
| /api/disks/{id}/copy | Post | Copies a disk. Codes: 202 Accepted, 400 Bad Request, 409 Conflict | 82.2. copy POST |
| /api/disks/{id}/reduce | Post | Reduces disk size. Codes: 202 Accepted, 400 Bad Request | 82.6. reduce POST |
| /api/tags | Get | List of tags. Codes: 200 OK | 254.2. list GET |
| /api/vms/{id}/tags | Post | Assigns a tag to VM. Codes: 201 Created, 400 Bad Request, 409 Conflict | 53.1. add POST |
| /api/imagetransfers | Get | List of image transfers. Codes: 200 OK. POST creates image transfer → 201 Created | 150.2. list GET |
| /api/imagetransfers/{id} | Get | Image transfer details. Codes: 200 OK, 404 Not Found | 150.2. list GET |
| /api/imagetransfers/{id}/finalize | Post | Finalizes image transfer. Codes: 200 OK, 409 Conflict | 150.2. list GET |
| /api/imagetransfers/{id}/cancel | Post | Cancels image transfer. Codes: 200 OK, 409 Conflict | 150.2. list GET |
| **/api/hosts** | Get | List of hosts. Codes: 200 OK | 18 List hosts |

## APIs Now Fully Implemented

The following APIs have been implemented in the CloudStack oVirtAPI server:

### Authentication & PKI APIs
- `POST /ovirt-engine/sso/oauth/token` - OAuth token generation
- `POST /ovirt-engine/sso/oauth/revoke` - Token revocation
- `GET /ovirt-engine/services/pki-resource` - CA certificate distribution
- `GET/POST /ovirt-engine/api/logout` - Session logout

### Infrastructure APIs
- `GET /api` - API root info (version, links)
- `HEAD /api` - API health check
- `GET /api/datacenters` - List of data centers
- `GET /api/datacenters/{id}/networks` - List of networks in a data center
- `GET /api/datacenters/{id}/storagedomains` - List of storage domains in a data center
- `GET /api/clusters` - List of clusters
- `GET /api/hosts` - List of hosts
- `GET /api/hosts/{id}` - Host details

### VM APIs
- `GET /api/vms` - List of virtual machines
- `GET /api/vms/{id}` - VM details
- `POST /api/vms/{id}/start` - Starts the VM
- `POST /api/vms/{id}/stop` - Stops the VM
- `POST /api/vms/{id}/shutdown` - Gracefully shuts down the VM

### Network APIs
- `GET /api/networks` - List of networks
- `GET /api/networks/{id}` - Network details
- `GET /api/vnicprofiles` - List of vNIC profiles
- `GET /api/vnicprofiles/{id}` - vNIC profile details

### Storage APIs
- `GET /api/storagedomains` - List of storage domains
- `GET /api/disks` - List of disks
- `GET /api/disks/{id}` - Disk details
- `PUT /api/disks/{id}` - Updates disk configuration
- `DELETE /api/disks/{id}` - Deletes a disk
- `POST /api/disks/{id}/copy` - Copies a disk
- `POST /api/disks/{id}/reduce` - Reduces disk size

### VM Disk Management APIs
- `GET /api/vms/{vmId}/diskattachments` - List of disks attached to the VM
- `POST /api/vms/{vmId}/diskattachments` - Attaches disk to VM
- `DELETE /api/vms/{vmId}/diskattachments/{diskId}?detach_only=true` - Detaches disk from VM

### VM Network Interface APIs
- `GET /api/vms/{vmId}/nics` - List of VM network interfaces
- `POST /api/vms/{vmId}/nics` - Creates NIC for VM
- `GET /api/vms/{vmId}/nics/{nicId}` - NIC details
- `PUT /api/vms/{vmId}/nics/{nicId}` - Updates NIC
- `DELETE /api/vms/{vmId}/nics/{nicId}` - Removes NIC

### VM Backup & Checkpoint APIs
- `POST /api/vms/{vmId}/backups` - Creates VM backup
- `GET /api/vms/{vmId}/backups/{backupId}` - Backup details
- `GET /api/vms/{vmId}/backups/{backupId}/disks` - List of disks in the backup
- `POST /api/vms/{vmId}/backups/{backupId}/finalize` - Finalizes the backup
- `GET /api/vms/{vmId}/checkpoints` - List of checkpoints
- `DELETE /api/vms/{vmId}/checkpoints/{checkpointId}` - Deletes a checkpoint

### VM Snapshot APIs
- `GET /api/vms/{vmId}/snapshots` - List of snapshots
- `POST /api/vms/{vmId}/snapshots` - Creates snapshot
- `GET /api/vms/{vmId}/snapshots/{snapshotId}` - Snapshot details
- `POST /api/vms/{vmId}/snapshots/{snapshotId}/restore` - Restores VM from snapshot
- `DELETE /api/vms/{vmId}/snapshots/{snapshotId}?async=false` - Deletes a snapshot

### Job Management APIs
- `GET /api/jobs/{id}` - Job status

### Tagging APIs
- `GET /api/tags` - List of tags
- `POST /api/vms/{id}/tags` - Assigns a tag to VM

### Image Transfer APIs
- `POST /api/imagetransfers` - Creates new image transfer for backup/restore
- `GET /api/imagetransfers/{id}` - Gets status of image transfer
- `POST /api/imagetransfers/{id}/finalize` - Finalizes image transfer
- `POST /api/imagetransfers/{id}/cancel` - Cancels image transfer

### Image & Extents APIs
- `GET /images/{image_id}` - Gets image information
- `GET /images/{image_id}/extents` - Gets image extents for incremental backup
