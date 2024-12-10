# ./plugins/lookup/network/info_by_ip.py
# nsys-ai-claude-3.5

#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
    name: network_info_by_ip
    author: n!-systems (claude sonnet 3.5) <ai-working-group@none.systems>
    version_added: "1.0.0"
    short_description: Retrieve information about libvirt networks by CIDR
    description:
        - This lookup returns information about libvirt networks based on their CIDR
        - Returns network configuration details including bridge, IP, and DHCP settings
        - Returns an empty list if no matching network is found
    options:
        _terms:
            description: CIDR of the network (e.g., '172.21.0.0/24')
            required: True
        wantlist:
            description: Force return of list even if single entry
            type: bool
            default: False
        uri:
            description: libvirt connection URI
            type: str
            default: qemu:///system
            ini:
                - section: network_info_by_ip_lookup
                  key: uri
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
        - "libvirt-python >= 10.9.0"
"""

EXAMPLES = r"""
# Get info for specific network by CIDR
- name: Get network info
  debug:
    msg: "{{ lookup('network_info_by_ip', '172.21.0.0/24') }}"

# Get info for network on remote host
- name: Get network info from remote host
  debug:
    msg: "{{ lookup('network_info_by_ip', '172.21.0.0/24', 
             remote_host='libvirt1.example.com', 
             auth_user='admin', 
             auth_password='secret') }}"

# Handle case when network is not found
- name: Get network info (handles not found case)
  debug:
    msg: "{{ lookup('network_info_by_ip', '192.168.0.0/16') | default('Network not found') }}"
"""

RETURN = r"""
_raw:
    description: Network information dictionary or list containing single dictionary. Empty list if no match found.
    type: list/dict
    contains:
        active:
            description: Whether the network is active (1) or not (0)
            type: int
        autostart:
            description: Whether the network autostarts (1) or not (0)
            type: int
        bridge:
            description: Bridge device name
            type: str
        bridge_details:
            description: Bridge configuration details
            type: dict
        cidr:
            description: Network CIDR
            type: str
        ip_info:
            description: IP configuration including address and netmask
            type: dict
        name:
            description: Network name
            type: str
        persistent:
            description: Whether the network is persistent (1) or not (0)
            type: int
        uuid:
            description: Network UUID
            type: str
"""

try:
    import libvirt
    HAS_LIBVIRT = True
except ImportError:
    HAS_LIBVIRT = False

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase
from ansible.utils.display import Display
from ansible_collections.nsys.libvirt.plugins.module_utils.common.libvirt_connection import LibvirtConnection
from ansible_collections.nsys.libvirt.plugins.module_utils.network.network_utils import NetworkUtils

display = Display()


class LookupModule(LookupBase):

    def run(self, terms, variables=None, **kwargs):
        if not HAS_LIBVIRT:
            raise AnsibleError("libvirt-python is required for network_info_by_ip lookup")

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

        # Establish connection
        success, conn = libvirt_conn.connect()
        if not success:
            raise AnsibleError(f"Failed to connect to libvirt: {conn}")

        try:
            network_utils = NetworkUtils(conn)

            for term in terms:
                network = network_utils.get_network_by_cidr(term)
                if network:
                    ret.append(network)
                else:
                    display.vvv(f"No network found with CIDR: {term}")
                    ret.append({})

            display.vvv(f"Network info by IP lookup result: {ret}")
            return ret

        except Exception as e:
            raise AnsibleError(f"Error in network_info_by_ip lookup: {str(e)}")
        finally:
            libvirt_conn.close()