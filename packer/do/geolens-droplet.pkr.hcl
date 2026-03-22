# Build: packer build packer/do/geolens-droplet.pkr.hcl
# Validate: packer validate packer/do/geolens-droplet.pkr.hcl

packer {
  required_plugins {
    digitalocean = {
      version = ">= 1.0.4"
      source  = "github.com/digitalocean/digitalocean"
    }
  }
}

variable "do_api_token" {
  type      = string
  default   = env("DIGITALOCEAN_API_TOKEN")
  sensitive = true
}

variable "region" {
  type    = string
  default = "nyc3"
}

variable "size" {
  type    = string
  default = "s-1vcpu-2gb"
}

variable "image_name" {
  type    = string
  default = "geolens"
}

variable "app_version" {
  type    = string
  default = "9.0.0"
}

source "digitalocean" "geolens" {
  api_token     = var.do_api_token
  image         = "ubuntu-24-04-x64"
  region        = var.region
  size          = var.size
  ssh_username  = "root"
  snapshot_name = "${var.image_name}-{{timestamp}}"
  snapshot_tags = ["geolens", "marketplace"]
}

build {
  sources = ["source.digitalocean.geolens"]

  # Wait for cloud-init to complete on the build droplet
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

  # Upload MOTD banner
  provisioner "file" {
    source      = "../common/motd/99-geolens"
    destination = "/tmp/99-geolens"
  }

  # Install application files and enable services
  provisioner "shell" {
    script = "../common/scripts/setup-geolens.sh"
  }

  # SSH hardening
  provisioner "shell" {
    script = "../common/scripts/harden-ssh.sh"
  }

  # DO-specific: ufw firewall
  provisioner "shell" {
    script = "scripts/setup-ufw.sh"
  }

  # Shared cleanup
  provisioner "shell" {
    script = "../common/scripts/cleanup.sh"
  }

  # DO vendor cleanup + validation -- MUST be last
  provisioner "shell" {
    script = "scripts/do-cleanup.sh"
  }
}
