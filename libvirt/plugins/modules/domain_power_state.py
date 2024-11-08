# ./plugins/modules/domain_power_state.py
# nsys-ai-claude-3.5

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: domain_power_state
short_description: Manage libvirt domain power states
description:
    - Control power state of libvirt domains (VMs)
    - Supports graceful and forced shutdown, reboot, and start operations
options:
    name:
        description: Name of the domain
        required: true
        type: str
    state:
        description: Desired power state
        choices: [ 'poweroff', 'reboot', 'running' ]
        required: true
        type: str
    force:
        description: Whether to force the operation
        type: bool
        default: false
    uri:
        description: libvirt connection URI
        type: str
        default: qemu:///system
requirements:
    - "python >= 3.12"
    - "libvirt-python >= 5.6.0"
author:
    - "N-One Systems (AI) (@n-one-systems)"
'''

EXAMPLES = r'''
- name: Gracefully shutdown a domain
  nsys.libvirt.domain_power_state:
    name: test_vm
    state: poweroff
    force: false

- name: Force shutdown a domain
  nsys.libvirt.domain_power_state:
    name: test_vm
    state: poweroff
    force: true

- name: Reboot a domain
  nsys.libvirt.domain_power_state:
    name: test_vm
    state: reboot
    force: false

- name: Start a domain
  nsys.libvirt.domain_power_state:
    name: test_vm
    state: running
'''

import traceback

try:
    import libvirt
    HAS_LIBVIRT = True
except ImportError:
    HAS_LIBVIRT = False

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.nsys.libvirt.plugins.module_utils.libvirt_connection import LibvirtConnection
from ansible_collections.nsys.libvirt.plugins.module_utils.domain_utils import DomainUtils

def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
            state=dict(type='str', required=True, choices=['poweroff', 'reboot', 'running']),
            force=dict(type='bool', default=False),
            uri=dict(type='str', default='qemu:///system')
        ),
        supports_check_mode=True
    )

    if not HAS_LIBVIRT:
        module.fail_json(msg='libvirt-python is required for this module')

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

        domain_utils = DomainUtils(conn)
        
        if not domain_utils.domain_exists(module.params['name']):
            module.fail_json(msg=f"Domain {module.params['name']} does not exist")

        result = domain_utils.manage_power_state(
            module.params['name'],
            module.params['state'],
            module.params['force']
        )

        module.exit_json(**result)

    except Exception as e:
        module.fail_json(msg=f"Unexpected error: {str(e)}", exception=traceback.format_exc())
    finally:
        libvirt_conn.close()

if __name__ == '__main__':
    main()
