# ./plugins/modules/storage/pool.py
# nsys-ai-claude-3.5

from __future__ import (absolute_import, division, print_function)

__metaclass__ = type

DOCUMENTATION = r'''
---
module: pool
short_description: Manage libvirt storage pools
description:
  - Create, delete, start, stop and modify libvirt storage pools
  - Supports different pool types (dir, logical, disk, iscsi, etc.)
  - Manages pool state (active/inactive)
  - Controls pool autostart behavior
  - Comprehensive permission management for pool directories
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
  mode:
    description:
      - Permission mode for the target path
      - Applied to pool directory and recursively to all contents
    type: str
    default: '0755'
  owner:
    description:
      - Owner of the target path and contents
      - Can be user name or UID
    type: str
  group:
    description:
      - Group of the target path and contents
      - Can be group name or GID
    type: str
  recursive_permissions:
    description:
      - Whether to apply permissions recursively to all pool contents
      - Only applies to directory-based pools
    type: bool
    default: true
  uri:
    description:
      - libvirt connection uri
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
requirements:
  - "python >= 3.12"
  - "libvirt-python >= 10.9.0"
author:
  - "N-One Systems AI (@n-one-systems)"
'''

EXAMPLES = r'''
# Create a basic directory-based storage pool
- name: Create a basic storage pool
  nsys.libvirt.storage.pool
    name: vm-images
    pool_type: dir
    target_path: /var/lib/libvirt/images
    state: present
    mode: '0755'
    owner: qemu
    group: qemu
    autostart: true

# Remove a storage pool
- name: Remove storage pool
  nsys.libvirt.storage.pool
    name: vm-images
    state: absent

# Ensure pool is active with specific permissions
- name: Configure active pool with permissions
  nsys.libvirt.storage.pool
    name: vm-images
    state: active
    mode: '0755'
    owner: qemu
    group: qemu
    recursive_permissions: true
'''
import os
import traceback
try:
    import libvirt
    HAS_LIBVIRT = True
except ImportError:
    HAS_LIBVIRT = False

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.nsys.libvirt.plugins.module_utils.common.libvirt_connection import LibvirtConnection
from ansible_collections.nsys.libvirt.plugins.module_utils.storage.pool_utils import StoragePoolUtils
from ansible_collections.nsys.libvirt.plugins.module_utils.common.permission_manager import PermissionManager

def manage_pool(module: AnsibleModule, pool_utils: StoragePoolUtils, perm_manager: PermissionManager) -> dict:
    """
    Main function to manage storage pool lifecycle
    """
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
        try:
            pool = pool_utils.conn.storagePoolLookupByName(name)
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
                try:
                    # Create directory with proper permissions
                    # Note: recursive=False since we only want to set permissions on the pool directory
                    changed = perm_manager.create_with_permissions(
                        target_path,
                        mode,
                        owner,
                        group,
                        is_directory=True
                    )
                    result['changed'] = changed or result['changed']
                except Exception as e:
                    module.fail_json(msg=f"Failed to create target path: {str(e)}")

            # Define the pool
            try:
                target_permissions = {
                    'mode': mode,
                    'owner': owner,
                    'group': group
                } if any([mode, owner, group]) else None
                xml = pool_utils.build_pool_xml(
                    name=name,
                    pool_type=pool_type,
                    target_path=target_path,
                    source_path=source_path,
                    source_host=source_host,
                    source_format=source_format,
                    target_permissions=target_permissions
                )

                # Define the storage pool with the XML
                pool = pool_utils.conn.storagePoolDefineXML(xml)
                if not pool:
                    raise libvirt.libvirtError("Failed to define storage pool")

                result['changed'] = True
            except libvirt.libvirtError as e:
                module.fail_json(msg=f"Failed to define pool: {str(e)}")

        # Handle pool state and permissions
        if pool:
            # Manage pool state
            try:
                desired_state = 'active' if state in ['present', 'active'] else 'inactive'
                state_changed, state_msg = pool_utils.manage_pool_state(pool, desired_state, autostart)
                result['changed'] = result['changed'] or state_changed
                if state_changed:
                    result['msg'] = state_msg
            except Exception as e:
                module.fail_json(msg=str(e))

            # Manage permissions only on the pool directory itself, not contents
            if pool_type == 'dir' and target_path and os.path.exists(target_path):
                try:
                    perm_changed = perm_manager.manage_permissions(
                        target_path,
                        mode,
                        owner,
                        group,
                        recursive=False  # Only set permissions on pool directory
                    )
                    result['changed'] = result['changed'] or perm_changed
                except Exception as e:
                    module.fail_json(msg=f"Failed to manage permissions: {str(e)}")

            # Get final pool info
            result['pool_info'] = pool_utils.get_pool_info(name)
            if not result.get('msg'):
                result['msg'] = ("Pool state updated" if result['changed']
                               else "Pool is in desired state")

        return result

    except Exception as e:
        module.fail_json(msg=f"Unexpected error in manage_pool: {str(e)}")

def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
            pool_type=dict(type='str', choices=[
                'dir', 'fs', 'netfs', 'logical', 'disk', 'iscsi', 'scsi',
                'mpath', 'rbd', 'sheepdog', 'gluster', 'zfs', 'vstorage'
            ]),
            target_path=dict(type='str'),
            source_path=dict(type='str'),
            source_host=dict(type='str'),
            source_format=dict(type='str'),
            state=dict(type='str', choices=['present', 'absent', 'active', 'inactive'],
                      default='present'),
            autostart=dict(type='bool', default=True),
            mode=dict(type='str', default='0755'),
            owner=dict(type='str'),
            group=dict(type='str'),
            recursive_permissions=dict(type='bool', default=True),
            uri=dict(type='str', default='qemu:///system'),
            remote_host=dict(type='str', required=False),
            auth_user=dict(type='str', required=False),
            auth_password=dict(type='str', required=False, no_log=True)
        ),
        supports_check_mode=True
    )

    if not HAS_LIBVIRT:
        module.fail_json(msg='The libvirt python module is required')

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

        # Initialize utilities
        pool_utils = StoragePoolUtils(conn)
        perm_manager = PermissionManager(module)

        if module.check_mode:
            module.exit_json(changed=True)

        result = manage_pool(module, pool_utils, perm_manager)
        module.exit_json(**result)

    except Exception as e:
        module.fail_json(msg=f"Unexpected error: {str(e)}",
                        exception=traceback.format_exc())
    finally:
        libvirt_conn.close()


if __name__ == '__main__':
    main()
