# ./plugins/lookup/domain/libvirt_vms.py
#!/usr/bin/python
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r"""
    name: libvirt_vms
    author: n!-systems (claude sonnet 3.5) <ai-working-group@none.systems>
    version_added: "1.0"
    short_description: Lists libvirt VMs by state
    description:
        - Returns a list of libvirt VMs filtered by state
        - Can return running VMs, shutdown VMs, or all VMs
    options:
        _terms:
            description: State to filter VMs by ("running", "shutdown", "all")
            required: True
            choices: ["running", "shutdown", "all"]
        uri:
            description: libvirt connection URI
            type: string
            default: qemu:///system
"""

EXAMPLES = r"""
- name: Get all running VMs
  debug:
    msg: "Running VMs: {{ query('libvirt_vms', 'running') }}"

- name: Get all shutdown VMs
  debug:
    msg: "Shutdown VMs: {{ query('libvirt_vms', 'shutdown') }}"

- name: Get all VMs
  debug:
    msg: "All VMs: {{ query('libvirt_vms', 'all') }}"
"""

RETURN = r"""
  _list:
    description: List of VM names matching the requested state
    type: list
    elements: str
"""

try:
    import libvirt
except ImportError:
    HAS_LIBVIRT = False
else:
    HAS_LIBVIRT = True

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase
from ansible.utils.display import Display

display = Display()

class LookupModule(LookupBase):

    def run(self, terms, variables=None, **kwargs):
        if not HAS_LIBVIRT:
            raise AnsibleError("libvirt-python package is required for this plugin")

        if not terms or len(terms) != 1 or terms[0] not in ['running', 'shutdown', 'all']:
            raise AnsibleError("State must be one of: running, shutdown, all")

        state = terms[0]
        uri = kwargs.get('uri', 'qemu:///system')
        ret = []

        try:
            conn = libvirt.open(uri)
            if not conn:
                raise AnsibleError(f"Failed to open connection to {uri}")

            try:
                # Get all domains
                if state == 'running':
                    domains = conn.listDomainsID()
                    for domain_id in domains:
                        domain = conn.lookupByID(domain_id)
                        ret.append(domain.name())
                elif state == 'shutdown':
                    domains = conn.listDefinedDomains()
                    ret.extend(domains)
                else:  # all
                    # Get running domains
                    running_domains = conn.listDomainsID()
                    for domain_id in running_domains:
                        domain = conn.lookupByID(domain_id)
                        ret.append(domain.name())
                    # Get shutdown domains
                    shutdown_domains = conn.listDefinedDomains()
                    ret.extend(shutdown_domains)

            except libvirt.libvirtError as e:
                raise AnsibleError(f"Error listing domains: {str(e)}")
            finally:
                conn.close()
            display.v(f"Found VMs: {ret}")
            return ret

        except libvirt.libvirtError as e:
            raise AnsibleError(f"Error in libvirt lookup: {str(e)}")
