# ./plugins/modules/storage_pool.py
# nsys-ai-claude-3.5

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r'''
---
module: storage_pool
short_description: Manage libvirt storage pools
description:
  - Create, delete, start, stop and modify libvirt storage pools
  - Supports different pool types (dir, logical, disk, iscsi, etc.)
  - Manages pool state (active/inactive)
  - Controls pool autostart behavior
options:
  name:
    description:
      - Name of the storage pool
    required: true
    type: str
  pool_type:
    description:
      - Type of the storage pool
      - Required when creating a new pool
    type: str
    choices: [ 'dir', 'fs', 'netfs', 'logical', 'disk', 'iscsi', 'scsi', 'mpath', 'rbd', 'sheepdog', 'gluster', 'zfs', 'vstorage' ]
  target_path:
    description:
      - Target path for the storage pool
      - Required for most pool types when creating a new pool
    type: str
  source_path:
    description:
      - Source path for the storage pool
      - Required for some pool types (fs, logical, etc.)
    type: str
  source_host:
    description:
      - Source host for remote storage pools
      - Required for some pool types (netfs, iscsi, etc.)
    type: str
  source_format:
    description:
      - Source format for the storage pool
      - Required for some pool types (fs, logical, etc.)
    type: str
  state:
    description:
      - State of the storage pool
    type: str
    choices: [ 'present', 'absent', 'active', 'inactive' ]
    default: 'present'
  autostart:
    description:
      - Whether to start the pool when host boots
    type: bool
    default: true
  uri:
    description:
      - libvirt connection uri
    type: str
    default: 'qemu:///system'
  mode:
    description:
      - Permission mode for the target path
    type: str
    default: '0711'
  owner:
    description:
      - Owner of the target path
    type: str
  group:
    description:
      - Group of the target path
    type: str
requirements:
  - "python >= 3.12"
  - "libvirt-python >= 5.6.0"
author:
  - "N-One Systems AI (@n-one-systems)"
'''

EXAMPLES = r'''
# Create a directory-based storage pool
- name: Create a basic storage pool
  nsys.libvirt.storage_pool:
    name: vm-images
    pool_type: dir
    target_path: /var/lib/libvirt/images
    state: present
    autostart: true

# Create a logical volume based storage pool
- name: Create a LVM storage pool
  nsys.libvirt.storage_pool:
    name: vg_images
    pool_type: logical
    source_path: /dev/sdb
    source_format: lvm2
    target_path: /dev/vg_images
    state: present

# Remove a storage pool
- name: Remove storage pool
  nsys.libvirt.storage_pool:
    name: vm-images
    state: absent

# Ensure pool is active
- name: Start storage pool
  nsys.libvirt.storage_pool:
    name: vm-images
    state: active
'''

RETURN = r'''
changed:
    description: Whether any changes were made
    type: bool
    returned: always
pool_info:
    description: Information about the storage pool
    type: dict
    returned: success
    contains:
        name:
            description: Pool name
            type: str
        state:
            description: Pool state
            type: str
        autostart:
            description: Whether pool autostarts
            type: bool
        persistent:
            description: Whether pool is persistent
            type: bool
        capacity:
            description: Pool capacity in bytes
            type: int
        allocation:
            description: Current allocation in bytes
            type: int
        available:
            description: Available space in bytes
            type: int
        target_path:
            description: Target path of the pool
            type: str
        type:
            description: Pool type
            type: str
msg:
    description: Status message
    type: str
    returned: always
'''

import os
import traceback
import xml.etree.ElementTree as ET

try:
    import libvirt
    HAS_LIBVIRT = True
except ImportError:
    HAS_LIBVIRT = False

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.nsys.libvirt.plugins.module_utils.libvirt_connection import LibvirtConnection


def get_pool_state(pool):
    """Get the current state of the pool"""
    state_map = {
        libvirt.VIR_STORAGE_POOL_INACTIVE: 'inactive',
        libvirt.VIR_STORAGE_POOL_BUILDING: 'building',
        libvirt.VIR_STORAGE_POOL_RUNNING: 'active',
        libvirt.VIR_STORAGE_POOL_DEGRADED: 'degraded',
        libvirt.VIR_STORAGE_POOL_INACCESSIBLE: 'inaccessible',
    }
    return state_map.get(pool.info()[0], 'unknown')


def get_pool_info(pool):
    """Get detailed information about a storage pool"""
    info = pool.info()
    xml = pool.XMLDesc(0)
    root = ET.fromstring(xml)
    target = root.find('target')
    target_path = target.find('path').text if target is not None and target.find('path') is not None else None

    return {
        'name': pool.name(),
        'state': get_pool_state(pool),
        'autostart': pool.autostart(),
        'persistent': pool.isPersistent(),
        'capacity': info[1],
        'allocation': info[2],
        'available': info[3],
        'target_path': target_path,
        'type': root.get('type')
    }


