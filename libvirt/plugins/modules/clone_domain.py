# ./plugins/modules/clone_domain.py
# nsys-ai-claude-3.5

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r'''
---
module: clone_domain
short_description: Clone a libvirt domain
description:
  - Create a clone of an existing libvirt domain
  - Can create full clone (copy of storage) or linked clone (COW)
  - Supports customization of clone name, UUID, and MAC addresses
  - Works with both running and inactive domains
  - Can specify target storage pool for cloned volumes
options:
  name:
    description:
      - Name of the source domain to clone
    required: true
    type: str
  clone_name:
    description:
      - Name for the cloned domain
    required: true
    type: str
  linked_clone:
    description:
      - Create a linked clone using copy-on-write for storage
      - Much faster but requires original domain to remain
    type: bool
    default: false
  target_storage_pool:
    description:
      - Name of the storage pool to store cloned volumes
      - If not specified, volumes will be cloned to their original pools
    type: str
    required: false
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
  - "libvirt-python >= 5.6.0"
author:
  - "N-One Systems AI (@n-one-systems)"
'''

EXAMPLES = r'''
- name: Create a full clone of a domain in a specific storage pool
  nsys.libvirt.clone_domain:
    name: source_vm
    clone_name: cloned_vm 
    target_storage_pool: mypool

- name: Create a linked clone in default pool
  nsys.libvirt.clone_domain:
    name: source_vm
    clone_name: fast_clone
    linked_clone: true
'''

