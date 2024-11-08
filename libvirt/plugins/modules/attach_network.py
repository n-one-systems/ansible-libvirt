# ./plugins/modules/attach_network.py
# nsys-ai-claude-3.5

# !/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2024, nsys.ai
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import (absolute_import, division, print_function)

__metaclass__ = type

DOCUMENTATION = r"""
    name: attach_network
    author: n!-systems (claude sonnet 3.5) <ai-working-group@none.systems>
    version_added: "1.0.0"
    short_description: Attach a libvirt network to a domain

    description:
        - Attach an existing libvirt network to an existing domain
        - Both network and domain must exist
        - The network will be attached with default parameters
        - Will not create duplicate interfaces if network is already attached
        - Works with both running and stopped domains
        - For running domains, applies changes both to live system and persistent config
        - For stopped domains, only updates the persistent config

    options:
        network_name:
            description: Name of the libvirt network to attach
            required: true
            type: str
        domain_name:
            description: Name of the domain to attach the network to
            required: true
            type: str
        connected:
            description: Whether the network interface should be connected
            required: false
            type: bool
            default: true
        uri:
            description: 
                - libvirt connection uri
                - defaults to qemu:///system
            required: false
            type: str
        remote_host:
            description: Remote host to connect to
            required: false
            type: str
        auth_user:
            description: Username for authentication if required
            required: false
            type: str
        auth_password:
            description: Password for authentication if required
            required: false
            type: str
            no_log: true

    requirements:
        - "python >= 3.12"
        - "libvirt-python >= 5.6.0"
"""

EXAMPLES = r"""
    # Attach network 'default' to domain 'testvm1' on local system
    - name: Attach network to domain
      nsys.libvirt.attach_network:
        network_name: default
        domain_name: testvm1

    # Attach network but leave it disconnected
    - name: Attach disconnected network interface
      nsys.libvirt.attach_network:
        network_name: default
        domain_name: testvm1
        connected: false

    # Attach network on remote system with authentication
    - name: Attach network to domain on remote host
      nsys.libvirt.attach_network:
        network_name: default
        domain_name: testvm1
        remote_host: libvirt1.example.com
        auth_user: admin
        auth_password: secret
"""

RETURN = r"""
    changed:
        description: Whether any changes were made
        type: bool
        returned: always
    network_name:
        description: Name of the network that was attached
        type: str
        returned: always
    domain_name:
        description: Name of the domain the network was attached to
        type: str
        returned: always
    already_attached:
        description: Whether the network was already attached to the domain
        type: bool
        returned: always
    domain_running:
        description: Whether the domain was running when the network was attached
        type: bool
        returned: always
"""

import xml.etree.ElementTree as ElementTree
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.nsys.libvirt.plugins.module_utils.libvirt_connection import LibvirtConnection

try:
    import libvirt
    HAS_LIBVIRT = True
except ImportError:
    HAS_LIBVIRT = False


class NetworkAttacher:
    """
    Helper class to manage network attachment operations
    """

    def __init__(self, module, conn):
        self.module = module
        self.conn = conn
        self.network_name = module.params['network_name']
        self.domain_name = module.params['domain_name']
        self.connected = module.params['connected']

    def validate_requirements(self):
        """
        Validate that required network and domain exist
        Returns tuple of (network, domain) objects
        """
        try:
            network = self.conn.networkLookupByName(self.network_name)
            domain = self.conn.lookupByName(self.domain_name)
            return network, domain
        except libvirt.libvirtError as e:
            self.module.fail_json(msg=f"Failed to find network or domain: {str(e)}")

    def is_domain_running(self, domain):
        """Check if domain is running"""
        try:
            state, _ = domain.state()
            return state == libvirt.VIR_DOMAIN_RUNNING
        except libvirt.libvirtError as e:
            self.module.fail_json(msg=f"Failed to get domain state: {str(e)}")

    def is_network_attached(self, domain):
        """Check if network is already attached to domain"""
        try:
            domain_xml = domain.XMLDesc(0)
            root = ElementTree.fromstring(domain_xml)

            for interface in root.findall(".//interface[@type='network']"):
                source = interface.find("source")
                if source is not None and source.get('network') == self.network_name:
                    return True
            return False
        except (libvirt.libvirtError, ElementTree.ParseError) as e:
            self.module.fail_json(msg=f"Failed to check network attachment: {str(e)}")

    def attach_network(self, domain, network, is_running):
        """Attach network to domain"""
        interface_xml = f"""
        <interface type='network'>
            <source network='{network.name()}'/>
            <model type='virtio'/>
            <link state='{"up" if self.connected else "down"}'/>
        </interface>
        """

        try:
            flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
            if is_running:
                flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE

            domain.attachDeviceFlags(interface_xml.strip(), flags)
            return True
        except libvirt.libvirtError as e:
            self.module.fail_json(msg=f"Failed to attach network: {str(e)}")

    def run(self):
        """
        Main execution flow
        """
        result = {
            'changed': False,
            'network_name': self.network_name,
            'domain_name': self.domain_name,
            'already_attached': False,
            'domain_running': False
        }

        network, domain = self.validate_requirements()
        result['domain_running'] = self.is_domain_running(domain)

        if self.is_network_attached(domain):
            result['already_attached'] = True
            return result

        if not self.module.check_mode:
            self.attach_network(domain, network, result['domain_running'])

        result['changed'] = True
        return result


def main():
    module_args = dict(
        network_name=dict(type='str', required=True),
        domain_name=dict(type='str', required=True),
        connected=dict(type='bool', required=False, default=True),
        uri=dict(type='str', required=False),
        remote_host=dict(type='str', required=False),
        auth_user=dict(type='str', required=False),
        auth_password=dict(type='str', required=False, no_log=True)
    )

    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True
    )

    if not HAS_LIBVIRT:
        module.fail_json(msg='libvirt-python is required for this module')

    # Initialize and setup connection
    libvirt_conn = LibvirtConnection(module)
    libvirt_conn.setup_connection_params(
        uri=module.params.get('uri'),
        auth_user=module.params.get('auth_user'),
        auth_password=module.params.get('auth_password'),
        remote_host=module.params.get('remote_host')
    )

    # Establish connection
    success, conn = libvirt_conn.connect()
    if not success:
        module.fail_json(msg=f"Failed to connect to libvirt: {conn}")

    try:
        attacher = NetworkAttacher(module, conn)
        result = attacher.run()
        module.exit_json(**result)
    finally:
        libvirt_conn.close()


if __name__ == '__main__':
    main()