def build_pool_xml(name, pool_type, target_path, source_path=None, source_host=None, source_format=None):
    """Build XML for pool definition"""
    pool = ET.Element('pool', type=pool_type)
    ET.SubElement(pool, 'name').text = name

    # Add source configuration if provided
    if any([source_path, source_host, source_format]):
        source = ET.SubElement(pool, 'source')
        if source_path:
            ET.SubElement(source, 'device', path=source_path)
        if source_host:
            ET.SubElement(source, 'host', name=source_host)
        if source_format:
            ET.SubElement(source, 'format', type=source_format)

    # Add target configuration
    target = ET.SubElement(pool, 'target')
    ET.SubElement(target, 'path').text = target_path

    return ET.tostring(pool).decode()


def create_pool_target(module, target_path, mode, owner=None, group=None):
    """Create the target directory with appropriate permissions"""
    if not os.path.exists(target_path):
        try:
            os.makedirs(target_path, int(mode, 8))
            if owner or group:
                os.chown(target_path,
                        int(owner) if owner else -1,
                        int(group) if group else -1)
            return True
        except Exception as e:
            module.fail_json(msg=f"Failed to create target path: {str(e)}")
    return False


def manage_pool(module, conn):
    """Manage the storage pool lifecycle"""
    name = module.params['name']
    pool_type = module.params['pool_type']
    target_path = module.params['target_path']
    source_path = module.params['source_path']
    source_host = module.params['source_host']
    source_format = module.params['source_format']
    state = module.params['state']
    autostart = module.params['autostart']
    mode = module.params['mode']
    owner = module.params['owner']
    group = module.params['group']

    result = {'changed': False}
    pool = None

    try:
        pool = conn.storagePoolLookupByName(name)
    except libvirt.libvirtError:
        if state == 'absent':
            module.exit_json(changed=False, msg="Pool already absent")

    # Handle pool removal
    if state == 'absent' and pool:
        if pool.isActive():
            pool.destroy()
        if pool.isPersistent():
            pool.undefine()
        result['changed'] = True
        result['msg'] = f"Pool {name} removed"
        return result

    # Create new pool if it doesn't exist
    if not pool and state != 'absent':
        if not pool_type:
            module.fail_json(msg="pool_type is required when creating a new pool")
        if not target_path:
            module.fail_json(msg="target_path is required when creating a new pool")

        # Create target directory for directory-based pools
        if pool_type == 'dir':
            result['changed'] = create_pool_target(module, target_path, mode, owner, group)

        # Define the pool
        xml = build_pool_xml(name, pool_type, target_path, source_path, source_host, source_format)
        try:
            pool = conn.storagePoolDefineXML(xml)
            result['changed'] = True
        except libvirt.libvirtError as e:
            module.fail_json(msg=f"Failed to define pool: {str(e)}")

    # Handle pool state
    if pool:
        # Set autostart
        try:
            pool_autostart = pool.autostart()
            if autostart != pool_autostart:
                pool.setAutostart(autostart)
                result['changed'] = True
        except libvirt.libvirtError as e:
            module.fail_json(msg=f"Failed to set autostart: {str(e)}")

        # Handle active/inactive state
        pool_state = get_pool_state(pool)
        
        if state == 'active' and pool_state != 'active':
            if not pool.isActive():
                pool.create()
                result['changed'] = True
        elif state == 'inactive' and pool_state == 'active':
            pool.destroy()
            result['changed'] = True

        # Get final pool info
        result['pool_info'] = get_pool_info(pool)
        if result['changed']:
            result['msg'] = f"Pool {name} updated successfully"
        else:
            result['msg'] = f"Pool {name} is in desired state"

    return result


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
            pool_type=dict(type='str', choices=['dir', 'fs', 'netfs', 'logical', 'disk', 'iscsi', 'scsi', 'mpath', 'rbd', 'sheepdog', 'gluster', 'zfs', 'vstorage']),
            target_path=dict(type='str'),
            source_path=dict(type='str'),
            source_host=dict(type='str'),
            source_format=dict(type='str'),
            state=dict(type='str', choices=['present', 'absent', 'active', 'inactive'], default='present'),
            autostart=dict(type='bool', default=True),
            uri=dict(type='str', default='qemu:///system'),
            mode=dict(type='str', default='0711'),
            owner=dict(type='str'),
            group=dict(type='str')
        ),
        supports_check_mode=True
    )

    if not HAS_LIBVIRT:
        module.fail_json(msg='The libvirt python module is required')

    # Initialize connection handler
    libvirt_conn = LibvirtConnection(module)
    
    # Setup connection parameters
    libvirt_conn.setup_connection_params(uri=module.params['uri'])

    try:
        # Establish connection
        success, conn = libvirt_conn.connect()
        if not success:
            module.fail_json(msg=f"Failed to connect to libvirt: {conn}")

        if module.check_mode:
            module.exit_json(changed=True)

        result = manage_pool(module, conn)
        module.exit_json(**result)

    except Exception as e:
        module.fail_json(msg=f"Unexpected error: {str(e)}", exception=traceback.format_exc())
    finally:
        libvirt_conn.close()


if __name__ == '__main__':
    main()
