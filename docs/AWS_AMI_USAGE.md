# GeoLens AWS AMI Usage Guide

## Instance Requirements

| Requirement | Minimum | Recommended | Notes |
|---|---|---|---|
| Instance type | t3.medium (4GB RAM) | t3.large (8GB RAM) | PostGIS + 7 Docker containers |
| Root volume | 40 GB (default) | 100 GB+ for raster data | gp3 EBS volume |
| Architecture | x86_64 (amd64) | -- | ARM/Graviton not yet supported |

## Required Security Group Rules

| Port | Protocol | Source | Purpose |
|---|---|---|---|
| 22 | TCP | Your IP | SSH administration |
| 80 | TCP | 0.0.0.0/0 | HTTP (application) |
| 443 | TCP | 0.0.0.0/0 | HTTPS (if TLS configured) |

No other inbound ports are required. All inter-service communication is Docker-internal.

## First-Boot Process

1. Launch the AMI via the AWS Console, CLI, or the provided CloudFormation template.
2. Cloud-init runs automatically on first boot (2-5 minutes):
   - Generates random PostgreSQL, JWT, and admin passwords
   - Detects the instance public IP via IMDSv2
   - Writes `/opt/geolens/.env` with all configuration
   - Configures 2GB swap space
   - Starts all Docker Compose services
   - Writes credentials to `/var/log/geolens-init.log`
3. The application is ready when cloud-init completes.

## Accessing the Application

### Web Interface

Open `http://<PUBLIC_IP>` in your browser.

### Admin Credentials

SSH into the instance and run:

```bash
sudo cat /var/log/geolens-init.log
```

This displays the auto-generated admin username and password.

### SSH Access

```bash
ssh -i ~/.ssh/your-key.pem ubuntu@<PUBLIC_IP>
```

The login banner (MOTD) displays common management commands.

## Common Operations

### Service Management

```bash
# View all service status
cd /opt/geolens && docker compose ps

# Restart all services
sudo systemctl restart geolens

# View logs (follow mode)
cd /opt/geolens && docker compose logs -f

# View logs for a specific service
cd /opt/geolens && docker compose logs -f api
```

### Changing the Admin Password

1. Log in to the web interface with the initial credentials.
2. Navigate to Settings > Users.
3. Update the admin password.
4. Optionally, create additional user accounts and disable the default `admin` account.

### Updating the Application URL

If you assign a domain name or Elastic IP:

```bash
sudo nano /opt/geolens/.env
# Update PUBLIC_APP_URL and PUBLIC_API_URL
# Example:
#   PUBLIC_APP_URL=https://geolens.example.com
#   PUBLIC_API_URL=https://geolens.example.com/api

sudo systemctl restart geolens
```

## Enabling HTTPS/TLS

### Option A: AWS Application Load Balancer (recommended)

1. Create an ALB in the same VPC.
2. Request an ACM certificate for your domain.
3. Create a target group pointing to the EC2 instance on port 80.
4. Create an HTTPS listener (443) with the ACM certificate.
5. Create an HTTP listener (80) that redirects to HTTPS.
6. Update `PUBLIC_APP_URL` and `PUBLIC_API_URL` in `/opt/geolens/.env` to use `https://`.

### Option B: Let's Encrypt (certbot)

```bash
# Install certbot
sudo apt-get update && sudo apt-get install -y certbot

# Temporarily stop GeoLens to free port 80
sudo systemctl stop geolens

# Obtain certificate
sudo certbot certonly --standalone -d your-domain.com

# Restart GeoLens
sudo systemctl start geolens
```

A TLS nginx configuration template is available at `/opt/geolens/nginx/tls.conf.template`.

## Backup Configuration

Automated backups run daily at 02:00 UTC by default.

### Local Backups

Backups are stored in the `backup_data` Docker volume. To change the schedule:

```bash
sudo nano /opt/geolens/.env
# Add or modify:
#   BACKUP_SCHEDULE=0 3 * * *      (3 AM UTC)
#   BACKUP_RETENTION_DAILY=14      (keep 14 daily backups)
#   BACKUP_RETENTION_WEEKLY=8      (keep 8 weekly backups)

sudo systemctl restart geolens
```

### S3 Backups

To enable S3 backup uploads:

```bash
sudo nano /opt/geolens/.env
# Add:
#   BACKUP_S3_ENABLED=true
#   S3_BUCKET=your-backup-bucket
#   S3_ACCESS_KEY_ID=AKIA...
#   S3_SECRET_ACCESS_KEY=...
#   S3_REGION=us-east-1

sudo systemctl restart geolens
```

## AI Features (Optional)

GeoLens supports AI-powered features (natural language search, metadata generation) via LLM APIs. To enable:

```bash
sudo nano /opt/geolens/.env
# Add one of:
#   ANTHROPIC_API_KEY=sk-ant-...
#   OPENAI_API_KEY=sk-...

sudo systemctl restart geolens
```

## Troubleshooting

### Application Not Accessible After Launch

1. Verify cloud-init completed: `cloud-init status`
2. Check service health: `cd /opt/geolens && docker compose ps`
3. Check cloud-init logs: `sudo cat /var/log/cloud-init-output.log`
4. Check application logs: `cd /opt/geolens && docker compose logs`

### Services Unhealthy

```bash
# Check which services are unhealthy
cd /opt/geolens && docker compose ps

# View logs for the unhealthy service
docker compose logs <service-name>

# Restart a single service
docker compose restart <service-name>
```

### Disk Space Issues

```bash
# Check disk usage
df -h /

# Check Docker disk usage
docker system df

# Prune unused Docker resources
docker system prune -f
```

### Memory Issues

```bash
# Check memory and swap usage
free -h

# Check per-container memory
docker stats --no-stream
```

## Instance Sizing Guide

| Workload | Instance Type | RAM | Notes |
|---|---|---|---|
| Evaluation / small team | t3.medium | 4 GB | Up to ~50 datasets |
| Production / medium team | t3.large | 8 GB | Up to ~500 datasets |
| Heavy raster workloads | t3.xlarge | 16 GB | Large COG/VRT files |
| Large organizations | m6i.xlarge | 16 GB | Consistent compute performance |
