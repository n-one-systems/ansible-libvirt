# Ansible Collection - nsys.libvirt

This collection provides roles and modules for managing libvirt resources:

## Roles

- network: Manage libvirt networks
- storage_disk: Manage storage pools and volumes
- vm: Manage virtual machines

## Installation

```bash
ansible-galaxy collection install nsys.libvirt
```

## Usage

```yaml
- hosts: localhost
  roles:
    - role: nsys.libvirt.network
      vars:
        libvirt_network:
          name: "my_network"
          # ... network settings

    - role: nsys.libvirt.storage_disk
      vars:
        libvirt_storage:
          name: "my_pool"
          # ... storage settings

    - role: nsys.libvirt.vm
      vars:
        libvirt_vm:
          name: "my_vm"
          # ... VM settings
```

For detailed documentation, please refer to the docs directory.
