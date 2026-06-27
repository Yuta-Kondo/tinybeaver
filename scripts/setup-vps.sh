#!/bin/bash
# Run once on a fresh Hetzner Ubuntu 24.04 VPS
# Usage: ssh root@<VPS_IP> 'bash -s' < scripts/setup-vps.sh
set -e

echo "==> Installing Docker..."
apt-get update -qq
apt-get install -y --no-install-recommends ca-certificates curl gnupg

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
| tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update -qq
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

systemctl enable docker
systemctl start docker

echo "==> Hardening SSH (key-only, no password)..."
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl reload sshd

echo "==> Enabling automatic security updates..."
apt-get install -y unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Creating app directory..."
mkdir -p /app/memory /app/data
chmod 700 /app

echo "==> Done. VPS is ready."
