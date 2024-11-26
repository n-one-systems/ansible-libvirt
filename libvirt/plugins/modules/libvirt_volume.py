# ./plugins/modules/libvirt_volume.py
# nsys-ai-claude-3.5

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r'''
---
module: libvirt_volume
short_description: Manage libvirt storage volumes
description:
  - Create, delete, resize, or import libvirt storage volumes.
options:
  name:
    description:
      - Name of the storage volume.
    required: true
    type: str
  pool:
    description:
      - Name of the storage pool.
    required: true
    type: str
  capacity:
    description:
      - Size of the storage volume (e.g., '10G', '1024M').
      - Required when creating a volume, resizing an existing one, or importing an image.
    type: str
  allocation:
    description:
      - Initial allocation size of the storage volume (e.g., '1G', '512M').
    type: str
  format:
    description:
      - Format of the storage volume.
    type: str
    choices: [ 'raw', 'qcow2', 'vmdk' ]
    default: 'raw'
  state:
    description:
      - State of the storage volume.
    type: str
    choices: [ 'present', 'absent', 'resize', 'import' ]
    default: 'present'
  uri:
    description:
      - libvirt connection uri.
    type: str
    default: 'qemu:///system'
  remote_host:
    description:
      - Remote host to connect to
    type: str
    required: false
  auth_user:
    description:
      - Username for authentication if required
    type: str
    required: false
  auth_password:
    description:
      - Password for authentication if required
    type: str
    required: false
    no_log: true
  import_image:
    description:
      - Path to an existing image to import.
    type: str
  import_format:
    description:
      - Format of the image being imported.
    type: str
    choices: [ 'raw', 'qcow2', 'vmdk' ]
    default: 'qcow2'
requirements:
  - "python >= 3.12"
  - "libvirt-python >= 5.6.0"
author:
  - "N-One Systems an AI (@n-one-systems)"
'''

EXAMPLES = r'''
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
    state: import
'''

RETURN = r'''
changed:
    description: Whether any changes were made
    type: bool
    returned: always
volume_info:
    description: Information about the volume after operation
    type: dict
    returned: when state is present, resize, or import
    contains:
        name:
            description: Volume name
            type: str
        path:
            description: Volume path
            type: str
        capacity:
            description: Volume capacity in bytes
            type: int
        allocation:
            description: Current allocation in bytes
            type: int
        format:
            description: Volume format (raw, qcow2, etc)
            type: str
        pool:
            description: Storage pool name
            type: str
msg:
    description: Status message
    type: str
    returned: always
'''

import os
import traceback

try:
    import libvirt

    HAS_LIBVIRT = True
except ImportError:
    HAS_LIBVIRT = False

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.nsys.libvirt.plugins.module_utils.libvirt_connection import LibvirtConnection
from ansible_collections.nsys.libvirt.plugins.module_utils.volume_utils import VolumeUtils


def parse_size(size_str):
    """Convert size string (like '5G', '1024M') to bytes"""
    units = {'B': 1, 'K': 1024, 'M': 1024 ** 2, 'G': 1024 ** 3, 'T': 1024 ** 4}
    size = size_str.strip()
    unit = size[-1].upper()
    if unit in units:
        return int(float(size[:-1]) * units[unit])
    else:
        return int(size)


def get_volume_xml(name, capacity, allocation, format):
    """Generate XML for volume creation"""
    capacity_bytes = parse_size(capacity)
    allocation_bytes = parse_size(allocation) if allocation else 0
    volume_xml = f"""
    <volume>
      <name>{name}</name>
      <allocation>{allocation_bytes}</allocation>
      <capacity>{capacity_bytes}</capacity>
      <target>
        <format type='{format}'/>
      </target>
    </volume>
    """
    return volume_xml


def create_volume(module, volume_utils, pool_name, vol_name, capacity, allocation, format):
    """Create a new volume"""
    if volume_utils.volume_exists(pool_name, vol_name):
        return False, "Volume already exists", None

    try:
        pool = volume_utils.conn.storagePoolLookupByName(pool_name)
        xml = get_volume_xml(vol_name, capacity, allocation, format)
        vol = pool.createXML(xml, 0)
        if vol is None:
            module.fail_json(msg="Failed to create the storage volume.")

        vol_info = volume_utils.get_volume_info(pool_name, vol_name)
        return True, "Volume created successfully", vol_info
    except libvirt.libvirtError as e:
        module.fail_json(msg=f"Error creating volume: {str(e)}")


def delete_volume(module, volume_utils, pool_name, vol_name):
    """Delete a volume"""
    try:
        if not volume_utils.volume_exists(pool_name, vol_name):
            return False, "Volume does not exist", None

        pool = volume_utils.conn.storagePoolLookupByName(pool_name)
        vol = pool.storageVolLookupByName(vol_name)
        vol.delete(0)
        return True, "Volume deleted successfully", None
    except libvirt.libvirtError as e:
        module.fail_json(msg=f"Error deleting volume: {str(e)}")


