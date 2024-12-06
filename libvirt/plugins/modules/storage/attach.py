# ./plugins/modules/storage/attach.py
# nsys-ai-claude-3.5

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
  - Prevents duplicate attachments of the same volume
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
requirements:
  - "python >= 3.12"
  - "libvirt-python >= 10.9.0"
author:
  - "N-One Systems AI (@n-one-systems)"
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


def is_volume_attached(domain_xml: str, volume_path: str) -> bool:
    """Check if volume is already attached to domain"""
    root = ET.fromstring(domain_xml)
    for disk in root.findall(".//disk"):
        source = disk.find("source")
        if source is not None:
            if source.get('file') == volume_path or source.get('volume') == os.path.basename(volume_path):
                return True
    return False


def is_iso_volume(volume):
    """Check if volume is an ISO image"""
    try:
        vol_xml = volume.XMLDesc(0)
        root = ET.fromstring(vol_xml)
        format_elem = root.find(".//format")
        if format_elem is not None:
            return format_elem.get('type') == 'iso'
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

    index = 0
    while True:
        name = f"{device_prefix}{chr(ord('a') + index)}"
        if name not in existing:
            return name
        index += 1


def ensure_sata_controller(domain, dom_xml, is_running):
    """Ensure SATA controller exists for ISO attachments"""
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
    """Generate XML for disk attachment"""
    pool = volume.storagePoolLookupByVolume()
    pool_type = ET.fromstring(pool.XMLDesc(0)).get('type')

    if pool_type == 'logical':
        source_tag = f"<source dev='{volume.path()}'/>"
        disk_type = 'block'
    else:
        source_tag = f"<source volume='{volume.name()}' pool='{pool.name()}'/>"
        disk_type = 'volume'

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
            uri=dict(type='str', default='qemu:///system')
        ),
        supports_check_mode=True
    )

    if not HAS_LIBVIRT:
        module.fail_json(msg='libvirt-python is required for this module')

    libvirt_conn = LibvirtConnection(module)
    libvirt_conn.setup_connection_params(uri=module.params['uri'])

    try:
        success, conn = libvirt_conn.connect()
        if not success:
            module.fail_json(msg=f"Failed to connect to libvirt: {conn}")

        volume_utils = VolumeUtils(conn)
        domain_utils = DomainUtils(conn)

        if not domain_utils.domain_exists(module.params['name']):
            module.fail_json(msg=f"Domain {module.params['name']} not found")

        try:
            domain = conn.lookupByName(module.params['name'])
            is_running = domain.isActive()
            dom_xml = domain.XMLDesc(0)

            try:
                pool = conn.storagePoolLookupByName(module.params['pool'])
            except libvirt.libvirtError:
                module.fail_json(msg=f"Storage pool '{module.params['pool']}' not found")

            try:
                pool.refresh(0)
            except libvirt.libvirtError as e:
                module.warn(f"Failed to refresh pool: {str(e)}")

            result = {
                'changed': False,
                'attached_volumes': [],
                'already_attached': []
            }

            volumes_to_attach = []
            for volume_name in module.params['volumes']:
                try:
                    volume = pool.storageVolLookupByName(volume_name)
                    if is_volume_attached(dom_xml, volume.path()):
                        result['already_attached'].append(volume_name)
                        continue
                    volumes_to_attach.append(volume)
                except libvirt.libvirtError:
                    module.fail_json(msg=f"Volume '{volume_name}' not found in pool '{module.params['pool']}'")

            has_iso = any(is_iso_volume(vol) for vol in volumes_to_attach)
            if has_iso and not module.check_mode:
                changed = ensure_sata_controller(domain, dom_xml, is_running)
                if changed:
                    result['changed'] = True
                    dom_xml = domain.XMLDesc(0)

            for volume in volumes_to_attach:
                device_type = 'cdrom' if is_iso_volume(volume) else 'disk'
                device_prefix = 'sd' if device_type == 'cdrom' else 'vd'
                target_dev = get_next_target_dev(dom_xml, device_prefix)

                if not module.check_mode:
                    disk_xml, bus = generate_disk_xml(volume, target_dev, device_type)
                    attach_device(domain, disk_xml, is_running)
                    dom_xml = domain.XMLDesc(0)

                result['attached_volumes'].append({
                    'name': volume.name(),
                    'type': device_type,
                    'target': target_dev,
                    'bus': bus,
                    'persistent': True
                })
                result['changed'] = True

            if result['attached_volumes']:
                result['msg'] = f"Successfully attached {len(result['attached_volumes'])} volume(s)"
            elif result['already_attached']:
                result['msg'] = f"All volumes already attached"
            else:
                result['msg'] = "No volumes to attach"

            module.exit_json(**result)

        except libvirt.libvirtError as e:
            module.fail_json(msg=f"Error attaching volumes: {str(e)}")
        except Exception as e:
            module.fail_json(msg=f"Unexpected error: {str(e)}",
                             exception=traceback.format_exc())

    finally:
        libvirt_conn.close()


if __name__ == '__main__':
    main()