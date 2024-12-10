# ./plugins/modules/network/attachpy
# nsys-ai-claude-3.5

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
        - The network will be attached with specified or default parameters
        - Will not create duplicate interfaces if network is already attached
        - Works with both running and stopped domains
        - For running domains, applies changes both to live system and persistent config
        - For stopped domains, only updates the persistent config
        - Optionally allows setting custom MAC address for the interface

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
        mac_address:
            description: 
                - Optional MAC address for the network interface
                - Must be a valid MAC address in the format "XX:XX:XX:XX:XX:XX"
                - If not provided, libvirt will generate one automatically
            required: false
            type: str
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
        - "libvirt-python >= 10.9.0"
"""

EXAMPLES = r"""
    # Attach network 'default' to domain 'testvm1' on local system
    - name: Attach network to domain
      nsys.libvirt.attach_network:
        network_name: default
        domain_name: testvm1

    # Attach network with custom MAC address
    - name: Attach network with specific MAC
      nsys.libvirt.attach_network:
        network_name: default
        domain_name: testvm1
        mac_address: "52:54:00:12:34:56"

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
    mac_address:
        description: MAC address of the attached interface
        type: str
        returned: success
"""

import re
import xml.etree.ElementTree as ElementTree
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.nsys.libvirt.plugins.module_utils.common.libvirt_connection import LibvirtConnection

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
        self.mac_address = module.params.get('mac_address')

    def validate_mac_address(self, mac_address):
        """
        Validate MAC address format

        Args:
            mac_address: MAC address string

        Returns:
            bool: True if valid, False otherwise
        """
        if not mac_address:
            return True

        mac_pattern = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$')
        return bool(mac_pattern.match(mac_address))

    def validate_requirements(self):
        """
        Validate that required network and domain exist and MAC address format if provided
        Returns tuple of (network, domain) objects
        """
        if self.mac_address and not self.validate_mac_address(self.mac_address):
            self.module.fail_json(msg=f"Invalid MAC address format: {self.mac_address}")

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
        """
        Check if network is already attached to domain
        Returns tuple of (bool, str) where str is existing MAC if found
        """
        try:
            domain_xml = domain.XMLDesc(0)
            root = ElementTree.fromstring(domain_xml)

            for interface in root.findall(".//interface[@type='network']"):
                source = interface.find("source")
                if source is not None and source.get('network') == self.network_name:
                    mac = interface.find("mac")
                    return True, mac.get('address') if mac is not None else None
            return False, None
        except (libvirt.libvirtError, ElementTree.ParseError) as e:
            self.module.fail_json(msg=f"Failed to check network attachment: {str(e)}")

    def attach_network(self, domain, network, is_running):
        """
        Attach network to domain
        Returns MAC address of attached interface
        """
        interface_xml = f"""
        <interface type='network'>
            <source network='{network.name()}'/>
            <model type='virtio'/>
            <link state='{"up" if self.connected else "down"}'/>
            {f"<mac address='{self.mac_address}'/>" if self.mac_address else ""}
        </interface>
        """

        try:
            flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
            if is_running:
                flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE

            domain.attachDeviceFlags(interface_xml.strip(), flags)

            # Re-read domain XML to get generated MAC if none was specified
            if not self.mac_address:
                domain_xml = domain.XMLDesc(0)
                root = ElementTree.fromstring(domain_xml)
                for interface in root.findall(".//interface[@type='network']"):
                    source = interface.find("source")
                    if source is not None and source.get('network') == self.network_name:
                        mac = interface.find("mac")
                        if mac is not None:
                            return mac.get('address')

            return self.mac_address

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

        is_attached, existing_mac = self.is_network_attached(domain)
        if is_attached:
            result['already_attached'] = True
            result['mac_address'] = existing_mac
            # If MAC address specified and different from existing, fail
            if self.mac_address and self.mac_address != existing_mac:
                self.module.fail_json(
                    msg=f"Network already attached with different MAC address: {existing_mac}"
                )
            return result

        if not self.module.check_mode:
            mac_address = self.attach_network(domain, network, result['domain_running'])
            result['mac_address'] = mac_address

        result['changed'] = True
        return result


def main():
    module_args = dict(
        network_name=dict(type='str', required=True),
        domain_name=dict(type='str', required=True),
        connected=dict(type='bool', required=False, default=True),
        mac_address=dict(type='str', required=False),
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