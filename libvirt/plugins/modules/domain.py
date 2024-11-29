# ./plugins/modules/domain.py
# nsys-ai-claude-3.5

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r'''
---
module: domain
short_description: Manage libvirt domains
description:
  - Create or remove libvirt domains
  - Basic domain configuration without disks or networks
  - Those should be attached using separate modules
options:
  name:
    description:
      - Name of the domain
    required: true
    type: str
  vcpu:
    description:
      - Number of virtual CPUs
    type: int
    default: 1
  memory:
    description:
      - Memory in MB
    type: int
    default: 512
  state:
    description:
      - State of the domain
    type: str
    choices: [ 'present', 'absent' ]
    default: 'present'
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
- name: Create a domain
  nsys.libvirt.domain:
    name: test-vm
    vcpu: 2
    memory: 2048
    state: present

- name: Remove a domain
  nsys.libvirt.domain:
    name: test-vm
    state: absent

- name: Create a domain on remote host
  nsys.libvirt.domain:
    name: test-vm
    vcpu: 4
    memory: 4096
    remote_host: libvirt1.example.com
    auth_user: admin
    auth_password: secret
'''

RETURN = r'''
changed:
    description: Whether any changes were made
    type: bool
    returned: always
domain_info:
    description: Information about the domain after operation
    type: dict
    returned: when state is present
    contains:
        name:
            description: Domain name
            type: str
        uuid:
            description: Domain UUID
            type: str
        vcpu:
            description: Number of virtual CPUs
            type: int
        memory:
            description: Memory in MB
            type: int
msg:
    description: Status message
    type: str
    returned: always
'''
import time
import os
import traceback
import uuid
import xml.etree.ElementTree as ET

try:
    import libvirt
    HAS_LIBVIRT = True
except ImportError:
    HAS_LIBVIRT = False

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.nsys.libvirt.plugins.module_utils.libvirt_connection import LibvirtConnection
from ansible_collections.nsys.libvirt.plugins.module_utils.domain_utils import DomainUtils


def generate_domain_xml(name, vcpu, memory_mb):
    """Generate domain XML configuration"""
    domain = ET.Element('domain', type='kvm')

    name_elem = ET.SubElement(domain, 'name')
    name_elem.text = name

    uuid_elem = ET.SubElement(domain, 'uuid')
    uuid_elem.text = str(uuid.uuid4())

    memory_elem = ET.SubElement(domain, 'memory', unit='MiB')
    memory_elem.text = str(memory_mb)

    currentMemory_elem = ET.SubElement(domain, 'currentMemory', unit='MiB')
    currentMemory_elem.text = str(memory_mb)

    vcpu_elem = ET.SubElement(domain, 'vcpu', placement='static')
    vcpu_elem.text = str(vcpu)

    # OS configuration with EFI
    os = ET.SubElement(domain, 'os')
    type_elem = ET.SubElement(os, 'type', arch='x86_64', machine='pc-q35-7.2')
    type_elem.text = 'hvm'
    ET.SubElement(os, 'loader', readonly='yes', type='pflash',
                  secure='yes').text = '/usr/share/edk2/x64/OVMF_CODE.secboot.4m.fd'
    ET.SubElement(os, 'nvram').text = '/var/lib/libvirt/qemu/nvram/' + name + '_VARS.fd'

    # Basic features
    features = ET.SubElement(domain, 'features')
    ET.SubElement(features, 'acpi')
    ET.SubElement(features, 'apic')
    ET.SubElement(features, 'smm', state='on')  # Required for secure boot

    # Clock configuration
    clock = ET.SubElement(domain, 'clock', offset='utc')
    ET.SubElement(clock, 'timer', name='rtc', tickpolicy='catchup')
    ET.SubElement(clock, 'timer', name='pit', tickpolicy='delay')
    ET.SubElement(clock, 'timer', name='hpet', present='no')

    # Device configuration
    devices = ET.SubElement(domain, 'devices')

    # Basic device configuration
    ET.SubElement(devices, 'emulator').text = '/usr/bin/qemu-system-x86_64'

    # Console and serial devices
    console = ET.SubElement(devices, 'console', type='pty')
    ET.SubElement(console, 'target', type='serial', port='0')

    # Graphics device
    graphics = ET.SubElement(devices, 'graphics', type='spice', autoport='yes')
    ET.SubElement(graphics, 'listen', type='address')
    ET.SubElement(graphics, 'image', compression='off')
    ET.SubElement(graphics, 'gl', enable='no')

    # Video device
    video = ET.SubElement(devices, 'video')
    model = ET.SubElement(video, 'model', type='cirrus', vram='16384', heads='1', primary='yes')
    address = ET.SubElement(video, 'address', type='pci', domain='0x0000', bus='0x07', slot='0x01', function='0x0')

    return ET.tostring(domain, encoding='unicode')

