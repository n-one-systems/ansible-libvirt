# ./plugins/modules/network.py
# nsys-ai-claude-3.5

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r'''
---
module: network
short_description: Manage libvirt networks
description:
  - Create, delete, and manage libvirt networks
  - Configure network properties including type, IP addressing, and DHCP
  - Manage network state (active/inactive) and autostart behavior
  - Support for NAT, routed, and isolated network types
options:
  name:
    description:
      - Name of the network
    required: true
    type: str
  state:
    description:
      - State of the network
      - If absent, the network will be removed if it exists
      - If present, the network will be created if it doesn't exist
      - If active or inactive, the network will be enabled/disabled
    choices: [ 'present', 'absent', 'active', 'inactive' ]
    default: present
    type: str
  type:
    description:
      - Type of the network
      - nat provides outbound connectivity through NAT
      - routed provides outbound connectivity through routing
      - isolated provides no outbound connectivity
    choices: [ 'nat', 'routed', 'isolated' ]
    default: nat
    type: str
  bridge:
    description:
      - Name of the bridge device to create
      - If not specified, libvirt will generate one
    type: str
  cidr:
    description:
      - Network address in CIDR notation (e.g., 192.168.122.0/24)
      - Required when state is present
    type: str
  dhcp:
    description:
      - DHCP configuration for the network
    type: dict
    suboptions:
      enabled:
        description:
          - Whether to enable DHCP
        type: bool
        default: true
      start:
        description:
          - Start of DHCP range
        type: str
      end:
        description:
          - End of DHCP range
        type: str
  dns:
    description:
      - DNS configuration for the network
    type: dict
    suboptions:
      enabled:
        description:
          - Whether to enable DNS
        type: bool
        default: true
      forwarders:
        description:
          - List of DNS forwarders
        type: list
        elements: str
      hosts:
        description:
          - List of static DNS host entries
        type: list
        elements: dict
        suboptions:
          ip:
            description:
              - IP address for the host
            type: str
          hostnames:
            description:
              - List of hostnames for the IP
            type: list
            elements: str
  domain:
    description:
      - DNS domain name for the network
    type: str
  autostart:
    description:
      - Whether the network should start automatically on boot
    type: bool
    default: true
  mtu:
    description:
      - MTU size for the network bridge
    type: int
  delay:
    description:
      - Bridge forward delay in seconds
    type: int
    default: 0
  stp:
    description:
      - Whether to enable STP protocol on the bridge
    type: bool
    default: true
  uri:
    description:
      - libvirt connection uri
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
# Create a NAT network with DHCP
- name: Create NAT network
  nsys.libvirt.network:
    name: natnet
    cidr: 192.168.100.0/24
    dhcp:
      enabled: true
      start: 192.168.100.128
      end: 192.168.100.254

# Create a routed network
- name: Create routed network
  nsys.libvirt.network:
    name: routednet
    type: routed
    cidr: 192.168.200.0/24
    bridge: routedbr0
    autostart: true

# Create an isolated network with custom DNS
- name: Create isolated network
  nsys.libvirt.network:
    name: isolated
    type: isolated
    cidr: 192.168.150.0/24
    dns:
      enabled: true
      forwarders:
        - 8.8.8.8
        - 8.8.4.4
      hosts:
        - ip: 192.168.150.10
          hostnames:
            - host1.example.com
            - host1

# Remove a network
- name: Remove network
  nsys.libvirt.network:
    name: mynet
    state: absent

# Create network on remote host
- name: Create remote network
  nsys.libvirt.network:
    name: remotenet
    cidr: 192.168.111.0/24
    remote_host: libvirt1.example.com
    auth_user: admin
    auth_password: secret
'''

RETURN = r'''
changed:
    description: Whether any changes were made
    type: bool
    returned: always
network:
    description: Network information
    type: dict
    returned: always
    contains:
        name:
            description: Network name
            type: str
        uuid:
            description: Network UUID
            type: str
        bridge:
            description: Bridge device name
            type: str
        state:
            description: Network state (active/inactive)
            type: str
        autostart:
            description: Whether network autostarts
            type: bool
        persistent:
            description: Whether network is persistent
            type: bool
        cidr:
            description: Network CIDR
            type: str
        type:
            description: Network type (nat/route/isolated)
            type: str
        dhcp:
            description: DHCP configuration
            type: dict
        dns:
            description: DNS configuration
            type: dict
msg:
    description: Status message
    type: str
    returned: always
'''

