# ./plugins/modules/network/update_dhcp_reservation.py

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r"""
    name: update_dhcp_reservation
    author: n!-systems (claude sonnet 3.5) <ai-working-group@none.systems>
    version_added: "1.0.0"
    short_description: Update DHCP reservations in libvirt networks
    description:
        - Manages static DHCP host entries in libvirt networks
        - Can add or update MAC to IP address mappings
        - Works with both active and inactive networks
        - Updates both running and persistent configurations
        - Skips networks without DHCP with a warning
    options:
        network_name:
            description: Name of the libvirt network
            required: true
            type: str
        domain_name:
            description: Name of the domain (used for the host entry name)
            required: true
            type: str
        ip_address:
            description: IP address to reserve (can include CIDR notation)
            required: true
            type: str
        mac_address:
            description: MAC address to associate with the IP
            required: true
            type: str
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
        - Requires libvirt-python to be installed
        - Skips operation with warning if network does not have DHCP enabled
        - If IP is provided in CIDR notation, only the IP portion is used
    requirements:
        - "python >= 3.12"
        - "libvirt-python >= 10.9.0"
"""

EXAMPLES = r"""
- name: Set DHCP reservation
  nsys.libvirt.update_dhcp_reservation:
    network_name: default
    domain_name: test_vm
    ip_address: 192.168.122.10
    mac_address: "52:54:00:12:34:56"

- name: Update reservation with CIDR notation IP
  nsys.libvirt.update_dhcp_reservation:
    network_name: default
    domain_name: test_vm
    ip_address: 192.168.122.10/24
    mac_address: "52:54:00:12:34:56"

- name: Update reservation on remote host
  nsys.libvirt.update_dhcp_reservation:
    network_name: default
    domain_name: test_vm
    ip_address: 192.168.122.10
    mac_address: "52:54:00:12:34:56"
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
    description: Name of the network that was modified
    type: str
    returned: always
domain_name:
    description: Name of the domain the reservation was made for
    type: str
    returned: always
ip_address:
    description: Reserved IP address (without CIDR if provided)
    type: str
    returned: always
mac_address:
    description: MAC address for the reservation
    type: str
    returned: always
msg:
    description: Status message
    type: str
    returned: always
skipped:
    description: Whether the operation was skipped
    type: bool
    returned: always
warning:
    description: Warning message if operation was skipped
    type: str
    returned: when skipped
"""

import ipaddress
import xml.etree.ElementTree as ET
from typing import Dict, Optional, Tuple, Union

try:
    import libvirt
    HAS_LIBVIRT = True
except ImportError:
    HAS_LIBVIRT = False

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.nsys.libvirt.plugins.module_utils.common.libvirt_connection import LibvirtConnection


