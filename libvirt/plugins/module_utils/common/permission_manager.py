# ./plugins/module_utils/common/permission_manager.py
# nsys-ai-claude-3.5

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import os
import pwd
import grp
from typing import Optional, Tuple, Union

class PermissionManager:
    """
    Utility class to manage file and directory permissions.
    Handles owner/group resolution and recursive permission setting.
    """

    def __init__(self, module):
        """
        Initialize the PermissionManager with an Ansible module instance

        Args:
            module: The AnsibleModule instance to use for operations
        """
        self.module = module

    def _resolve_owner(self, owner: Optional[Union[str, int]]) -> Optional[int]:
        """
        Resolve owner name/ID to numeric UID

        Args:
            owner: Username or UID

        Returns:
            int: Numeric UID or None if not specified
            
        Raises:
            ValueError: If owner cannot be resolved
        """
        if owner is None:
            return None
        try:
            if isinstance(owner, int) or (isinstance(owner, str) and owner.isdigit()):
                return int(owner)
            return pwd.getpwnam(owner).pw_uid
        except (KeyError, ValueError):
            raise ValueError(f"Unable to resolve owner: {owner}")

    def _resolve_group(self, group: Optional[Union[str, int]]) -> Optional[int]:
        """
        Resolve group name/ID to numeric GID

        Args:
            group: Group name or GID

        Returns:
            int: Numeric GID or None if not specified
            
        Raises:
            ValueError: If group cannot be resolved
        """
        if group is None:
            return None
        try:
            if isinstance(group, int) or (isinstance(group, str) and group.isdigit()):
                return int(group)
            return grp.getgrnam(group).gr_gid
        except (KeyError, ValueError):
            raise ValueError(f"Unable to resolve group: {group}")

    def _set_perms(self, path: str, mode: Optional[str], 
                   uid: Optional[int], gid: Optional[int]) -> bool:
        """
        Set permissions on a single file/directory

        Args:
            path: Path to set permissions on
            mode: Permission mode (octal string)
            uid: Numeric UID
            gid: Numeric GID

        Returns:
            bool: Whether any changes were made
        """
        changed = False
        try:
            # Get current state
            st = os.stat(path)
            current_mode = st.st_mode & 0o777
            current_uid = st.st_uid
            current_gid = st.st_gid

            # Update mode if specified and different
            if mode is not None:
                mode_int = int(mode, 8)
                if current_mode != mode_int:
                    os.chmod(path, mode_int)
                    changed = True

            # Update ownership if different
            if (uid is not None and uid != current_uid) or \
               (gid is not None and gid != current_gid):
                os.chown(path, 
                        uid if uid is not None else -1,
                        gid if gid is not None else -1)
                changed = True

            return changed

        except (OSError, IOError) as e:
            self.module.fail_json(
                msg=f"Failed to set permissions on {path}: {str(e)}")

    def create_with_permissions(self, path: str, mode: Optional[str],
                              owner: Optional[Union[str, int]], 
                              group: Optional[Union[str, int]],
                              is_directory: bool = False) -> bool:
        """
        Create a file/directory with specified permissions

        Args:
            path: Path to create
            mode: Permission mode (octal string)
            owner: Owner name/ID
            group: Group name/ID
            is_directory: Whether to create a directory

        Returns:
            bool: Whether any changes were made
        """
        if os.path.exists(path):
            return self.manage_permissions(path, mode, owner, group)

        try:
            # Resolve owner/group before creation
            uid = self._resolve_owner(owner)
            gid = self._resolve_group(group)

            # Create with default permissions first
            if is_directory:
                os.makedirs(path, exist_ok=True)
            else:
                open(path, 'a').close()

            # Then set requested permissions
            self._set_perms(path, mode, uid, gid)
            return True

        except (OSError, IOError) as e:
            self.module.fail_json(
                msg=f"Failed to create {path}: {str(e)}")

    def manage_permissions(self, path: str, mode: Optional[str],
                         owner: Optional[Union[str, int]], 
                         group: Optional[Union[str, int]],
                         recursive: bool = False) -> bool:
        """
        Manage permissions on existing file/directory

        Args:
            path: Path to manage
            mode: Permission mode (octal string)
            owner: Owner name/ID
            group: Group name/ID
            recursive: Whether to apply recursively

        Returns:
            bool: Whether any changes were made
        """
        if not os.path.exists(path):
            self.module.fail_json(msg=f"Path does not exist: {path}")

        try:
            changed = False
            uid = self._resolve_owner(owner)
            gid = self._resolve_group(group)

            # Update root path
            if self._set_perms(path, mode, uid, gid):
                changed = True

            # Recursively update if requested and path is directory
            if recursive and os.path.isdir(path):
                for root, dirs, files in os.walk(path):
                    for d in dirs:
                        if self._set_perms(os.path.join(root, d), mode, uid, gid):
                            changed = True
                    for f in files:
                        if self._set_perms(os.path.join(root, f), mode, uid, gid):
                            changed = True

            return changed

        except Exception as e:
            self.module.fail_json(
                msg=f"Failed to manage permissions on {path}: {str(e)}")
