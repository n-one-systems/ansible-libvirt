from __future__ import (absolute_import, division, print_function)

__metaclass__ = type

import fnmatch
import time
import xml.etree.ElementTree as ElementTree
from typing import Dict, List, Optional, Tuple

try:
    import libvirt
except ImportError:
    HAS_LIBVIRT = False
else:
    HAS_LIBVIRT = True



class StoragePoolUtils:
    """
    Utility class to manage libvirt storage pool operations.
    Provides reusable methods for pool information and management.
    """

    def __init__(self, conn: libvirt.virConnect):
        """
        Initialize the StoragePoolUtils with a libvirt connection

        Args:
            conn: An active libvirt connection
        """
        self.conn = conn

    def _extract_target_info(self, pool_xml: str) -> Dict:
        """
        Extract target configuration from pool XML

        Args:
            pool_xml: XML description of the pool

        Returns:
            dict: Target configuration details
        """
        try:
            root = ElementTree.fromstring(pool_xml)
            target_elem = root.find(".//target")
            if target_elem is not None:
                path_elem = target_elem.find("path")
                perms_elem = target_elem.find("permissions")

                target_info = {
                    "path": path_elem.text if path_elem is not None else None,
                    "permissions": {}
                }

                if perms_elem is not None:
                    for perm in ["mode", "owner", "group"]:
                        elem = perms_elem.find(perm)
                        if elem is not None:
                            target_info["permissions"][perm] = elem.text

                return target_info
        except ElementTree.ParseError:
            pass
        return {}

    def _extract_source_info(self, pool_xml: str) -> Dict:
        """
        Extract source configuration from pool XML

        Args:
            pool_xml: XML description of the pool

        Returns:
            dict: Source configuration details
        """
        try:
            root = ElementTree.fromstring(pool_xml)
            source_elem = root.find(".//source")
            if source_elem is not None:
                source_info = {}

                # Extract device info if present
                device = source_elem.find("device")
                if device is not None:
                    source_info["device"] = device.get("path")

                # Extract host info if present
                host = source_elem.find("host")
                if host is not None:
                    source_info["host"] = host.get("name")

                # Extract format info if present
                format_elem = source_elem.find("format")
                if format_elem is not None:
                    source_info["format"] = format_elem.get("type")

                return source_info
        except ElementTree.ParseError:
            pass
        return {}

    def get_pool_info(self, pool_name: str) -> Dict:
        """
        Get detailed information about a specific storage pool

        Args:
            pool_name: Name of the storage pool

        Returns:
            dict: Pool information or empty dict if pool not found
        """
        try:
            pool = self.conn.storagePoolLookupByName(pool_name)
            pool_xml = pool.XMLDesc(0)
            pool_info = pool.info()

            info = {
                "name": pool_name,
                "uuid": pool.UUIDString(),
                "state": pool_info[0],
                "capacity": pool_info[1],
                "allocation": pool_info[2],
                "available": pool_info[3],
                "active": pool.isActive(),
                "persistent": pool.isPersistent(),
                "autostart": pool.autostart(),
                "type": ElementTree.fromstring(pool_xml).get("type"),
                "target_info": self._extract_target_info(pool_xml),
                "source_info": self._extract_source_info(pool_xml)
            }
            return info
        except libvirt.libvirtError:
            return {}

    def get_pools_by_pattern(self, pattern: str) -> List[Dict]:
        """
        Get information about pools matching a pattern

        Args:
            pattern: Glob pattern to match pool names

        Returns:
            list: List of pool information dictionaries
        """
        pools = []
        try:
            all_pools = (
                    self.conn.listStoragePools() +
                    self.conn.listDefinedStoragePools()
            )
            matching_pools = fnmatch.filter(all_pools, pattern)

            for pool in matching_pools:
                pool_info = self.get_pool_info(pool)
                if pool_info:
                    pools.append(pool_info)

        except libvirt.libvirtError:
            pass

        return pools

    def get_all_pools(self) -> List[Dict]:
        """
        Get information about all storage pools

        Returns:
            list: List of pool information dictionaries
        """
        return self.get_pools_by_pattern("*")

    def pool_exists(self, pool_name: str) -> bool:
        """
        Check if a storage pool exists

        Args:
            pool_name: Name of the storage pool

        Returns:
            bool: True if pool exists, False otherwise
        """
        return bool(self.get_pool_info(pool_name))

    def manage_pool_state(self, pool: libvirt.virStoragePool,
                          desired_state: str, autostart: bool,
                          max_retries: int = 3, retry_delay: float = 1.0) -> Tuple[bool, str]:
        """
        Manage pool state (active/inactive) and autostart with retry mechanism

        Args:
            pool: Storage pool object
            desired_state: Desired state ('active', 'inactive')
            autostart: Whether pool should autostart
            max_retries: Maximum number of activation attempts
            retry_delay: Delay between retries in seconds

        Returns:
            tuple: (changed, message)
        """
        changed = False
        messages = []

        try:
            # Handle autostart
            pool_autostart = pool.autostart()
            if autostart != pool_autostart:
                pool.setAutostart(autostart)
                changed = True
                messages.append(
                    f"{'Enabled' if autostart else 'Disabled'} autostart"
                )

            # Handle activation state
            current_state = "active" if pool.isActive() else "inactive"

            if desired_state != current_state:
                if desired_state == "active" and not pool.isActive():
                    retry_count = 0
                    last_error = None

                    while retry_count < max_retries:
                        try:
                            if pool.create() == 0:  # Success
                                changed = True
                                messages.append("Activated pool")
                                break
                            retry_count += 1
                            if retry_count < max_retries:
                                time.sleep(retry_delay)
                        except libvirt.libvirtError as e:
                            last_error = e
                            retry_count += 1
                            if retry_count < max_retries:
                                time.sleep(retry_delay)

                    if retry_count == max_retries:
                        error_msg = str(last_error) if last_error else "Failed to activate pool"
                        raise libvirt.libvirtError(error_msg)

                elif desired_state == "inactive" and pool.isActive():
                    pool.destroy()
                    changed = True
                    messages.append("Deactivated pool")

            return changed, ", ".join(messages) if messages else "No state changes needed"

        except libvirt.libvirtError as e:
            raise Exception(f"Failed to manage pool state: {str(e)}")

    def build_pool_xml(self, name: str, pool_type: str, target_path: str,
                       source_path: Optional[str] = None,
                       source_host: Optional[str] = None,
                       source_format: Optional[str] = None,
                       target_permissions: Optional[Dict] = None) -> str:
        """
        Build XML configuration for a storage pool

        Args:
            name: Name of the pool
            pool_type: Type of storage pool
            target_path: Target path for the pool
            source_path: Source device path (optional)
            source_host: Source host name (optional)
            source_format: Source format type (optional)
            target_permissions: Dict with mode, owner, group (optional)

        Returns:
            str: Pool XML configuration
        """
        pool = ElementTree.Element('pool', type=pool_type)

        # Add name
        name_elem = ElementTree.SubElement(pool, 'name')
        name_elem.text = name

        # Add source configuration if provided
        if any([source_path, source_host, source_format]):
            source = ElementTree.SubElement(pool, 'source')
            if source_path:
                ElementTree.SubElement(source, 'device', path=source_path)
            if source_host:
                ElementTree.SubElement(source, 'host', name=source_host)
            if source_format:
                ElementTree.SubElement(source, 'format', type=source_format)

        # Add target configuration
        target = ElementTree.SubElement(pool, 'target')
        path = ElementTree.SubElement(target, 'path')
        path.text = target_path

        # Add permissions if provided
        if target_permissions:
            perms = ElementTree.SubElement(target, 'permissions')
            for perm_type in ['mode', 'owner', 'group']:
                if perm_type in target_permissions and target_permissions[perm_type] is not None:
                    perm_elem = ElementTree.SubElement(perms, perm_type)
                    perm_elem.text = str(target_permissions[perm_type])

        # Add XML declaration and ensure proper formatting
        xml_declaration = '<?xml version="1.0" encoding="utf-8"?>\n'
        pool_xml = ElementTree.tostring(pool, encoding='unicode', method='xml')
        return xml_declaration + pool_xml

    def refresh_pool(self, pool_name: str = None) -> Tuple[bool, str]:
        """
        Refresh storage pool to ensure up-to-date content information

        Args:
            pool_name: Optional name of specific pool to refresh

        Returns:
            tuple: (success, message)
        """
        try:
            if pool_name:
                pools = [self.conn.storagePoolLookupByName(pool_name)]
            else:
                pools = [self.conn.storagePoolLookupByName(name)
                         for name in self.conn.listStoragePools()]

            refreshed = []
            failed = []

            for pool in pools:
                try:
                    if pool.isActive():
                        pool.refresh(0)
                        refreshed.append(pool.name())
                except libvirt.libvirtError as e:
                    failed.append((pool.name(), str(e)))

            if failed:
                failures = '; '.join([f"{name}: {error}" for name, error in failed])
                return False, f"Failed to refresh pools: {failures}"

            return True, f"Successfully refreshed pools: {', '.join(refreshed)}"

        except libvirt.libvirtError as e:
            return False, str(e)