class DHCPReservationManager:
    """Helper class to manage DHCP reservations in libvirt networks"""

    def __init__(self, module: AnsibleModule, conn: libvirt.virConnect):
        self.module = module
        self.conn = conn

    def _strip_ip_cidr(self, ip_address: str) -> str:
        """
        Remove CIDR notation if present
        
        Args:
            ip_address: IP address potentially with CIDR
            
        Returns:
            str: IP address without CIDR
        """
        return ip_address.split('/')[0]

    def validate_ip_address(self, ip_address: str, network_xml: str) -> bool:
        """
        Validate that IP address is within network range
        
        Args:
            ip_address: IP address to validate (with or without CIDR)
            network_xml: Network XML definition
        
        Returns:
            bool: True if valid, False otherwise
        """
        try:
            root = ET.fromstring(network_xml)
            ip_elem = root.find(".//ip")
            if ip_elem is not None:
                network_addr = ip_elem.get("address")
                network_mask = ip_elem.get("netmask")
                if network_addr and network_mask:
                    network = ipaddress.IPv4Network(f"{network_addr}/{network_mask}", strict=False)
                    host_ip = ipaddress.IPv4Address(self._strip_ip_cidr(ip_address))
                    return host_ip in network
            return False
        except (ValueError, ET.ParseError):
            return False

    def has_dhcp_enabled(self, network_xml: str) -> bool:
        """
        Check if network has DHCP enabled
        
        Args:
            network_xml: Network XML definition
            
        Returns:
            bool: True if DHCP is enabled, False otherwise
        """
        try:
            root = ET.fromstring(network_xml)
            dhcp = root.find(".//dhcp")
            return dhcp is not None
        except ET.ParseError:
            return False

    def get_existing_host(self, network_xml: str, mac_address: str = None, 
                         ip_address: str = None) -> Optional[ET.Element]:
        """
        Find existing host entry by MAC or IP
        
        Args:
            network_xml: Network XML definition
            mac_address: MAC address to look for
            ip_address: IP address to look for (with or without CIDR)
            
        Returns:
            Element: Host element if found, None otherwise
        """
        try:
            root = ET.fromstring(network_xml)
            clean_ip = self._strip_ip_cidr(ip_address) if ip_address else None
            
            for host in root.findall(".//dhcp/host"):
                if mac_address and host.get("mac") == mac_address:
                    return host
                if clean_ip and host.get("ip") == clean_ip:
                    return host
            return None
        except ET.ParseError:
            return None

    def create_host_xml(self, domain_name: str, ip_address: str, 
                       mac_address: str) -> str:
        """
        Create XML for a DHCP host entry
        
        Args:
            domain_name: Domain name for the host entry
            ip_address: IP address to reserve (with or without CIDR)
            mac_address: MAC address to associate
            
        Returns:
            str: XML string for the host entry
        """
        clean_ip = self._strip_ip_cidr(ip_address)
        host = ET.Element("host")
        host.set("name", domain_name)
        host.set("ip", clean_ip)
        host.set("mac", mac_address)
        return ET.tostring(host, encoding='unicode')

    def update_reservation(self, network_name: str, domain_name: str,
                          ip_address: str, mac_address: str) -> Dict:
        """
        Update DHCP reservation in network
        
        Args:
            network_name: Name of the network
            domain_name: Domain name for host entry
            ip_address: IP address to reserve (with or without CIDR)
            mac_address: MAC address to associate
            
        Returns:
            dict: Result of the operation
        """
        result = {
            "changed": False,
            "skipped": False,
            "network_name": network_name,
            "domain_name": domain_name,
            "ip_address": self._strip_ip_cidr(ip_address),
            "mac_address": mac_address,
            "msg": ""
        }

        try:
            network = self.conn.networkLookupByName(network_name)
            network_xml = network.XMLDesc(0)

            # Check if DHCP is enabled
            if not self.has_dhcp_enabled(network_xml):
                result.update({
                    "skipped": True,
                    "warning": f"Network {network_name} does not have DHCP enabled - skipping DHCP reservation",
                    "msg": "Operation skipped - DHCP not enabled"
                })
                return result

            # Validate IP address
            if not self.validate_ip_address(ip_address, network_xml):
                self.module.fail_json(
                    msg=f"IP address {self._strip_ip_cidr(ip_address)} is not within network range"
                )

            # Check for existing entry
            existing_host = self.get_existing_host(network_xml, mac_address, ip_address)
            
            if existing_host is not None:
                # Check if update needed
                if (existing_host.get("mac") == mac_address and 
                    existing_host.get("ip") == self._strip_ip_cidr(ip_address) and
                    existing_host.get("name") == domain_name):
                    result["msg"] = "DHCP reservation already up to date"
                    return result
                
                # Update existing entry
                command = libvirt.VIR_NETWORK_UPDATE_COMMAND_MODIFY
            else:
                # Add new entry
                command = libvirt.VIR_NETWORK_UPDATE_COMMAND_ADD_LAST

            if not self.module.check_mode:
                # Create host XML
                host_xml = self.create_host_xml(domain_name, ip_address, mac_address)

                # Apply changes to both running and persistent config
                flags = libvirt.VIR_NETWORK_UPDATE_AFFECT_CONFIG
                if network.isActive():
                    flags |= libvirt.VIR_NETWORK_UPDATE_AFFECT_LIVE

                network.update(
                    command,
                    libvirt.VIR_NETWORK_SECTION_IP_DHCP_HOST,
                    -1,
                    host_xml,
                    flags
                )

            result["changed"] = True
            result["msg"] = "DHCP reservation updated"
            return result

        except libvirt.libvirtError as e:
            self.module.fail_json(msg=f"Failed to update DHCP reservation: {str(e)}")


def main():
    module = AnsibleModule(
        argument_spec=dict(
            network_name=dict(type='str', required=True),
            domain_name=dict(type='str', required=True),
            ip_address=dict(type='str', required=True),
            mac_address=dict(type='str', required=True),
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

        reservation_manager = DHCPReservationManager(module, conn)
        result = reservation_manager.update_reservation(
            module.params['network_name'],
            module.params['domain_name'],
            module.params['ip_address'],
            module.params['mac_address']
        )

        if result.get("warning"):
            module.warn(result["warning"])

        module.exit_json(**result)

    finally:
        libvirt_conn.close()


if __name__ == '__main__':
    main()
