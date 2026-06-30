---
name: app-server-infrastructure
description: Real network architecture of Phase 2 — app server SSH access to both headnodes
metadata:
  type: user
---
App server (10.20.11.226) has direct SSH access to BOTH headnodes:
- Linux headnode (server1): 192.168.201.1 — ubuntu user, SSH key /home/ubuntu/.ssh/id_rsa
- OpenStack headnode (controller): 192.168.202.1 — ubuntu user, same SSH key

However, app server CANNOT reach OpenStack API ports (5000 Keystone, 9292 Glance, 8774 Nova) directly via HTTP — connection times out.

**Solution for Glance uploads**: SCP file to 192.168.202.1, then run `openstack image create` via SSH on that host (where the openstack CLI and local Keystone access work fine). openstack CLI version 5.2.0 is installed on 192.168.202.1.

OpenStack credentials (from ~/env-scripts/cloud-admin-openrc on headnode):
- OS_AUTH_URL=http://controller:5000/v3  (controller resolves locally on 192.168.202.1)
- OS_USERNAME=cloud_admin
- OS_PROJECT_NAME=cloud_admin
- OS_USER_DOMAIN_NAME=Cloud
- OS_PROJECT_DOMAIN_NAME=Cloud
