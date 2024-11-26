# ./plugins/modules/refresh_resources.py
# nsys-ai-claude-3.5

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r'''
---
module: refresh_resources
short_description: Refresh libvirt resources to ensure up-to-date state
description:
  - Forces a refresh of libvirt resources to ensure the daemon has current information
  - Useful when resources may have been modified outside of libvirt's knowledge
  - Can refresh domains, networks, and storage pools
options:
  resource:
    description:
      - Type of resource to refresh
      - For domains, rescans for changes in domain definitions and states
      - For networks, refreshes network state and interface information
      - For storage pools, rescans storage pool contents
    required: true
    choices: [ 'domain', 'network', 'storage_pool' ]
    type: str
  name:
    description:
      - Name of the specific resource to refresh
      - If not provided, refreshes all resources of the specified type
    required: false
    type: str
  uri:
    description:
      - libvirt connection URI
    type: str
    default: qemu:///system
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
- name: Refresh all storage pools
  nsys.libvirt.refresh_resources:
    resource: storage_pool

- name: Refresh specific network
  nsys.libvirt.refresh_resources:
    resource: network
    name: default

- name: Refresh all domains on remote host
  nsys.libvirt.refresh_resources:
    resource: domain
    remote_host: libvirt1.example.com
    auth_user: admin
    auth_password: secret
'''

RETURN = r'''
changed:
    description: Whether any resources were refreshed
    type: bool
    returned: always
msg:
    description: Status message
    type: str
    returned: always
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
from ansible_collections.nsys.libvirt.plugins.module_utils.network_utils import NetworkUtils
from ansible_collections.nsys.libvirt.plugins.module_utils.volume_utils import VolumeUtils


def main():
    module = AnsibleModule(
        argument_spec=dict(
            resource=dict(type='str', required=True, 
                         choices=['domain', 'network', 'storage_pool']),
            name=dict(type='str', required=False),
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

        resource_type = module.params['resource']
        resource_name = module.params['name']

        if module.check_mode:
            module.exit_json(changed=True, 
                           msg=f"Would refresh {resource_type}" + 
                               (f" {resource_name}" if resource_name else "s"))

        success = False
        message = ""

        if resource_type == 'domain':
            domain_utils = DomainUtils(conn)
            success, message = domain_utils.refresh_domain(resource_name)
        elif resource_type == 'network':
            network_utils = NetworkUtils(conn)
            success, message = network_utils.refresh_network(resource_name)
        elif resource_type == 'storage_pool':
            volume_utils = VolumeUtils(conn)
            success, message = volume_utils.refresh_storage_pool(resource_name)

        if success:
            module.exit_json(changed=True, msg=message)
        else:
            module.fail_json(msg=message)

    except Exception as e:
        module.fail_json(msg=f"Unexpected error: {str(e)}", 
                        exception=traceback.format_exc())
    finally:
        libvirt_conn.close()


if __name__ == '__main__':
    main()
