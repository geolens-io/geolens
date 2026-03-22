# AWS Security Group Configuration for GeoLens

This document specifies the minimum security group rules required for a GeoLens EC2 instance launched from the AWS Marketplace AMI.

## Minimum Required Inbound Rules

| Port | Protocol | Source | Purpose | Required |
|------|----------|--------|---------|----------|
| 80 | TCP | 0.0.0.0/0, ::/0 | HTTP access to GeoLens web interface | Yes |
| 443 | TCP | 0.0.0.0/0, ::/0 | HTTPS (when ALB/ACM termination is configured) | Recommended |
| 22 | TCP | Your IP/32 | SSH administration | Yes (restrict to operator IP) |

**Important:** Port 22 should always be restricted to the operator's IP address. Never open SSH to 0.0.0.0/0.

## Outbound Rules

All outbound traffic should be allowed (this is the AWS default). Outbound access is required for:

- **Docker image pulls** from GitHub Container Registry (ghcr.io) during first boot
- **OS package updates** via apt repositories
- **IMDS access** to the instance metadata service at 169.254.169.254

## HTTPS Configuration

The GeoLens AMI serves HTTP on port 80 via the frontend container. For HTTPS, use the AWS Application Load Balancer (ALB) with AWS Certificate Manager (ACM) pattern:

1. **Create an ACM certificate** for your domain in the same region as your EC2 instance
2. **Create an Application Load Balancer** with an HTTPS listener (port 443) using the ACM certificate
3. **Create a target group** pointing to the EC2 instance on port 80 (HTTP)
4. **Configure the ALB HTTPS listener** to forward traffic to the target group
5. **Update security groups:**
   - **Instance security group:** Allow port 80 inbound from the ALB security group only (remove 0.0.0.0/0 on port 80)
   - **ALB security group:** Allow port 443 inbound from 0.0.0.0/0, ::/0

This approach keeps TLS termination at the ALB layer, with unencrypted traffic only between the ALB and the instance within the VPC.

## AWS Marketplace Scanning Note

During the AWS Marketplace automated vetting process, the AMI must be accessible via SSH from internal AWS subnets `10.0.0.0/16` and `10.2.0.0/16`. This is handled automatically by AWS during the scanning process. Operators do **not** need to add these CIDR ranges to their security groups.

## Example AWS CLI Commands

Create a security group and add the minimum required inbound rules:

```bash
# Create the security group
SG_ID=$(aws ec2 create-security-group \
  --group-name geolens-sg \
  --description "Security group for GeoLens AMI" \
  --vpc-id vpc-xxxxxxxxx \
  --query 'GroupId' --output text)

# Allow HTTP from anywhere
aws ec2 authorize-security-group-ingress \
  --group-id "$SG_ID" \
  --protocol tcp --port 80 \
  --cidr 0.0.0.0/0

# Allow HTTPS from anywhere (for ALB or future direct HTTPS)
aws ec2 authorize-security-group-ingress \
  --group-id "$SG_ID" \
  --protocol tcp --port 443 \
  --cidr 0.0.0.0/0

# Allow SSH from your IP only (replace with your actual IP)
aws ec2 authorize-security-group-ingress \
  --group-id "$SG_ID" \
  --protocol tcp --port 22 \
  --cidr YOUR_IP/32

echo "Security group created: $SG_ID"
```

Replace `vpc-xxxxxxxxx` with your VPC ID and `YOUR_IP/32` with your actual public IP address (e.g., `203.0.113.50/32`).