import ipaddress
import traceback
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple, Union

try:
    import libvirt
    HAS_LIBVIRT = True
except ImportError:
    HAS_LIBVIRT = False

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.nsys.libvirt.plugins.module_utils.libvirt_connection import LibvirtConnection
from ansible_collections.nsys.libvirt.plugins.module_utils.network_utils import NetworkUtils

class NetworkManager:
    """Helper class to manage libvirt network operations"""

    def __init__(self, module: AnsibleModule, conn: libvirt.virConnect):
        self.module = module
        self.conn = conn
        self.network_utils = NetworkUtils(conn)
        self.params = module.params
        self.changed = False
        self.network_info = {}

    def generate_network_xml(self) -> str:
        """Generate network XML configuration"""
        root = ET.Element("network")
        
        # Add name and optional bridge
        ET.SubElement(root, "name").text = self.params['name']
        bridge = ET.SubElement(root, "bridge")
        if self.params.get('bridge'):
            bridge.set("name", self.params['bridge'])
        bridge.set("stp", "on" if self.params['stp'] else "off")
        bridge.set("delay", str(self.params['delay']))
        
        if self.params.get('mtu'):
            bridge.set("mtu", str(self.params['mtu']))

        # Add domain if specified
        if self.params.get('domain'):
            ET.SubElement(root, "domain", name=self.params['domain'])

        # Configure network type
        if self.params['type'] != 'isolated':
            forward = ET.SubElement(root, "forward")
            forward.set("mode", self.params['type'])

        # Configure IP and DHCP if CIDR is provided
        if self.params.get('cidr'):
            network = ipaddress.IPv4Network(self.params['cidr'])
            ip = ET.SubElement(root, "ip")
            ip.set("address", str(network.network_address + 1))
            ip.set("netmask", str(network.netmask))

            # Configure DHCP if enabled
            dhcp_config = self.params.get('dhcp', {})
            if dhcp_config.get('enabled', True):
                dhcp = ET.SubElement(ip, "dhcp")
                
                # Set default DHCP range if not specified
                start = dhcp_config.get('start')
                end = dhcp_config.get('end')
                
                if not start:
                    # Use second half of network range by default
                    start = str(network.network_address + 10)
                if not end:
                    # Use last usable address
                    end = str(network.broadcast_address - 1)
                
                ET.SubElement(dhcp, "range", start=start, end=end)

        # Configure DNS if enabled
        dns_config = self.params.get('dns', {})
        if dns_config.get('enabled', True):
            dns = ET.SubElement(root, "dns")
            
            # Add forwarders
            for forwarder in dns_config.get('forwarders', []):
                ET.SubElement(dns, "forwarder", addr=forwarder)
            
            # Add host entries
            for host in dns_config.get('hosts', []):
                host_elem = ET.SubElement(dns, "host", ip=host['ip'])
                for hostname in host['hostnames']:
                    ET.SubElement(host_elem, "hostname").text = hostname

        return ET.tostring(root, encoding='unicode')

    def ensure_network_state(self, network: libvirt.virNetwork, target_state: str) -> bool:
        """
        Ensure network is in the desired state
        
        Args:
            network: libvirt network object
            target_state: Desired state (active/inactive)
            
        Returns:
            bool: Whether any changes were made
        """
        changed = False
        current_state = "active" if network.isActive() else "inactive"
        
        if current_state != target_state:
            if target_state == "active":
                network.create()
            else:
                network.destroy()
            changed = True
            
        # Handle autostart
        autostart = bool(network.autostart())
        if autostart != self.params['autostart']:
            network.setAutostart(self.params['autostart'])
            changed = True
            
        return changed

    def manage_network(self) -> Tuple[bool, Dict, str]:
        """
        Main method to manage the network state
        
        Returns:
            Tuple containing:
            - Whether any changes were made
            - Network information dictionary
            - Status message
        """
        name = self.params['name']
        state = self.params['state']
        changed = False
        network = None
        msg = ""

        try:
            # Check if network exists
            existing_net = self.network_utils.get_network_info(name)
            if existing_net:
                network = self.conn.networkLookupByName(name)

            # Handle network removal
            if state == 'absent':
                if existing_net:
                    if network.isActive():
                        network.destroy()
                    network.undefine()
                    changed = True
                    msg = f"Network {name} removed"
                else:
                    msg = f"Network {name} does not exist"

            # Handle network creation/modification
            else:
                # Create new network if it doesn't exist
                if not existing_net:
                    if state != "inactive":
                        xml = self.generate_network_xml()
                        network = self.conn.networkDefineXML(xml)
                        changed = True
                        msg = f"Network {name} created"
                    
                # Ensure desired state
                if network:
                    if state in ['active', 'inactive']:
                        changed = self.ensure_network_state(network, state)
                        msg = f"Network {name} state changed to {state}"
                    elif state == 'present':
                        # Activate by default unless dhcp/autostart disabled
                        should_activate = self.params.get('dhcp', {}).get('enabled', True)
                        if should_activate:
                            changed = self.ensure_network_state(network, 'active')
                            msg = f"Network {name} is active"

            # Get final network info
            if state != 'absent':
                self.network_info = self.network_utils.get_network_info(name)

            return changed, self.network_info, msg

        except libvirt.libvirtError as e:
            self.module.fail_json(msg=f"Failed to manage network: {str(e)}")
        except Exception as e:
            self.module.fail_json(msg=f"Unexpected error: {str(e)}", 
                                exception=traceback.format_exc())

