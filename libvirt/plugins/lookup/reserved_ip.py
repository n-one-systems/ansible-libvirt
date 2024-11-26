# ./plugins/lookup/reserved_ip.py
# nsys-ai-claude-3.5

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r"""
    name: reserved_ip
    author: n!-systems (claude sonnet 3.5) <ai-working-group@none.systems>
    version_added: "1.0.0"
    short_description: Get reserved IP address for a domain in a network
    description:
        - Returns the reserved IP address for a domain in a specified network
        - Looks up the domain's MAC address and matches it against network DHCP reservations
        - Returns None if no reservation is found
    options:
        _terms:
            description: List of strings in format "domain_name/network_name"
            required: True
        uri:
            description: libvirt connection URI
            type: str
            default: qemu:///system
        remote_host:
            description: Remote host to connect to
            type: str
            required: false
        auth_user:
            description: Username for authentication if required
            type: str
            required: false
        auth_password:
            description: Password for authentication if required
            type: str
            required: false
            no_log: true
    notes:
        - Requires libvirt-python to be installed on the control node
    requirements:
        - "python >= 3.12"
        - "libvirt-python >= 5.6.0"
"""

EXAMPLES = r"""
# Get reserved IP for a domain in a network
- name: Get domain's reserved IP
  debug:
    msg: "{{ lookup('nsys.libvirt.reserved_ip', 'myVM/default') }}"

# Get multiple reservations
- name: Get multiple domain IPs
  debug:
    msg: "{{ lookup('nsys.libvirt.reserved_ip', 'vm1/net1', 'vm2/net1') }}"

# Get reservation from remote host
- name: Get domain IP from remote host
  debug:
    msg: "{{ lookup('nsys.libvirt.reserved_ip', 'myVM/default', 
             remote_host='libvirt1.example.com', 
             auth_user='admin', 
             auth_password='secret') }}"
"""

RETURN = r"""
_raw:
    description: List of IP addresses or None values for each domain/network pair
    type: list
    elements: str
"""

import xml.etree.ElementTree as ET
from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase
from ansible.utils.display import Display
from ansible_collections.nsys.libvirt.plugins.module_utils.libvirt_connection import LibvirtConnection

try:
    import libvirt
    HAS_LIBVIRT = True
except ImportError:
    HAS_LIBVIRT = False

display = Display()

class LookupModule(LookupBase):

    def get_vm_mac_address(self, domain, network_name):
        """Get MAC address of domain's interface in specified network"""
        try:
            # Get domain XML and parse it
            domain_xml = domain.XMLDesc()
            root = ET.fromstring(domain_xml)

            # Find interface connected to specified network
            for interface in root.findall(".//interface"):
                source = interface.find("source")
                if source is not None and source.get("network") == network_name:
                    mac = interface.find("mac")
                    if mac is not None:
                        return mac.get("address")
            return None

        except libvirt.libvirtError as e:
            raise AnsibleError(f"Error getting domain XML: {str(e)}")
        except ET.ParseError:
            raise AnsibleError("Failed to parse domain XML")

    def get_reserved_ip(self, network, mac_address):
        """Get reserved IP address for MAC address in network"""
        try:
            # Get network XML and parse it
            network_xml = network.XMLDesc()
            root = ET.fromstring(network_xml)

            # Look for DHCP host entries with matching MAC
            for host in root.findall(".//dhcp/host"):
                if host.get("mac") == mac_address:
                    return host.get("ip")
            return None

        except libvirt.libvirtError as e:
            raise AnsibleError(f"Error getting network XML: {str(e)}")
        except ET.ParseError:
            raise AnsibleError("Failed to parse network XML")

    def run(self, terms, variables=None, **kwargs):
        if not HAS_LIBVIRT:
            raise AnsibleError("libvirt-python is required for reserved_ip lookup")

        if not terms:
            raise AnsibleError("At least one domain/network pair must be specified")

        # Process options
        self.set_options(var_options=variables, direct=kwargs)

        # Initialize connection handler
        libvirt_conn = LibvirtConnection(self._templar.available_variables.get('ansible_module', None))

        # Setup connection parameters
        libvirt_conn.setup_connection_params(
            uri=self.get_option('uri'),
            auth_user=self.get_option('auth_user'),
            auth_password=self.get_option('auth_password'),
            remote_host=self.get_option('remote_host')
        )

        ret = []

        try:
            # Establish connection
            success, conn = libvirt_conn.connect()
            if not success:
                raise AnsibleError(f"Failed to connect to libvirt: {conn}")

            try:
                for term in terms:
                    # Parse domain/network names
                    try:
                        domain_name, network_name = term.split('/')
                    except ValueError:
                        raise AnsibleError(f"Invalid format for {term}. Use 'domain_name/network_name'")

                    try:
                        # Look up domain and network
                        domain = conn.lookupByName(domain_name)
                        network = conn.networkLookupByName(network_name)

                        # Get MAC address for domain's interface in this network
                        mac_address = self.get_vm_mac_address(domain, network_name)
                        if not mac_address:
                            display.vvv(f"No interface found for network {network_name} in domain {domain_name}")
                            ret.append(None)
                            continue

                        # Get reserved IP for this MAC
                        ip_address = self.get_reserved_ip(network, mac_address)
                        ret.append(ip_address)

                    except libvirt.libvirtError as e:
                        display.vvv(f"Error looking up domain or network: {str(e)}")
                        ret.append(None)

            finally:
                libvirt_conn.close()

            return ret

        except Exception as e:
            raise AnsibleError(f"Error in reserved_ip lookup: {str(e)}")