def create_domain(module, domain_utils, name, vcpu, memory):
    """Create a new domain"""
    try:
        if domain_utils.domain_exists(name):
            return False, "Domain already exists", domain_utils.get_domain_info(name)
            
        xml = generate_domain_xml(name, vcpu, memory)
        domain = domain_utils.conn.defineXML(xml)
        
        if domain is None:
            module.fail_json(msg="Failed to define the domain")
            
        return True, "Domain created successfully", domain_utils.get_domain_info(name)
        
    except libvirt.libvirtError as e:
        module.fail_json(msg=f"Error creating domain: {str(e)}")


def remove_domain(module, domain_utils, name):
    """Remove an existing domain and all associated resources"""
    try:
        if not domain_utils.domain_exists(name):
            return False, "Domain does not exist", None

        domain = domain_utils.conn.lookupByName(name)

        # Force shutdown if running
        if domain.isActive():
            try:
                # Try graceful shutdown first
                domain.shutdown()
                # Wait for up to 30 seconds for shutdown
                for _ in range(30):
                    if not domain.isActive():
                        break
                    time.sleep(1)
                # Force if still running
                if domain.isActive():
                    domain.destroy()
            except libvirt.libvirtError:
                # If shutdown fails, go straight to destroy
                domain.destroy()

        try:
            # Remove managed save state if exists
            if domain.hasManagedSaveImage():
                domain.managedSaveRemove()
        except libvirt.libvirtError as e:
            module.warn(f"Failed to remove managed save: {str(e)}")

        # Combine all undefine flags
        undefine_flags = (
                libvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE |  # Remove managed save state
                libvirt.VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA |  # Remove snapshot metadata
                libvirt.VIR_DOMAIN_UNDEFINE_NVRAM |  # Remove NVRAM file
                libvirt.VIR_DOMAIN_UNDEFINE_CHECKPOINTS_METADATA  # Remove checkpoint metadata
        )

        try:
            domain.undefineFlags(undefine_flags)
        except libvirt.libvirtError:
            # Fallback to basic undefine if flags not supported
            module.warn("Advanced undefine flags not supported, falling back to basic undefine")
            try:
                domain.undefine()
            except libvirt.libvirtError as e:
                module.fail_json(msg=f"Failed to undefine domain: {str(e)}")

        # Extra cleanup for NVRAM file
        try:
            nvram_path = f"/var/lib/libvirt/qemu/nvram/{name}_VARS.fd"
            if os.path.exists(nvram_path):
                os.remove(nvram_path)
        except (OSError, IOError) as e:
            module.warn(f"Failed to remove NVRAM file: {str(e)}")

        return True, "Domain and all associated resources removed successfully", None

    except libvirt.libvirtError as e:
        module.fail_json(msg=f"Error removing domain: {str(e)}")


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
            vcpu=dict(type='int', default=1),
            memory=dict(type='int', default=512),
            state=dict(type='str', choices=['present', 'absent'], default='present'),
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

        # Initialize domain utilities
        domain_utils = DomainUtils(conn)

        name = module.params['name']
        vcpu = module.params['vcpu']
        memory = module.params['memory']
        state = module.params['state']

        result = {
            'changed': False,
            'msg': '',
            'domain_info': None
        }

        try:
            if state == 'present':
                if not module.check_mode:
                    changed, message, domain_info = create_domain(module, domain_utils, name, vcpu, memory)
                    result['changed'] = changed
                    result['msg'] = message
                    result['domain_info'] = domain_info
                else:
                    result['changed'] = not domain_utils.domain_exists(name)
                    result['msg'] = "Would create domain (check mode)"
                    
            else:  # state == 'absent'
                if not module.check_mode:
                    changed, message, _ = remove_domain(module, domain_utils, name)
                    result['changed'] = changed
                    result['msg'] = message
                else:
                    result['changed'] = domain_utils.domain_exists(name)
                    result['msg'] = "Would remove domain (check mode)"

            module.exit_json(**result)

        except Exception as e:
            module.fail_json(msg=f"Unexpected error: {str(e)}", exception=traceback.format_exc())

    finally:
        libvirt_conn.close()


if __name__ == '__main__':
    main()
