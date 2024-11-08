[comment]: # (./roles/libvirt/molecule-transformer/README.md, nsys-ai-claude-3.5)

# Molecule Transformer Role

This role transforms Molecule platform configurations into libvirt resources. It processes Molecule YAML definitions and generates standardized data structures for VMs, networks, and storage that can be consumed by other roles in the nsys.libvirt collection.

## Requirements

- Python >= 3.12
- Required packages for cloud-init support:
  - genisoimage
  - cloud-localds

## Role Variables

### Required Input Variables

- `yaml_content`: Molecule platform configuration (list)
- `project_name`: Unique identifier for the project (string)
- `project_base_dir`: Base directory for project resources (string)
- `state`: Desired state - 'present' or 'absent' (string)

### Output Variables

The role produces several standardized data structures:

#### DOMAIN_SPECS
List of VM specifications:
```yaml
- name: "instance-name"
  type: "vm"
  cpu: 1
  memory: 1024
  power: true
  cloud_init: true
```

#### NETWORKS
List of network configurations:
```yaml
- name: "project-network-name"
  forwarding: "nat|routed"  # optional
  cidr: "192.168.1.0/24"    # optional
  dhcp:                     # optional
    start: "192.168.1.10"
    end: "192.168.1.50"
```

#### DISKS
List of storage volumes:
```yaml
- name: "project-disk-name"
  format: "qcow2|raw"
  capacity: 10              # in GB, optional
  path: "/path/to/file"     # optional
```

#### Reference Lists

- `INTERFACE_REFERENCE`: Maps network interfaces to domains
```yaml
- reference: "project-network-name"
  ip: "192.168.1.10/24"    # optional
  target: "domain-name"
```

- `DISK_REFERENCE`: Maps storage volumes to domains
```yaml
- reference: "project-volume-name"
  target_domain: "domain-name"
```

#### Storage Pool Information
- `POOL_NAME`: Name of the libvirt storage pool (string)
- `POOL_DIR`: Directory path for the storage pool (string)

## Example Molecule Configuration

```yaml
platforms:
  - name: test-instance
    type: vm
    power_on: true
    cloud_init: true
    cpu: 1
    memory: 1024
    interfaces:
      - network: default
      - network: custom-net
        ip: 192.168.18.22/24
    disks:
      - name: system
        capacity: 15
      - name: install-iso
        path: "~/Downloads/debian-12.7.0-amd64-netinst.iso"

  - name: custom-net
    type: network
    forwarding: nat
    cidr: 192.168.18.0/24

  - name: storage-vol
    type: disk
    capacity: 8
    format: qcow2
```

## Notes

- Network and disk names must be unique within their type
- The default libvirt network can be referenced using `network: default`
- All resources are prefixed with the project name
- Boot order for disks can be specified using `boot_order` parameter
- Cloud-init configuration requires additional packages

## Dependencies

This role is part of the nsys.libvirt collection. All paths are relative to the collection root directory.
