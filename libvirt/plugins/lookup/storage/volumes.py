# ./plugins/lookup/storage/volumes.py
# nsys-ai-claude-3.5

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r"""
    name: volume_info
    author: n!-systems (claude sonnet 3.5) <ai-working-group@none.systems>
    version_added: "1.0.0"
    short_description: Retrieve information about libvirt storage volumes
    description:
        - This lookup returns information about libvirt storage volumes
        - Can return single volume info or multiple volumes based on pattern matching
        - Returns empty dict for non-existent volumes when not using wildcards
        - Returns empty list for non-matching wildcard patterns
    options:
        _terms:
            description: 
                - Path to volume in format "pool_name/volume_name"
                - Supports wildcards for volume_name when using with pool_name/*
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
                - section: volume_info_lookup
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
        - Requires Python >= 3.12
"""

EXAMPLES = r"""
# Get info for specific volume
- name: Get volume info
  debug:
    msg: "{{ lookup('volume_info', 'default/my-volume.qcow2') }}"

# Get info for specific volume as list
- name: Get volume info as list
  debug:
    msg: "{{ lookup('volume_info', 'default/my-volume.qcow2', wantlist=True) }}"

# Get info for all volumes in pool
- name: Get all volumes
  debug:
    msg: "{{ lookup('volume_info', 'default/*') }}"

# Get info for volume on remote host
- name: Get volume info from remote host
  debug:
    msg: "{{ lookup('volume_info', 'default/my-volume.qcow2', 
             remote_host='libvirt1.example.com', 
             auth_user='admin', 
             auth_password='secret') }}"

# Handle non-existent volume
- name: Get info for missing volume
  debug:
    msg: "Volume exists: {{ lookup('volume_info', 'default/missing.qcow2') != {} }}"
"""

RETURN = r"""
_raw:
    description:
        - List of volume information dictionaries or single dictionary when not using wantlist=True
        - Returns empty dict for missing single volumes or empty list for no wildcard matches
    type: list/dict
    contains:
        name:
            description: Volume name
            type: str
        path:
            description: Volume path
            type: str
        capacity:
            description: Volume capacity in bytes
            type: int
        allocation:
            description: Current allocation in bytes
            type: int
        format:
            description: Volume format (raw, qcow2, etc)
            type: str
        pool:
            description: Storage pool name
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
from ansible_collections.nsys.libvirt.plugins.module_utils.libvirt_connection import LibvirtConnection
from ansible_collections.nsys.libvirt.plugins.module_utils.volume_utils import VolumeUtils

display = Display()


class LookupModule(LookupBase):

    def run(self, terms, variables=None, **kwargs):
        if not HAS_LIBVIRT:
            raise AnsibleError("libvirt-python is required for volume_info lookup")

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
                # Initialize volume utilities
                volume_utils = VolumeUtils(conn)

                for term in terms:
                    try:
                        # Parse the pool/volume path
                        pool_name, volume_pattern = volume_utils.parse_volume_path(term)
                    except ValueError as e:
                        raise AnsibleError(str(e))

                    # Handle wildcard patterns
                    if '*' in volume_pattern:
                        # Refresh pool to ensure we have current volume list
                        if not volume_utils.refresh_pool(pool_name):
                            display.warning(f"Failed to refresh pool: {pool_name}")
                            ret.append([])
                            continue

                        volumes = volume_utils.get_volumes_by_pattern(pool_name, volume_pattern)
                        if not volumes:
                            display.vvv(f"No volumes matched pattern: {volume_pattern}")
                            ret.append([])
                        else:
                            ret.extend(volumes)
                    else:
                        # Single volume lookup
                        vol_info = volume_utils.get_volume_info(pool_name, volume_pattern)
                        if not vol_info:
                            display.vvv(f"Volume not found: {term}")
                        ret.append(vol_info)

            finally:
                libvirt_conn.close()

            display.vvv(f"Volume info lookup result: {ret}")
            return ret

        except Exception as e:
            raise AnsibleError(f"Error in volume_info lookup: {str(e)}")