RETURN = r'''
changed:
    description: Whether any changes were made
    type: bool
    returned: always
clone_info:
    description: Information about the cloned domain
    type: dict
    returned: success
    contains:
        name:
            description: Name of the clone
            type: str
        uuid:
            description: UUID of the clone
            type: str
        storage:
            description: List of cloned storage volumes
            type: list
            contains:
                name:
                    description: Volume name
                    type: str
                path:
                    description: Volume path
                    type: str
                type:
                    description: Clone type (full/cow)
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
import uuid
import random
import traceback
import xml.etree.ElementTree as ET

try:
    import libvirt
    HAS_LIBVIRT = True
except ImportError:
    HAS_LIBVIRT = False

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.nsys.libvirt.plugins.module_utils.libvirt_connection import LibvirtConnection
from ansible_collections.nsys.libvirt.plugins.module_utils.volume_utils import VolumeUtils
from ansible_collections.nsys.libvirt.plugins.module_utils.domain_utils import DomainUtils

def generate_mac_address():
    """Generate a random MAC address in KVM format"""
    mac = [0x52, 0x54, 0x00,
           random.randint(0x00, 0xff),
           random.randint(0x00, 0xff),
           random.randint(0x00, 0xff)]
    return ':'.join(map(lambda x: "%02x" % x, mac))

def clone_volume(vol_utils, source_vol, target_name, target_pool=None, linked_clone=False):
    """
    Clone a storage volume, optionally to a different pool
    
    Args:
        vol_utils: VolumeUtils instance
        source_vol: Source volume object
        target_name: Name for cloned volume
        target_pool: Target pool object (optional)
        linked_clone: Whether to create a COW clone
    """
    try:
        source_pool = source_vol.storagePoolLookupByVolume()
        vol_xml = source_vol.XMLDesc(0)
        
        # Parse XML to get format
        root = ET.fromstring(vol_xml)
        format_elem = root.find(".//format")
        vol_format = format_elem.get('type') if format_elem is not None else 'raw'
        
        # Modify XML for clone
        root.find('name').text = target_name
        if root.find('key') is not None:
            root.find('key').text = str(uuid.uuid4())
            
        # Get target pool path
        pool_to_use = target_pool if target_pool else source_pool
        pool_xml = ET.fromstring(pool_to_use.XMLDesc(0))
        pool_path = pool_xml.find('.//path').text
            
        # Update target path
        target = root.find('.//target/path')
        if target is not None:
            new_path = os.path.join(pool_path, target_name)
            target.text = new_path

        clone_xml = ET.tostring(root, encoding='unicode')
        
        # Create the clone
        flags = libvirt.VIR_STORAGE_VOL_CREATE_PREALLOC_METADATA
        if linked_clone and vol_format == 'qcow2':
            # For linked clones, we need to create in the same pool as source
            if target_pool:
                raise Exception("Linked clones must be in the same pool as the source volume")
            # Create COW clone
            backing_store = source_vol.path()
            clone_vol = pool_to_use.createXML(clone_xml, flags)
            # Set up backing chain
            clone_vol.backingStore(backing_store, vol_format, 0)
        else:
            # Full clone - can be in different pool
            clone_vol = pool_to_use.createXMLFrom(clone_xml, source_vol, flags)
            
        return {
            'name': target_name,
            'path': clone_vol.path(),
            'type': 'cow' if linked_clone else 'full',
            'pool': pool_to_use.name()
        }
        
    except libvirt.libvirtError as e:
        raise Exception(f"Failed to clone volume: {str(e)}")

def clone_domain_xml(xml_str, clone_name, volume_map):
    """
    Prepare domain XML for clone, updating volume paths
    
    Args:
        xml_str: Original domain XML
        clone_name: Name for the cloned domain
        volume_map: Dict mapping original volume paths to cloned volume paths
    """
    try:
        root = ET.fromstring(xml_str)
        
        # Update name
        root.find('name').text = clone_name
        
        # Generate new UUID
        root.find('uuid').text = str(uuid.uuid4())
        
        # Generate new MAC addresses
        for interface in root.findall('.//interface/mac'):
            interface.set('address', generate_mac_address())
            
        # Update disk paths to point to cloned volumes
        for disk in root.findall('.//disk'):
            if disk.get('device') == 'disk':
                source = disk.find('source')
                if source is not None:
                    orig_path = source.get('file')
                    if orig_path in volume_map:
                        source.set('file', volume_map[orig_path])
            
        # Remove any runtime-specific elements
        for elem in root.findall(".//domain/*[@uuid]"):
            elem.attrib.pop('uuid', None)
            
        return ET.tostring(root, encoding='unicode')
    except Exception as e:
        raise Exception(f"Failed to prepare clone XML: {str(e)}")

def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
            clone_name=dict(type='str', required=True),
            linked_clone=dict(type='bool', default=False),
            target_storage_pool=dict(type='str', required=False),
            uri=dict(type='str', default='qemu:///system'),
            remote_host=dict(type='str', required=False),
            auth_user=dict(type='str', required=False),
            auth_password=dict(type='str', required=False, no_log=True),
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
        volume_utils = VolumeUtils(conn)
        domain_utils = DomainUtils(conn)

        name = module.params['name']
        clone_name = module.params['clone_name']
        linked_clone = module.params['linked_clone']
        target_pool_name = module.params.get('target_storage_pool')

        result = {
            'changed': False,
            'clone_info': {},
            'msg': ''
        }

        try:
            # Verify source domain exists
            if not domain_utils.domain_exists(name):
                module.fail_json(msg=f"Source domain {name} not found")

            # Check if clone already exists
            if domain_utils.domain_exists(clone_name):
                # Get info about existing clone for return value
                clone_info = domain_utils.get_domain_info(clone_name)
                result['clone_info'] = {
                    'name': clone_name,
                    'uuid': clone_info.get('uuid', ''),
                    'storage': []  # We don't track the original clone operation's storage info
                }
                result['msg'] = f"Domain clone '{clone_name}' already exists"
                module.exit_json(**result)

            # Get target storage pool if specified
            target_pool = None
            if target_pool_name:
                try:
                    target_pool = conn.storagePoolLookupByName(target_pool_name)
                    # Ensure pool is active
                    if not target_pool.isActive():
                        module.fail_json(msg=f"Target storage pool {target_pool_name} is not active")
                except libvirt.libvirtError:
                    module.fail_json(msg=f"Target storage pool {target_pool_name} not found")

            # Linked clones can't be in a different pool
            if linked_clone and target_pool_name:
                module.fail_json(msg="Linked clones must be in the same storage pool as the source volume")

            source_domain = conn.lookupByName(name)
            source_xml = source_domain.XMLDesc(0)

            if not module.check_mode:
                # First pass: identify and clone all storage volumes
                cloned_volumes = []
                volume_map = {}  # Maps original paths to cloned paths
                root = ET.fromstring(source_xml)

                for disk in root.findall('.//disk'):
                    if disk.get('device') == 'disk':  # Only clone actual disks, not CDROMs
                        source = disk.find('source')
                        if source is not None:
                            source_path = source.get('file')
                            if source_path:
                                try:
                                    source_vol = conn.storageVolLookupByPath(source_path)
                                    target_name = os.path.basename(source_path).replace(name, clone_name)
                                    cloned_vol = clone_volume(volume_utils, source_vol, target_name,
                                                              target_pool, linked_clone)
                                    cloned_volumes.append(cloned_vol)
                                    volume_map[source_path] = cloned_vol['path']
                                except libvirt.libvirtError as e:
                                    # Clean up any volumes we've already cloned
                                    for vol in cloned_volumes:
                                        try:
                                            clone_vol = conn.storageVolLookupByPath(vol['path'])
                                            clone_vol.delete(0)
                                        except:
                                            pass
                                    raise Exception(f"Failed to clone volume: {str(e)}")

                # Second pass: create domain XML with updated paths
                clone_xml = clone_domain_xml(source_xml, clone_name, volume_map)

                # Define the cloned domain
                clone_domain = conn.defineXML(clone_xml)

                result['clone_info'] = {
                    'name': clone_name,
                    'uuid': clone_domain.UUIDString(),
                    'storage': cloned_volumes
                }

                # Handle power state if specified in playbook
                try:
                    # Start the domain if power_state is running
                    power_state = module.params.get('power_state', 'running')
                    if power_state == 'running' and not clone_domain.isActive():
                        clone_domain.create()
                except libvirt.libvirtError as e:
                    # Don't fail if power state management fails
                    result['msg'] = f"Domain cloned but failed to set power state: {str(e)}"
                    module.exit_json(**result)

            result['changed'] = True
            target_pool_msg = f" in pool {target_pool_name}" if target_pool_name else ""
            result[
                'msg'] = f"Successfully created {'linked' if linked_clone else 'full'} clone {clone_name}{target_pool_msg}"

            module.exit_json(**result)

        except Exception as e:
            module.fail_json(msg=f"Error cloning domain: {str(e)}", exception=traceback.format_exc())

    finally:
        libvirt_conn.close()


if __name__ == '__main__':
    main()