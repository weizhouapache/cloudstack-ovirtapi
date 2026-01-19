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

# Configuration Example

Example **config.ini**

```
[server]
host = 0.0.0.0
port = 443
path = /ovirt-engine
public_ip =

[ssl]
cert_file = ./certs/server.crt
key_file  = ./certs/server.key

[cloudstack]
endpoint = https://cloudstack.mgmt.server/client/api

[security]
hmac_secret = very-long-random-secret

[logging]
level = DEBUG
file = ./logs/app.log
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

## Prerequisites

Before running the application, ensure all required packages from `requirements.txt` are installed:

```
pip install -r requirements.txt
```

## Build and run

### Manual run
```
python -m app.main
```

### Using run.sh script

The project includes a `run.sh` script that runs the application as a background service with sudo privileges:

```
./run.sh
```

**Note**: The `run.sh` script assumes all required packages from `requirements.txt` are already installed. Make sure to install them before running the script:

```
pip install -r requirements.txt
./run.sh
```

## Stopping the application

To stop the running application, use the `stop.sh` script:

```
./stop.sh
```

This will find and terminate the running instance of the CloudStack oVirt-Compatible API Server.

## Basic Authentication

- GET request to retrieve a list of virtual machines:

```
curl -k -X GET -H "Authorization: Basic $(echo -n 'admin:password' | base64)" https://localhost:443/ovirt-engine/api/vms
```

- POST request to start a virtual machine:

```
curl -k -X POST -H "Authorization: Basic $(echo -n 'admin:password' | base64)" https://localhost:443/ovirt-engine/api/vms/fef1d5a5-1598-4710-a50c-a4dcc5b2051d/start
```

## OAuth Authentication


To authenticate using OAuth, you can follow these steps:

- Obtain an access token by making a POST request to the `/sso/oauth/token` endpoint with the appropriate grant type, username, and password.

For example:

```
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

- Use the obtained access token to authenticate subsequent requests by setting the Authorization header with the value Bearer {access_token}. For example:

```
curl -k -H "Authorization: Bearer ji2mBN46rlzdlzFwzNLtRc_V9OrMFXmcDpCKzWzxUFo" https://localhost:443/ovirt-engine/api/vms
```

Make sure to replace localhost:443 with the appropriate host and port for your environment.

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

### VM Backup & Snapshot APIs
- `POST /api/vms/{vmId}/backups` - Creates VM backup
- `GET /api/vms/{vmId}/backups/{backupId}` - Backup details
- `GET /api/vms/{vmId}/backups/{backupId}/disks` - List of disks in the backup
- `POST /api/vms/{vmId}/backups/{backupId}/finalize` - Finalizes the backup
- `GET /api/vms/{vmId}/checkpoints` - List of checkpoints
- `DELETE /api/vms/{vmId}/checkpoints/{checkpointId}` - Deletes a checkpoint
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
- `POST /api/imagetransfers` - Creates new image transfers for backup/restore operations
- `GET /api/imagetransfers/{id}` - Gets status of image transfers
- `POST /api/imagetransfers/{id}/finalize` - Finalizes image transfers
- `POST /api/imagetransfers/{id}/cancel` - Cancels image transfers

### Images APIs
- `GET /images/{image_id}/extents` - Gets image extents for incremental backup
- `GET /images/{image_id}` - Gets image information

### Authentication & PKI APIs
- `POST /sso/oauth/token` - OAuth token endpoint
- `GET /services/pki-resource?resource=ca-certificate&format=X509-PEM-CA` - Gets CA certificate
- `POST /api/logout` - Logout endpoint

