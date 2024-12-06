# ./plugins/lookup/domain/info.py
# nsys-ai-claude-3.5

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r"""
    name: domain_info
    author: n!-systems (claude sonnet 3.5) <ai-working-group@none.systems>
    version_added: "1.0.0"
    short_description: Retrieve information about libvirt domains
    description:
        - This lookup returns information about libvirt domains
        - Can return single domain info or multiple domains based on pattern matching
        - Returns empty dict for non-existent domains when not using wildcards
        - Returns empty list for non-matching wildcard patterns
    options:
        _terms:
            description: 
                - Name of domain to look up
                - Supports wildcards for matching multiple domains
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
                - section: domain_info_lookup
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
        - Returns empty dict/list when domain not found
    requirements:
        - "python >= 3.12"
        - "libvirt-python >= 10.9.0"
"""

EXAMPLES = r"""
# Get info for specific domain
- name: Get domain info
  debug:
    msg: "{{ lookup('domain.info', 'my-vm') }}"

# Get info for specific domain as list
- name: Get domain info as list
  debug:
    msg: "{{ lookup('domain.info', 'my-vm', wantlist=True) }}"

# Get info for all domains
- name: Get all domains
  debug:
    msg: "{{ lookup('domain.info', '*') }}"

# Get info for domain on remote host
- name: Get domain info from remote host
  debug:
    msg: "{{ lookup('domain.info', 'my-vm', 
             remote_host='libvirt1.example.com', 
             auth_user='admin', 
             auth_password='secret') }}"
"""

RETURN = r"""
_raw:
    description:
        - List of domain information dictionaries or single dictionary when not using wantlist=True
        - Returns empty dict for missing single domains or empty list for no wildcard matches
    type: list/dict
    contains:
        name:
            description: Domain name
            type: str
        uuid:
            description: Domain UUID
            type: str
        id:
            description: Running domain ID
            type: int
        state:
            description: Domain state
            type: int
        max_memory:
            description: Maximum memory in KiB
            type: int
        memory:
            description: Current memory in KiB
            type: int
        vcpus:
            description: Number of virtual CPUs
            type: int
        cpu_time:
            description: CPU time used in nanoseconds
            type: int
        active:
            description: Whether domain is active
            type: bool
        persistent:
            description: Whether domain is persistent
            type: bool
        autostart:
            description: Whether domain autostarts
            type: bool
        memory_info:
            description: Detailed memory configuration
            type: dict
        disks:
            description: List of attached disks
            type: list
        interfaces:
            description: List of network interfaces
            type: list
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
from ansible_collections.nsys.libvirt.plugins.module_utils.domain.domain_utils import DomainUtils

display = Display()


class LookupModule(LookupBase):

    def run(self, terms, variables=None, **kwargs):
        if not HAS_LIBVIRT:
            raise AnsibleError("libvirt-python is required for domain_info lookup")

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
                # Initialize domain utilities
                domain_utils = DomainUtils(conn)

                for term in terms:
                    if '*' in term:
                        domains = domain_utils.get_domains_by_pattern(term)
                        if not domains:
                            display.vvv(f"No domains matched pattern: {term}")
                            ret.append([])
                        else:
                            ret.extend(domains)
                    else:
                        # Single domain lookup
                        dom_info = domain_utils.get_domain_info(term)
                        if not dom_info:
                            display.vvv(f"Domain not found: {term}")
                        ret.append(dom_info)

            finally:
                libvirt_conn.close()

            display.vvv(f"Domain info lookup result: {ret}")
            return ret

        except Exception as e:
            raise AnsibleError(f"Error in domain_info lookup: {str(e)}")