def resize_volume(module, volume_utils, pool_name, vol_name, new_capacity):
    """Resize a volume"""
    try:
        if not volume_utils.volume_exists(pool_name, vol_name):
            module.fail_json(msg=f"Volume {vol_name} does not exist")

        pool = volume_utils.conn.storagePoolLookupByName(pool_name)
        vol = pool.storageVolLookupByName(vol_name)
        current_capacity = vol.info()[1]
        new_capacity_bytes = parse_size(new_capacity)

        if new_capacity_bytes == current_capacity:
            return False, "Volume is already at the specified size", volume_utils.get_volume_info(pool_name, vol_name)
        elif new_capacity_bytes < current_capacity:
            module.fail_json(msg="New capacity must be larger than current capacity")

        vol.resize(new_capacity_bytes)
        vol_info = volume_utils.get_volume_info(pool_name, vol_name)
        return True, f"Volume resized from {current_capacity} to {new_capacity_bytes} bytes", vol_info
    except libvirt.libvirtError as e:
        module.fail_json(msg=f"Error resizing volume: {str(e)}")


def import_volume(module, volume_utils, pool_name, vol_name, import_path, import_format):
    """Import an existing image as a volume"""
    try:
        if volume_utils.volume_exists(pool_name, vol_name):
            return False, "Volume already exists", None

        if not os.path.exists(import_path):
            module.fail_json(msg=f"Import file {import_path} does not exist")

        image_size = os.path.getsize(import_path)
        pool = volume_utils.conn.storagePoolLookupByName(pool_name)

        # Create new volume
        xml = get_volume_xml(vol_name, str(image_size), str(image_size), import_format)
        vol = pool.createXML(xml, 0)
        if vol is None:
            module.fail_json(msg="Failed to create the storage volume for import.")

        # Upload content
        stream = volume_utils.conn.newStream(0)
        vol.upload(stream, 0, image_size, 0)

        with open(import_path, 'rb') as f:
            while True:
                data = f.read(1024 * 1024)  # Read 1MB at a time
                if not data:
                    break
                stream.send(data)

        stream.finish()
        vol_info = volume_utils.get_volume_info(pool_name, vol_name)
        return True, f"Volume imported successfully (format: {import_format})", vol_info
    except (libvirt.libvirtError, IOError) as e:
        module.fail_json(msg=f"Error importing volume: {str(e)}")


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
            pool=dict(type='str', required=True),
            capacity=dict(type='str'),
            allocation=dict(type='str'),
            format=dict(type='str', choices=['raw', 'qcow2', 'vmdk'], default='raw'),
            state=dict(type='str', choices=['present', 'absent', 'resize', 'import'], default='present'),
            uri=dict(type='str', default='qemu:///system'),
            remote_host=dict(type='str', required=False),
            auth_user=dict(type='str', required=False),
            auth_password=dict(type='str', required=False, no_log=True),
            import_image=dict(type='str'),
            import_format=dict(type='str', choices=['raw', 'qcow2', 'vmdk'], default='qcow2')
        ),
        supports_check_mode=True,
    )

    if not HAS_LIBVIRT:
        module.fail_json(msg='The libvirt python module is required for this module.')

    # Initialize connection handler
    libvirt_conn = LibvirtConnection(module)

    # Setup connection parameters
    libvirt_conn.setup_connection_params(
        uri=module.params['uri'],
        auth_user=module.params['auth_user'],
        auth_password=module.params['auth_password'],
        remote_host=module.params['remote_host']
    )

    try:
        # Establish connection
        success, conn = libvirt_conn.connect()
        if not success:
            module.fail_json(msg=f"Failed to connect to libvirt: {conn}")

        # Initialize volume utilities
        volume_utils = VolumeUtils(conn)

        name = module.params['name']
        pool = module.params['pool']
        capacity = module.params['capacity']
        allocation = module.params['allocation']
        format = module.params['format']
        state = module.params['state']
        import_image = module.params['import_image']
        import_format = module.params['import_format']

        result = {'changed': False}

        try:
            if state == 'present':
                if import_image:
                    changed, message, vol_info = import_volume(module, volume_utils, pool, name,
                                                               import_image, import_format)
                else:
                    if not capacity:
                        module.fail_json(msg="'capacity' is required when state is 'present'")
                    if not allocation:
                        allocation = '0'  # Default to thin provisioning
                    changed, message, vol_info = create_volume(module, volume_utils, pool, name,
                                                               capacity, allocation, format)
            elif state == 'absent':
                changed, message, vol_info = delete_volume(module, volume_utils, pool, name)
            elif state == 'resize':
                if not capacity:
                    module.fail_json(msg="'capacity' is required when state is 'resize'")
                changed, message, vol_info = resize_volume(module, volume_utils, pool, name, capacity)
            elif state == 'import':
                if not import_image:
                    module.fail_json(msg="'import_image' is required when state is 'import'")
                changed, message, vol_info = import_volume(module, volume_utils, pool, name,
                                                           import_image, import_format)

            result['changed'] = changed
            result['msg'] = message
            if vol_info:
                result['volume_info'] = vol_info

            module.exit_json(**result)

        except Exception as e:
            module.fail_json(msg=f"Unexpected error: {str(e)}", exception=traceback.format_exc())
    finally:
        libvirt_conn.close()


if __name__ == '__main__':
    main()