#!/usr/bin/python

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
  - "python >= 3.11"
  - "libvirt-python"
author:
  - "N-One Systems an AI (@n-one-systems)"
'''

EXAMPLES = r'''
- name: Create a storage volume
  libvirt_volume:
    name: my_volume
    pool: default
    capacity: 5G
    format: qcow2
    state: present

- name: Resize a storage volume
  libvirt_volume:
    name: my_volume
    pool: default
    capacity: 10G
    state: resize

- name: Delete a storage volume
  libvirt_volume:
    name: my_volume
    pool: default
    state: absent

- name: Import an existing qcow2 image
  libvirt_volume:
    name: imported_volume
    pool: default
    import_image: /path/to/existing/image.qcow2
    import_format: qcow2
    state: import
'''

RETURN = r'''
'''

import traceback
import os

try:
    import libvirt
except ImportError:
    HAS_LIBVIRT = False
else:
    HAS_LIBVIRT = True

from ansible.module_utils.basic import AnsibleModule

def parse_size(size_str):
    units = {'B': 1, 'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4}
    size = size_str.strip()
    unit = size[-1].upper()
    if unit in units:
        return int(float(size[:-1]) * units[unit])
    else:
        return int(size)

def get_volume_xml(name, capacity, allocation, format):
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

def create_volume(module, conn, pool_name, vol_name, capacity, allocation, format):
    try:
        pool = conn.storagePoolLookupByName(pool_name)
        if not pool:
            module.fail_json(msg=f"Storage pool '{pool_name}' not found.")

        # Check if volume already exists
        try:
            vol = pool.storageVolLookupByName(vol_name)
            return False, "Volume already exists"
        except libvirt.libvirtError:
            pass  # Volume doesn't exist, we can create it

        xml = get_volume_xml(vol_name, capacity, allocation, format)
        vol = pool.createXML(xml, 0)
        if vol is None:
            module.fail_json(msg="Failed to create the storage volume.")
        return True, "Volume created successfully"
    except libvirt.libvirtError as e:
        module.fail_json(msg=f"Error creating volume: {str(e)}")

def delete_volume(module, conn, pool_name, vol_name):
    try:
        pool = conn.storagePoolLookupByName(pool_name)
        if not pool:
            module.fail_json(msg=f"Storage pool '{pool_name}' not found.")

        try:
            vol = pool.storageVolLookupByName(vol_name)
            vol.delete(0)
            return True, "Volume deleted successfully"
        except libvirt.libvirtError:
            return False, "Volume does not exist"
    except libvirt.libvirtError as e:
        module.fail_json(msg=f"Error deleting volume: {str(e)}")

def resize_volume(module, conn, pool_name, vol_name, new_capacity):
    try:
        pool = conn.storagePoolLookupByName(pool_name)
        if not pool:
            module.fail_json(msg=f"Storage pool '{pool_name}' not found.")

        try:
            vol = pool.storageVolLookupByName(vol_name)
            current_capacity = vol.info()[1]  # Get current capacity
            new_capacity_bytes = parse_size(new_capacity)

            if new_capacity_bytes == current_capacity:
                return False, "Volume is already at the specified size"
            elif new_capacity_bytes < current_capacity:
                module.fail_json(msg="New capacity must be larger than current capacity")

            vol.resize(new_capacity_bytes)
            return True, f"Volume resized from {current_capacity} to {new_capacity_bytes} bytes"
        except libvirt.libvirtError as e:
            module.fail_json(msg=f"Error resizing volume: {str(e)}")
    except libvirt.libvirtError as e:
        module.fail_json(msg=f"Error accessing volume: {str(e)}")

def import_volume(module, conn, pool_name, vol_name, import_path, import_format):
    try:
        pool = conn.storagePoolLookupByName(pool_name)
        if not pool:
            module.fail_json(msg=f"Storage pool '{pool_name}' not found.")

        # Check if volume already exists
        try:
            vol = pool.storageVolLookupByName(vol_name)
            return False, "Volume already exists"
        except libvirt.libvirtError:
            pass  # Volume doesn't exist, we can import it

        # Get the size of the existing image
        image_size = os.path.getsize(import_path)

        # Create a new volume with the same size as the existing image
        xml = get_volume_xml(vol_name, str(image_size), str(image_size), import_format)
        vol = pool.createXML(xml, 0)
        if vol is None:
            module.fail_json(msg="Failed to create the storage volume for import.")

        # Upload the content of the existing image to the new volume
        stream = conn.newStream(0)
        vol.upload(stream, 0, image_size, 0)
        
        with open(import_path, 'rb') as f:
            data = f.read(1024*1024)  # Read 1MB at a time
            while data:
                stream.send(data)
                data = f.read(1024*1024)
        
        stream.finish()
        return True, f"Volume imported successfully (format: {import_format})"
    except libvirt.libvirtError as e:
        module.fail_json(msg=f"Error importing volume: {str(e)}")
    except IOError as e:
        module.fail_json(msg=f"Error reading import file: {str(e)}")

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
            import_image=dict(type='str'),
            import_format=dict(type='str', choices=['raw', 'qcow2', 'vmdk'], default='qcow2')
        ),
        supports_check_mode=True,
    )

    if not HAS_LIBVIRT:
        module.fail_json(msg='The libvirt python module is required for this module.')

    name = module.params['name']
    pool = module.params['pool']
    capacity = module.params['capacity']
    allocation = module.params['allocation']
    format = module.params['format']
    state = module.params['state']
    uri = module.params['uri']
    import_image = module.params['import_image']
    import_format = module.params['import_format']

    try:
        conn = libvirt.open(uri)
    except libvirt.libvirtError as e:
        module.fail_json(msg=f'Failed to open connection to {uri}: {str(e)}')

    try:
        changed = False
        if state == 'present':
            if import_image:
                changed, message = import_volume(module, conn, pool, name, import_image, import_format)
            else:
                if not capacity:
                    module.fail_json(msg="'capacity' is required when state is 'present' and not importing an image")
                if not allocation:
                    allocation = '0'  # Default to thin provisioning
                changed, message = create_volume(module, conn, pool, name, capacity, allocation, format)
        elif state == 'absent':
            changed, message = delete_volume(module, conn, pool, name)
        elif state == 'resize':
            if not capacity:
                module.fail_json(msg="'capacity' is required when state is 'resize'")
            changed, message = resize_volume(module, conn, pool, name, capacity)
        elif state == 'import':
            if not import_image:
                module.fail_json(msg="'import_image' is required when state is 'import'")
            changed, message = import_volume(module, conn, pool, name, import_image, import_format)

        module.exit_json(changed=changed, msg=message)
    except Exception as e:
        module.fail_json(msg=f"Unexpected error: {str(e)}", exception=traceback.format_exc())
    finally:
        conn.close()

if __name__ == '__main__':
    main()
