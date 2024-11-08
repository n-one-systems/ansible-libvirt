# ./plugins/module_utils/volume_utils.py
# nsys-ai-claude-3.5

from __future__ import (absolute_import, division, print_function)

__metaclass__ = type

import fnmatch
import xml.etree.ElementTree as ElementTree
from typing import Dict, List, Optional, Tuple, Union

try:
    import libvirt
except ImportError:
    HAS_LIBVIRT = False
else:
    HAS_LIBVIRT = True


class VolumeUtils:
    """
    Utility class to manage libvirt storage volume operations.
    Provides reusable methods for volume information and management.
    """

    def __init__(self, conn: libvirt.virConnect):
        """
        Initialize the VolumeUtils with a libvirt connection

        Args:
            conn: An active libvirt connection
        """
        self.conn = conn

    def _refresh_pool(self, pool: libvirt.virStoragePool) -> bool:
        """
        Internal method to refresh a storage pool

        Args:
            pool: libvirt storage pool object

        Returns:
            bool: True if refresh successful, False otherwise
        """
        try:
            pool.refresh(0)
            return True
        except libvirt.libvirtError:
            return False

    def _get_pool(self, pool_name: str) -> Optional[libvirt.virStoragePool]:
        """
        Internal method to get and refresh a storage pool

        Args:
            pool_name: Name of the storage pool

        Returns:
            Optional[virStoragePool]: Pool object or None if not found
        """
        try:
            pool = self.conn.storagePoolLookupByName(pool_name)
            self._refresh_pool(pool)
            return pool
        except libvirt.libvirtError:
            return None

    def _extract_volume_format(self, vol_xml: str) -> str:
        """
        Extract volume format from XML description

        Args:
            vol_xml: XML description of the volume

        Returns:
            str: Volume format type (e.g., 'raw', 'qcow2')
        """
        try:
            root = ElementTree.fromstring(vol_xml)
            format_elem = root.find(".//format")
            if format_elem is not None and "type" in format_elem.attrib:
                return format_elem.attrib["type"]
        except ElementTree.ParseError:
            pass
        return "raw"

    def get_volume_info(self, pool_name: str, volume_name: str) -> Dict:
        """
        Get detailed information about a specific volume

        Args:
            pool_name: Name of the storage pool
            volume_name: Name of the volume

        Returns:
            dict: Volume information or empty dict if volume not found
        """
        try:
            pool = self._get_pool(pool_name)
            if not pool:
                return {}
                
            vol = pool.storageVolLookupByName(volume_name)
            vol_info = vol.info()
            vol_xml = vol.XMLDesc(0)

            return {
                "name": volume_name,
                "path": vol.path(),
                "capacity": vol_info[1],
                "allocation": vol_info[2],
                "format": self._extract_volume_format(vol_xml),
                "pool": pool_name,
            }
        except libvirt.libvirtError:
            return {}

    def get_volumes_by_pattern(self, pool_name: str, pattern: str) -> List[Dict]:
        """
        Get information about volumes matching a pattern within a pool

        Args:
            pool_name: Name of the storage pool
            pattern: Glob pattern to match volume names

        Returns:
            list: List of volume information dictionaries
        """
        volumes = []
        try:
            pool = self._get_pool(pool_name)
            if not pool:
                return volumes

            all_volumes = pool.listVolumes()
            matching_volumes = fnmatch.filter(all_volumes, pattern)

            for volume in matching_volumes:
                vol_info = self.get_volume_info(pool_name, volume)
                if vol_info:
                    volumes.append(vol_info)

        except libvirt.libvirtError:
            pass

        return volumes

    def get_pool_volumes(self, pool_name: str) -> List[Dict]:
        """
        Get information about all volumes in a pool

        Args:
            pool_name: Name of the storage pool

        Returns:
            list: List of volume information dictionaries
        """
        return self.get_volumes_by_pattern(pool_name, "*")

    def refresh_pool(self, pool_name: str) -> bool:
        """
        Refresh a storage pool to update volume information

        Args:
            pool_name: Name of the storage pool

        Returns:
            bool: True if refresh successful, False otherwise
        """
        try:
            pool = self._get_pool(pool_name)
            return bool(pool)
        except libvirt.libvirtError:
            return False

    def volume_exists(self, pool_name: str, volume_name: str) -> bool:
        """
        Check if a volume exists in the specified pool

        Args:
            pool_name: Name of the storage pool
            volume_name: Name of the volume

        Returns:
            bool: True if volume exists, False otherwise
        """
        return bool(self.get_volume_info(pool_name, volume_name))

    def parse_volume_path(self, volume_path: str) -> Tuple[str, str]:
        """
        Parse a volume path in the format "pool_name/volume_name"

        Args:
            volume_path: Volume path in format "pool_name/volume_name"

        Returns:
            tuple: (pool_name, volume_name)

        Raises:
            ValueError: If path format is invalid
        """
        try:
            pool_name, volume_name = volume_path.split("/", 1)
            return pool_name, volume_name
        except ValueError:
            raise ValueError("Volume path must be in format 'pool_name/volume_name'")
