# ./plugins/modules/storage/attach.py

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r'''
---
module: attach_volume
short_description: Attach volumes to a libvirt domain
description:
  - Attach one or more storage volumes to a libvirt domain
  - Automatically detects if volume is an ISO image and attaches as CDROM using SATA bus
  - Handles regular volumes as virtio disk devices
  - Smart handling of multiple volumes with appropriate bus selection
  - Works with both running and inactive domains
  - Uses libvirt storage pool abstraction for volume management
options:
  name:
    description:
      - Name of the target domain to attach volumes to
    required: true
    type: str
  volumes:
    description:
      - List of volume names to attach
    required: true
    type: list
    elements: str
  pool:
    description:
      - Name of the storage pool containing the volumes
    required: true
    type: str
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
- name: Attach a single volume to running or stopped domain
  nsys.libvirt.storage.attach_volume:
    name: my_vm
    volumes: 
      - my_data_volume
    pool: default

- name: Attach multiple volumes including ISOs
  nsys.libvirt.storage.attach_volume:
    name: my_vm
    volumes:
      - data_vol1
      - installer1.iso
      - installer2.iso 
    pool: default
'''

RETURN = r'''
changed:
    description: Whether any changes were made
    type: bool
    returned: always
attached_volumes:
    description: Information about attached volumes
    type: list
    returned: success
    contains:
        name:
            description: Volume name
            type: str
        type:
            description: How volume was attached (disk/cdrom)
            type: str
        target:
            description: Target device name in guest
            type: str
        bus:
            description: Bus type used for attachment
            type: str
        persistent:
            description: Whether attachment is persistent
            type: bool
domain_state:
    description: State of the domain (running/shutoff)
    type: str
    returned: always
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
from ansible_collections.nsys.libvirt.plugins.module_utils.common.libvirt_connection import LibvirtConnection
from ansible_collections.nsys.libvirt.plugins.module_utils.storage.volume_utils import VolumeUtils
from ansible_collections.nsys.libvirt.plugins.module_utils.domain.domain_utils import DomainUtils

def is_iso_volume(volume):
    """
    Check if volume is an ISO image by checking its format
    Args:
        volume: libvirt volume object
    Returns:
        bool: True if volume is an ISO, False otherwise
    """
    try:
        vol_xml = volume.XMLDesc(0)
        root = ET.fromstring(vol_xml)
        format_elem = root.find(".//format")
        if format_elem is not None:
            return format_elem.get('type') == 'iso'
        # Fallback to checking file extension if format not specified
        return volume.name().lower().endswith('.iso')
    except libvirt.libvirtError:
        return False

def get_next_target_dev(dom_xml, device_prefix):
    """Get next available target device name"""
    root = ET.fromstring(dom_xml)
    existing = set()
    for disk in root.findall(".//disk/target"):
        dev = disk.get('dev', '')
        if dev.startswith(device_prefix):
            existing.add(dev)
    
    # Generate possible names
    index = 0
    while True:
        name = f"{device_prefix}{chr(ord('a') + index)}"
        if name not in existing:
            return name
        index += 1

def ensure_sata_controller(domain, dom_xml, is_running):
    """Ensure SATA controller exists, add if needed"""
    root = ET.fromstring(dom_xml)
    sata_controllers = root.findall(".//controller[@type='sata']")
    
    if not sata_controllers:
        controller_xml = """
        <controller type='sata' index='0'>
          <address type='pci' domain='0x0000' bus='0x00' slot='0x1f' function='0x2'/>
        </controller>
        """
        flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
        if is_running:
            flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE
        domain.attachDeviceFlags(controller_xml, flags)
        return True
    return False

def generate_disk_xml(volume, target_dev, device_type='disk'):
    """
    Generate XML for disk attachment using volume object
    Args:
        volume: libvirt volume object
        target_dev: target device name
        device_type: disk or cdrom
    Returns:
        tuple: (xml string, bus type)
    """
    pool = volume.storagePoolLookupByVolume()
    
    # Determine source based on pool type
    pool_type = ET.fromstring(pool.XMLDesc(0)).get('type')
    
    if pool_type == 'logical':
        source_tag = f"<source dev='{volume.path()}'/>"
        disk_type = 'block'
    else:
        source_tag = f"<source volume='{volume.name()}' pool='{pool.name()}'/>"
        disk_type = 'volume'

    # Use SATA for CDROMs and virtio for regular disks
    bus = 'sata' if device_type == 'cdrom' else 'virtio'
    
    xml = f"""
    <disk type='{disk_type}' device='{device_type}'>
      <driver name='qemu' type='raw'/>
      {source_tag}
      <target dev='{target_dev}' bus='{bus}'/>
      {'<readonly/>' if device_type == 'cdrom' else ''}
    </disk>
    """
    return xml.strip(), bus

def attach_device(domain, xml, is_running):
    """Attach device to domain with appropriate flags"""
    flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
    if is_running:
        flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE
    return domain.attachDeviceFlags(xml, flags)

def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
            volumes=dict(type='list', elements='str', required=True),
            pool=dict(type='str', required=True),
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

        domain_name = module.params['name']
        pool_name = module.params['pool']
        volume_names = module.params['volumes']

        result = {
            'changed': False,
            'attached_volumes': [],
            'msg': ''
        }

        # Verify domain exists
        if not domain_utils.domain_exists(domain_name):
            module.fail_json(msg=f"Domain {domain_name} not found")

        try:
            domain = conn.lookupByName(domain_name)
            is_running = domain.isActive()
            
            result['domain_state'] = 'running' if is_running else 'shutoff'
            
            # Get initial domain XML
            dom_xml = domain.XMLDesc(0)

            # Look up storage pool
            try:
                pool = conn.storagePoolLookupByName(pool_name)
            except libvirt.libvirtError:
                module.fail_json(msg=f"Storage pool '{pool_name}' not found")

            # Refresh pool to ensure we have current volume list
            try:
                pool.refresh(0)
            except libvirt.libvirtError as e:
                module.warn(f"Failed to refresh pool: {str(e)}")

            # Check volumes and determine if we need SATA controller
            volumes_to_attach = []
            for volume_name in volume_names:
                try:
                    volume = pool.storageVolLookupByName(volume_name)
                    volumes_to_attach.append(volume)
                except libvirt.libvirtError:
                    module.fail_json(msg=f"Volume '{volume_name}' not found in pool '{pool_name}'")

            # Check if we need SATA controller for ISOs
            has_iso = any(is_iso_volume(vol) for vol in volumes_to_attach)
            if has_iso:
                if not module.check_mode:
                    changed = ensure_sata_controller(domain, dom_xml, is_running)
                    if changed:
                        result['changed'] = True
                        dom_xml = domain.XMLDesc(0)  # Refresh XML

            # Attach volumes
            for volume in volumes_to_attach:
                # Determine device type and prefix
                device_type = 'cdrom' if is_iso_volume(volume) else 'disk'
                device_prefix = 'sd' if device_type == 'cdrom' else 'vd'

                # Get next available target device
                target_dev = get_next_target_dev(dom_xml, device_prefix)

                if not module.check_mode:
                    # Generate and attach disk XML
                    disk_xml, bus = generate_disk_xml(volume, target_dev, device_type)
                    attach_device(domain, disk_xml, is_running)
                    dom_xml = domain.XMLDesc(0)  # Refresh XML after each attachment

                result['attached_volumes'].append({
                    'name': volume.name(),
                    'type': device_type,
                    'target': target_dev,
                    'bus': bus,
                    'persistent': True
                })
                result['changed'] = True

            if result['changed']:
                result['msg'] = f"Successfully attached {len(volumes_to_attach)} volume(s) to {result['domain_state']} domain"
            else:
                result['msg'] = "No volumes were attached"

            module.exit_json(**result)

        except libvirt.libvirtError as e:
            module.fail_json(msg=f"Error attaching volumes: {str(e)}")
        except Exception as e:
            module.fail_json(msg=f"Unexpected error: {str(e)}", exception=traceback.format_exc())

    finally:
        libvirt_conn.close()

if __name__ == '__main__':
    main()
