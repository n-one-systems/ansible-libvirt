# ./plugins/module_utils/network_utils.py
# nsys-ai-claude-3.5

from __future__ import (absolute_import, division, print_function)

__metaclass__ = type

import fnmatch
import xml.etree.ElementTree as ElementTree
from typing import Dict, List, Optional
import ipaddress

try:
    import libvirt
except ImportError:
    HAS_LIBVIRT = False
else:
    HAS_LIBVIRT = True


class NetworkUtils:
    """
    Utility class to manage libvirt network operations.
    Provides reusable methods for network information and management.
    """

    def __init__(self, conn: libvirt.virConnect):
        """
        Initialize the NetworkUtils with a libvirt connection

        Args:
            conn: An active libvirt connection
        """
        self.conn = conn

    def _extract_bridge_info(self, net_xml: str) -> Dict:
        """
        Extract bridge configuration from network XML

        Args:
            net_xml: XML description of the network

        Returns:
            dict: Bridge configuration details
        """
        try:
            root = ElementTree.fromstring(net_xml)
            bridge_elem = root.find(".//bridge")
            if bridge_elem is not None:
                return {
                    "name": bridge_elem.get("name", ""),
                    "stp": bridge_elem.get("stp", "on") == "on",
                    "delay": int(bridge_elem.get("delay", 0))
                }
        except ElementTree.ParseError:
            pass
        return {}

    def _extract_ip_info(self, net_xml: str) -> Dict:
        """
        Extract IP configuration from network XML

        Args:
            net_xml: XML description of the network

        Returns:
            dict: IP configuration details
        """
        try:
            root = ElementTree.fromstring(net_xml)
            ip_elem = root.find(".//ip")
            if ip_elem is not None:
                ip_info = {
                    "address": ip_elem.get("address"),
                    "netmask": ip_elem.get("netmask"),
                    "dhcp_range": None
                }

                # Calculate CIDR if address and netmask are present
                if ip_info["address"] and ip_info["netmask"]:
                    try:
                        network = ipaddress.IPv4Network(
                            f"{ip_info['address']}/{ip_info['netmask']}",
                            strict=False
                        )
                        ip_info["cidr"] = str(network)
                    except ValueError:
                        ip_info["cidr"] = None

                # Check for DHCP range
                dhcp_elem = ip_elem.find(".//range")
                if dhcp_elem is not None:
                    ip_info["dhcp_range"] = {
                        "start": dhcp_elem.get("start"),
                        "end": dhcp_elem.get("end")
                    }

                return ip_info
        except ElementTree.ParseError:
            pass
        return {}

    def get_network_info(self, network_name: str) -> Dict:
        """
        Get detailed information about a specific network

        Args:
            network_name: Name of the network

        Returns:
            dict: Network information or empty dict if network not found
        """
        try:
            network = self.conn.networkLookupByName(network_name)
            net_xml = network.XMLDesc(0)

            info = {
                "name": network_name,
                "uuid": network.UUIDString(),
                "active": network.isActive(),
                "persistent": network.isPersistent(),
                "autostart": network.autostart(),
                "bridge": None,
                "ip_info": None
            }

            bridge_info = self._extract_bridge_info(net_xml)
            if bridge_info:
                info["bridge"] = bridge_info.get("name")
                info["bridge_details"] = bridge_info

            ip_info = self._extract_ip_info(net_xml)
            if ip_info:
                info["ip_info"] = ip_info

            return info
        except libvirt.libvirtError:
            return {}

    def get_networks_by_pattern(self, pattern: str) -> List[Dict]:
        """
        Get information about networks matching a pattern

        Args:
            pattern: Glob pattern to match network names

        Returns:
            list: List of network information dictionaries
        """
        networks = []
        try:
            all_networks = (
                self.conn.listNetworks() +
                self.conn.listDefinedNetworks()
            )
            matching_networks = fnmatch.filter(all_networks, pattern)

            for network in matching_networks:
                net_info = self.get_network_info(network)
                if net_info:
                    networks.append(net_info)

        except libvirt.libvirtError:
            pass

        return networks

    def get_all_networks(self) -> List[Dict]:
        """
        Get information about all networks

        Returns:
            list: List of network information dictionaries
        """
        return self.get_networks_by_pattern("*")

    def network_exists(self, network_name: str) -> bool:
        """
        Check if a network exists

        Args:
            network_name: Name of the network

        Returns:
            bool: True if network exists, False otherwise
        """
        return bool(self.get_network_info(network_name))

    def get_network_by_cidr(self, cidr: str) -> Optional[Dict]:
        """
        Find network matching a specific CIDR

        Args:
            cidr: Network CIDR (e.g., "192.168.1.0/24")

        Returns:
            Optional[dict]: Network information or None if not found
        """
        try:
            target_network = ipaddress.IPv4Network(cidr, strict=False)

            for network in self.get_all_networks():
                if (network.get("ip_info") and
                    network["ip_info"].get("cidr")):
                    try:
                        net_cidr = ipaddress.IPv4Network(
                            network["ip_info"]["cidr"],
                            strict=False
                        )
                        if net_cidr == target_network:
                            return network
                    except ValueError:
                        continue
        except ValueError:
            pass

        return None

    def refresh_network(self, network_name: str = None) -> tuple[bool, str]:
        """
        Refresh network state to ensure up-to-date information

        Args:
            network_name: Optional name of specific network to refresh

        Returns:
            tuple: (success, message)
        """
        try:
            if network_name:
                networks = [self.conn.networkLookupByName(network_name)]
            else:
                networks = self.conn.listAllNetworks()

            refreshed = []
            failed = []

            for network in networks:
                try:
                    if network.isActive():
                        # Force a refresh of the network's state
                        network.destroy()
                        network.create()
                    refreshed.append(network.name())
                except libvirt.libvirtError as e:
                    failed.append((network.name(), str(e)))

            if failed:
                failures = '; '.join([f"{name}: {error}" for name, error in failed])
                return False, f"Failed to refresh networks: {failures}"

            return True, f"Successfully refreshed networks: {', '.join(refreshed)}"

        except libvirt.libvirtError as e:
            return False, str(e)