def validate_params(module: AnsibleModule) -> None:
    """Validate module parameters"""
    params = module.params
    
    # Validate CIDR if provided
    if params['state'] != 'absent' and params.get('cidr'):
        try:
            ipaddress.IPv4Network(params['cidr'])
        except ValueError as e:
            module.fail_json(msg=f"Invalid CIDR format: {str(e)}")
    
    # Validate DHCP range if provided
    dhcp = params.get('dhcp', {})
    if dhcp and dhcp.get('enabled') and (dhcp.get('start') or dhcp.get('end')):
        try:
            network = ipaddress.IPv4Network(params['cidr'])
            if dhcp.get('start'):
                ipaddress.IPv4Address(dhcp['start'])
            if dhcp.get('end'):
                ipaddress.IPv4Address(dhcp['end'])
        except ValueError as e:
            module.fail_json(msg=f"Invalid DHCP configuration: {str(e)}")

def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
            state=dict(type='str', default='present', 
                      choices=['present', 'absent', 'active', 'inactive']),
            type=dict(type='str', default='nat', 
                     choices=['nat', 'route', 'isolated']),
            bridge=dict(type='str'),
            cidr=dict(type='str'),
            dhcp=dict(type='dict', options=dict(
                enabled=dict(type='bool', default=True),
                start=dict(type='str'),
                end=dict(type='str')
            )),
            dns=dict(type='dict', options=dict(
                enabled=dict(type='bool', default=True),
                forwarders=dict(type='list', elements='str'),
                hosts=dict(type='list', elements='dict', options=dict(
                    ip=dict(type='str', required=True),
                    hostnames=dict(type='list', elements='str', required=True)
                ))
            )),
            domain=dict(type='str'),
            autostart=dict(type='bool', default=True),
            mtu=dict(type='int'),
            delay=dict(type='int', default=0),
            stp=dict(type='bool', default=True),
            uri=dict(type='str', default='qemu:///system'),
            remote_host=dict(type='str'),
            auth_user=dict(type='str'),
            auth_password=dict(type='str', no_log=True)
        ),
        supports_check_mode=True
    )

    if not HAS_LIBVIRT:
        module.fail_json(msg='The libvirt python module is required')

    # Validate parameters
    validate_params(module)

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

        if module.check_mode:
            module.exit_json(changed=True)

        # Initialize network manager and process changes
        network_manager = NetworkManager(module, conn)
        changed, network_info, msg = network_manager.manage_network()

        result = {
            'changed': changed,
            'network': network_info,
            'msg': msg
        }

        module.exit_json(**result)

    except Exception as e:
        module.fail_json(msg=f"Unexpected error: {str(e)}",
                        exception=traceback.format_exc())
    finally:
        libvirt_conn.close()

if __name__ == '__main__':
    main()