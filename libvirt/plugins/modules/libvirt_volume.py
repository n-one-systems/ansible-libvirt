#!/usr/bin/python

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: libvirt_volume
short_description: Manage libvirt storage volumes
description:
  - Create or delete libvirt storage volumes.
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
    choices: [ 'present', 'absent' ]
    default: 'present'
  uri:
    description:
      - libvirt connection uri.
    type: str
    default: 'qemu:///system'
requirements:
  - "python >= 2.6"
  - "libvirt-python"
author:
  - "Your Name (@yourgithubusername)"
'''

EXAMPLES = r'''
- name: Create a storage volume
  libvirt_volume:
    name: my_volume
    pool: default
    capacity: 5G
    format: qcow2
    state: present

- name: Delete a storage volume
  libvirt_volume:
    name: my_volume
    pool: default
    state: absent
'''

RETURN = r'''
'''

import traceback

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

def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
            pool=dict(type='str', required=True),
            capacity=dict(type='str'),
            allocation=dict(type='str'),
            format=dict(type='str', choices=['raw', 'qcow2', 'vmdk'], default='raw'),
            state=dict(type='str', choices=['present', 'absent'], default='present'),
            uri=dict(type='str', default='qemu:///system')
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

    try:
        conn = libvirt.open(uri)
    except libvirt.libvirtError as e:
        module.fail_json(msg=f'Failed to open connection to {uri}: {str(e)}')

    try:
        changed = False
        if state == 'present':
            if not capacity:
                module.fail_json(msg="'capacity' is required when state is 'present'")
            if not allocation:
                allocation = '0'  # Default to thin provisioning
            changed, message = create_volume(module, conn, pool, name, capacity, allocation, format)
        elif state == 'absent':
            changed, message = delete_volume(module, conn, pool, name)

        module.exit_json(changed=changed, msg=message)
    except Exception as e:
        module.fail_json(msg=f"Unexpected error: {str(e)}", exception=traceback.format_exc())
    finally:
        conn.close()

if __name__ == '__main__':
    main()
