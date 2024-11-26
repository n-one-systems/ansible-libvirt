# ./plugins/module_utils/libvirt_connection.py
# nsys-ai-claude-3.5

# NOTE
#
# not yet used
#
# NOTE


import libvirt
from ansible.module_utils.basic import AnsibleModule
from typing import Optional, Tuple, Union

EXAMPLES = r'''
Using:
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.nsys.libvirter.plugins.module_utils.libvirt_connection import LibvirtConnection

def main():
    module = AnsibleModule(
        argument_spec=dict(
            uri=dict(type='str', required=False),
            remote_host=dict(type='str', required=False),
            auth_user=dict(type='str', required=False, no_log=True),
            auth_password=dict(type='str', required=False, no_log=True)
        )
    )

    # Initialize connection using collection's utility module
    libvirt_conn = LibvirtConnection(module)
    
    # Setup connection params
    libvirt_conn.setup_connection_params(
        uri=module.params.get('uri'),
        auth_user=module.params.get('auth_user'),
        auth_password=module.params.get('auth_password'),
        remote_host=module.params.get('remote_host')
    )
'''


class LibvirtConnection:
    """
    Utility class to manage libvirt connections for nsys.libvirter collection modules.
    Provides a reusable pattern for establishing and managing libvirt connections.
    """

    def __init__(self, module: AnsibleModule):
        """
        Initialize the LibvirtConnection with an Ansible module instance

        Args:
            module: The AnsibleModule instance from the calling module
        """
        self.module = module
        self.uri = None
        self.conn = None
        self.auth_params = {}

    def setup_connection_params(self,
                                uri: Optional[str] = None,
                                auth_user: Optional[str] = None,
                                auth_password: Optional[str] = None,
                                remote_host: Optional[str] = None) -> None:
        """
        Setup the connection parameters for libvirt

        Args:
            uri: The libvirt connection URI (e.g. qemu:///system)
            auth_user: Username for authentication if required
            auth_password: Password for authentication if required
            remote_host: Remote host to connect to if using remote connection
        """
        if uri:
            self.uri = uri
        elif remote_host:
            self.uri = f"qemu+ssh://{remote_host}/system"
        else:
            self.uri = "qemu:///system"

        if auth_user:
            self.auth_params['username'] = auth_user
        if auth_password:
            self.auth_params['password'] = auth_password

    def connect(self) -> Tuple[bool, Union[libvirt.virConnect, str]]:
        """
        Establish connection to libvirt

        Returns:
            Tuple containing:
            - Boolean indicating success/failure
            - Either the libvirt connection object on success, or error message on failure
        """
        try:
            if self.auth_params:

                def request_cred(credentials, user_data):
                    for credential in credentials:
                        if credential[0] == libvirt.VIR_CRED_AUTHNAME:
                            credential[4] = self.auth_params.get('username', '')
                        elif credential[0] == libvirt.VIR_CRED_PASSPHRASE:
                            credential[4] = self.auth_params.get('password', '')
                    return 0

                auth = [[libvirt.VIR_CRED_AUTHNAME, libvirt.VIR_CRED_PASSPHRASE],
                        request_cred, None]
                self.conn = libvirt.openAuth(self.uri, auth, 0)
            else:
                self.conn = libvirt.open(self.uri)

            if not self.conn:
                return False, f"Failed to connect to libvirt at {self.uri}"

            return True, self.conn

        except libvirt.libvirtError as e:
            return False, f"Failed to connect to libvirt: {str(e)}"

    def get_connection(self) -> libvirt.virConnect:
        """
        Get the established libvirt connection

        Returns:
            The libvirt connection object if connected

        Raises:
            Exception if not connected
        """
        if not self.conn:
            raise Exception("Not connected to libvirt - call connect() first")
        return self.conn

    def close(self) -> None:
        """Close the libvirt connection if active"""
        if self.conn:
            try:
                self.conn.close()
            except:
                pass
            self.conn = None