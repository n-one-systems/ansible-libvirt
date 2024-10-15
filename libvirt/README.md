# nsys.libvirt

An Ansible collection for managing libvirt resources. This collection provides modules to interact with libvirt, allowing you to manage various aspects of your virtualization environment.

## Installation

You can install this collection via ansible-galaxy:

```bash
ansible-galaxy collection install https://github.com/n-one-systems/ansible-libvirt.git
```

## Requirements

- Python >= 3.11
- libvirt-python
- Ansible Core >= 2.12.0

Ensure that you have libvirt and its Python bindings installed on your system. You can usually install these with your system's package manager.

For example, on Ubuntu/Debian:

```bash
sudo apt-get install libvirt-dev python3-libvirt
```

On RHEL/CentOS:

```bash
sudo dnf install libvirt-devel python3-libvirt
```

## Modules

### libvirt_volume

This module allows you to create, delete, resize, and import libvirt storage volumes.

#### Parameters

- `name` (required): Name of the storage volume.
- `pool` (required): Name of the storage pool.
- `capacity`: Size of the storage volume (e.g., '10G', '1024M').
- `allocation`: Initial allocation size of the storage volume (e.g., '1G', '512M').
- `format`: Format of the storage volume. Choices: raw, qcow2, vmdk. Default: raw.
- `state`: State of the storage volume. Choices: present, absent, resize. Default: present.
- `uri`: libvirt connection URI. Default: 'qemu:///system'.
- `import_image`: Path to an existing image to import.
- `import_format`: Format of the image being imported. Choices: raw, qcow2, vmdk.

#### Example Usage

```yaml
- name: Create a storage volume
  nsys.libvirt.libvirt_volume:
    name: my_volume
    pool: default
    capacity: 5G
    format: qcow2
    state: present

- name: Resize a storage volume
  nsys.libvirt.libvirt_volume:
    name: my_volume
    pool: default
    capacity: 10G
    state: resize

- name: Delete a storage volume
  nsys.libvirt.libvirt_volume:
    name: my_volume
    pool: default
    state: absent

- name: Import an existing qcow2 image
  nsys.libvirt.libvirt_volume:
    name: imported_volume
    pool: default
    import_image: /path/to/existing/image.qcow2
    import_format: qcow2
    state: present
```

## Planned Functionality

We are continuously working to expand the capabilities of this collection. Here are some modules and features we're planning to add in future releases:

- **libvirt_pool**: Manage libvirt storage pools.
- **libvirt_network**: Create and manage libvirt networks.
- **libvirt_domain**: Manage libvirt domains (virtual machines).

Stay tuned for updates, and feel free to suggest new features or improvements!

## Contributing

Contributions to this collection are welcome! Please refer to our [Contribution Guidelines](CONTRIBUTING.md) for more information on how to get started.

## Testing

To run the tests for this collection, you'll need to have Ansible installed. Then, you can use the following command:

```bash
ansible-test sanity --docker default -v
```

This will run the sanity tests in a Docker container, ensuring a consistent environment.

## Issues

If you encounter any problems or have feature requests, please create an issue on our [GitHub issue tracker](https://github.com/n-one-systems/ansible-libvirt/issues).

## License

This collection is licensed under the GNU General Public License v3.0 (GPLv3). See the [LICENSE](LICENSE) file for details.

## Author

This collection is maintained by N-One Systems. For more information, visit our [GitHub repository](https://github.com/n-one-systems/ansible-libvirt).

## Support

For professional support, please open an issue on our [GitHub issue tracker](https://github.com/n-one-systems/ansible-libvirt/issues).
