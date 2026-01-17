import os
import socket
import subprocess
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from datetime import datetime, timedelta
from ipaddress import ip_address

from app.config import SSL, SERVER

def get_default_ip():
    """
    Get the default IP address of the current server.
    For Linux servers, uses 'ip route' command (most reliable).
    Falls back to socket method for other systems.
    """
    # Try Linux 'ip route' method first
    ip = _get_ip_from_ip_route()
    if ip:
        return ip

    # Fallback to socket method
    return _get_ip_from_socket()

def _get_ip_from_ip_route():
    """
    Get IP using 'ip route' command (Linux only).
    Finds default gateway interface and gets its IP.
    """
    try:
        # Get default route: "default via 192.168.1.1 dev eth0"
        output = subprocess.check_output(
            ["ip", "route", "show"],
            universal_newlines=True,
            stderr=subprocess.DEVNULL,
            timeout=5
        )

        for line in output.split('\n'):
            if line.startswith('default'):
                parts = line.split()
                # Extract interface from "dev eth0"
                if 'dev' in parts:
                    dev_idx = parts.index('dev')
                    iface = parts[dev_idx + 1]

                    # Get IP address of the interface
                    addr_output = subprocess.check_output(
                        ["ip", "addr", "show", iface],
                        universal_newlines=True,
                        stderr=subprocess.DEVNULL,
                        timeout=5
                    )

                    for addr_line in addr_output.split('\n'):
                        if 'inet ' in addr_line and '127.' not in addr_line:
                            ip = addr_line.strip().split()[1].split('/')[0]
                            return ip if ip != "0.0.0.0" else None

    except (subprocess.CalledProcessError, FileNotFoundError, IndexError, subprocess.TimeoutExpired):
        pass

    return None

def _get_ip_from_socket():
    """
    Get IP by connecting to a public DNS server (socket method).
    Works on all platforms but requires internet access.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip if ip != "0.0.0.0" else None
    except Exception:
        return None

def create_self_signed_cert(cert_file, key_file, host_ip, public_ip=None):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with open(key_file, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "CA"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CloudStack oVirtAPI"),
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])

    # Build Subject Alternative Names
    san_list = [x509.DNSName("localhost")]

    # Add public IP if provided
    if public_ip and public_ip.strip():
        san_list.append(x509.IPAddress(ip_address(public_ip)))
    
    # Add host IP if provided
    if host_ip and host_ip.strip():
        try:
            # Try to add as IP address
            san_list.append(x509.IPAddress(ip_address(host_ip)))
        except ValueError:
            # If not valid IP, add as DNS name
            san_list.append(x509.DNSName(host_ip))

    cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)\
        .public_key(key.public_key()).serial_number(x509.random_serial_number())\
        .not_valid_before(datetime.utcnow())\
        .not_valid_after(datetime.utcnow() + timedelta(days=365))\
        .add_extension(x509.SubjectAlternativeName(san_list), critical=False)\
        .sign(key, hashes.SHA256())

    with open(cert_file, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    san_names = ", ".join([str(name) for name in san_list])
    print(f"[INFO] Self-signed certificate created: {cert_file}, {key_file}")
    print(f"[INFO] Certificate SANs: {san_names}")


def ensure_certificates():
    cert_file = SSL.get("cert_file", "./certs/server.crt")
    key_file = SSL.get("key_file", "./certs/server.key")
    host = SERVER.get("host", "0.0.0.0")
    public_ip = SERVER.get("public_ip", "").strip()

    os.makedirs(os.path.dirname(cert_file), exist_ok=True)
    os.makedirs(os.path.dirname(key_file), exist_ok=True)

    # If host is 0.0.0.0 and no public_ip set, auto-detect server IP
    if host == "0.0.0.0":
        host_ip = get_default_ip()
        if host_ip:
            print(f"[INFO] Auto-detected server IP: {host_ip}")
    elif host != "localhost":
        host_ip = host

    if not os.path.exists(cert_file) or not os.path.exists(key_file):
        create_self_signed_cert(cert_file, key_file, host_ip, public_ip)

    return cert_file, key_file
