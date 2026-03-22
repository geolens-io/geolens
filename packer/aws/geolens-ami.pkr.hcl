# Build: packer build -var 'aws_profile=your-profile' packer/aws/geolens-ami.pkr.hcl
# Validate: packer validate packer/aws/geolens-ami.pkr.hcl

packer {
  required_plugins {
    amazon = {
      source  = "github.com/hashicorp/amazon"
      version = "~> 1"
    }
  }
}

variable "aws_profile" {
  type    = string
  default = "carto-concepts"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "instance_type" {
  type    = string
  default = "t3.medium"
}

variable "ami_name_prefix" {
  type    = string
  default = "geolens"
}

variable "app_version" {
  type        = string
  default     = "12.3"
  description = "Application version for AMI tags and VERSION file"
}

variable "geolens_version" {
  type        = string
  default     = "v12.3"
  description = "Docker image tag for geolens-api and geolens-frontend"
}

variable "titiler_version" {
  type        = string
  default     = "2.0.0"
  description = "Docker image tag for titiler"
}

variable "product_code" {
  type        = string
  default     = ""
  description = "AWS Marketplace product code (assigned after initial listing)"
}

source "amazon-ebs" "geolens" {
  profile       = var.aws_profile
  region        = var.aws_region
  instance_type = var.instance_type

  source_ami_filter {
    filters = {
      name                = "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
      architecture        = "x86_64"
    }
    owners      = ["099720109477"] # Canonical
    most_recent = true
  }

  ami_name        = "${var.ami_name_prefix}-{{timestamp}}"
  ami_description = "GeoLens v${var.app_version} - PostGIS-native GIS data catalog"

  # Copy AMI to additional regions for Marketplace distribution
  ami_regions = [
    "us-east-2",
    "us-west-1",
    "us-west-2",
    "eu-west-1",
    "eu-west-2",
    "eu-central-1",
    "ap-southeast-1",
    "ap-southeast-2",
    "ap-northeast-1",
  ]

  # AWS Marketplace: unencrypted EBS required
  encrypt_boot = false

  # IMDSv2 enforced on resulting AMI
  imds_support = "v2.0"

  # IMDSv2 enforced on build instance; hop limit 2 for Docker
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  # EBS volume config
  launch_block_device_mappings {
    device_name           = "/dev/sda1"
    volume_size           = 40
    volume_type           = "gp3"
    delete_on_termination = true
  }

  ssh_username              = "ubuntu"
  ssh_clear_authorized_keys = true

  tags = {
    Name           = "GeoLens AMI"
    Application    = "GeoLens"
    Vendor         = "GeoLens"
    Version        = var.app_version
    GeoLensVersion = var.geolens_version
    TitilerVersion = var.titiler_version
    BuildDate      = "{{timestamp}}"
    ProductCode    = var.product_code
  }
}

build {
  sources = ["source.amazon-ebs.geolens"]

  # Wait for cloud-init to complete on the build instance
  provisioner "shell" {
    inline = ["cloud-init status --wait"]
  }

  # Install Docker Engine
  provisioner "shell" {
    script = "../common/scripts/setup-docker.sh"
  }

  # Upload application files to /tmp
  provisioner "file" {
    source      = "../../docker-compose.prod.yml"
    destination = "/tmp/docker-compose.prod.yml"
  }

  provisioner "file" {
    source      = "../../scripts/init-db.sh"
    destination = "/tmp/init-db.sh"
  }

  provisioner "file" {
    source      = "../../scripts/backup-entrypoint.sh"
    destination = "/tmp/backup-entrypoint.sh"
  }

  provisioner "file" {
    source      = "../../scripts/backup.sh"
    destination = "/tmp/backup.sh"
  }

  provisioner "file" {
    source      = "../../scripts/backup-s3-upload.py"
    destination = "/tmp/backup-s3-upload.py"
  }

  provisioner "file" {
    source      = "../../scripts/backup-s3-retention.py"
    destination = "/tmp/backup-s3-retention.py"
  }

  provisioner "file" {
    source      = "../../deploy/cloud-init/01-geolens-init.sh"
    destination = "/tmp/01-geolens-init.sh"
  }

  provisioner "file" {
    source      = "../../deploy/systemd/geolens.service"
    destination = "/tmp/geolens.service"
  }

  provisioner "file" {
    source      = "../../deploy/validate-firstrun.sh"
    destination = "/tmp/validate-firstrun.sh"
  }

  provisioner "file" {
    source      = "../../deploy/nginx/tls.conf.template"
    destination = "/tmp/tls.conf.template"
  }

  provisioner "file" {
    source      = "../../docs/AWS_AMI_USAGE.md"
    destination = "/tmp/USAGE.md"
  }

  # Upload MOTD banner
  provisioner "file" {
    source      = "../common/motd/99-geolens"
    destination = "/tmp/99-geolens"
  }

  # Install application files and enable services
  provisioner "shell" {
    script = "../common/scripts/setup-geolens.sh"
    environment_vars = [
      "GEOLENS_VERSION=${var.geolens_version}",
      "TITILER_VERSION=${var.titiler_version}",
      "APP_VERSION=${var.app_version}",
    ]
  }

  # SSH hardening
  provisioner "shell" {
    script = "../common/scripts/harden-ssh.sh"
  }

  # Final cleanup -- MUST be last
  provisioner "shell" {
    script = "../common/scripts/cleanup.sh"
  }
}
