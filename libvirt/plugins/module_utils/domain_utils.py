# ./plugins/module_utils/domain_utils.py
# nsys-ai-claude-3.5

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import fnmatch
import xml.etree.ElementTree as ElementTree
from typing import Dict, List, Optional, Union

try:
    import libvirt
except ImportError:
    HAS_LIBVIRT = False
else:
    HAS_LIBVIRT = True


class DomainUtils:
    """
    Utility class to manage libvirt domain operations.
    Provides reusable methods for domain information and management.
    """

    def __init__(self, conn: libvirt.virConnect):
        """
        Initialize the DomainUtils with a libvirt connection

        Args:
            conn: An active libvirt connection
        """
        self.conn = conn

    def _extract_disk_info(self, dom_xml: str) -> List[Dict]:
        """
        Extract disk configuration from domain XML

        Args:
            dom_xml: XML description of the domain

        Returns:
            list: List of disk configuration details
        """
        try:
            root = ElementTree.fromstring(dom_xml)
            disks = []
            for disk_elem in root.findall(".//disk"):
                if disk_elem.get("device") == "disk":
                    source = disk_elem.find("source")
                    target = disk_elem.find("target")
                    driver = disk_elem.find("driver")
                    
                    disk_info = {
                        "type": disk_elem.get("type"),
                        "device": disk_elem.get("device"),
                        "source": source.get("file") if source is not None else None,
                        "target": target.get("dev") if target is not None else None,
                        "bus": target.get("bus") if target is not None else None,
                        "driver": {
                            "name": driver.get("name") if driver is not None else None,
                            "type": driver.get("type") if driver is not None else None
                        }
                    }
                    disks.append(disk_info)
            return disks
        except ElementTree.ParseError:
            return []

    def _extract_network_interfaces(self, dom_xml: str) -> List[Dict]:
        """
        Extract network interface configuration from domain XML

        Args:
            dom_xml: XML description of the domain

        Returns:
            list: List of network interface configuration details
        """
        try:
            root = ElementTree.fromstring(dom_xml)
            interfaces = []
            for iface_elem in root.findall(".//interface"):
                source = iface_elem.find("source")
                model = iface_elem.find("model")
                mac = iface_elem.find("mac")
                
                iface_info = {
                    "type": iface_elem.get("type"),
                    "source": {
                        "network": source.get("network") if source is not None else None,
                        "bridge": source.get("bridge") if source is not None else None
                    },
                    "model": model.get("type") if model is not None else None,
                    "mac": mac.get("address") if mac is not None else None
                }
                interfaces.append(iface_info)
            return interfaces
        except ElementTree.ParseError:
            return []

    def _extract_memory_info(self, dom_xml: str) -> Dict:
        """
        Extract memory configuration from domain XML

        Args:
            dom_xml: XML description of the domain

        Returns:
            dict: Memory configuration details
        """
        try:
            root = ElementTree.fromstring(dom_xml)
            memory = root.find("memory")
            currentMemory = root.find("currentMemory")
            
            return {
                "maximum": int(memory.text) if memory is not None else None,
                "current": int(currentMemory.text) if currentMemory is not None else None,
                "unit": memory.get("unit") if memory is not None else "KiB"
            }
        except ElementTree.ParseError:
            return {}

    def get_raw_xml(self, domain_name: str) -> Optional[str]:
        """
        Get the raw XML configuration of a domain

        Args:
            domain_name: Name of the domain

        Returns:
            Optional[str]: Raw XML configuration or None if domain not found
        """
        try:
            domain = self.conn.lookupByName(domain_name)
            return domain.XMLDesc(0)
        except libvirt.libvirtError:
            return None

    def get_domain_info(self, domain_name: str) -> Dict:
        """
        Get detailed information about a specific domain

        Args:
            domain_name: Name of the domain

        Returns:
            dict: Domain information or empty dict if domain not found
        """
        try:
            domain = self.conn.lookupByName(domain_name)
            dom_xml = domain.XMLDesc(0)
            dom_info = domain.info()

            info = {
                "name": domain_name,
                "uuid": domain.UUIDString(),
                "id": domain.ID(),
                "state": dom_info[0],
                "max_memory": dom_info[1],
                "memory": dom_info[2],
                "vcpus": dom_info[3],
                "cpu_time": dom_info[4],
                "active": domain.isActive(),
                "persistent": domain.isPersistent(),
                "autostart": domain.autostart(),
                "memory_info": self._extract_memory_info(dom_xml),
                "disks": self._extract_disk_info(dom_xml),
                "interfaces": self._extract_network_interfaces(dom_xml),
            }
            return info
        except libvirt.libvirtError:
            return {}

    def get_domains_by_pattern(self, pattern: str) -> List[Dict]:
        """
        Get information about domains matching a pattern

        Args:
            pattern: Glob pattern to match domain names

        Returns:
            list: List of domain information dictionaries
        """
        domains = []
        try:
            all_domains = (
                [self.conn.lookupByID(did).name() for did in self.conn.listDomainsID()] +
                self.conn.listDefinedDomains()
            )
            matching_domains = fnmatch.filter(all_domains, pattern)

            for domain in matching_domains:
                dom_info = self.get_domain_info(domain)
                if dom_info:
                    domains.append(dom_info)

        except libvirt.libvirtError:
            pass

        return domains

    def get_all_domains(self) -> List[Dict]:
        """
        Get information about all domains

        Returns:
            list: List of domain information dictionaries
        """
        return self.get_domains_by_pattern("*")

    def domain_exists(self, domain_name: str) -> bool:
        """
        Check if a domain exists

        Args:
            domain_name: Name of the domain

        Returns:
            bool: True if domain exists, False otherwise
        """
        return bool(self.get_domain_info(domain_name))

    def get_domain_state(self, domain_name: str) -> Optional[int]:
        """
        Get the current state of a domain

        Args:
            domain_name: Name of the domain

        Returns:
            Optional[int]: Domain state code or None if domain not found
            States:
                VIR_DOMAIN_NOSTATE = 0
                VIR_DOMAIN_RUNNING = 1
                VIR_DOMAIN_BLOCKED = 2
                VIR_DOMAIN_PAUSED  = 3
                VIR_DOMAIN_SHUTDOWN = 4
                VIR_DOMAIN_SHUTOFF = 5
                VIR_DOMAIN_CRASHED = 6
                VIR_DOMAIN_PMSUSPENDED = 7
        """
        try:
            domain = self.conn.lookupByName(domain_name)
            return domain.info()[0]
        except libvirt.libvirtError:
            return None

    def is_domain_active(self, domain_name: str) -> bool:
        """
        Check if a domain is currently active

        Args:
            domain_name: Name of the domain

        Returns:
            bool: True if domain is active, False otherwise
        """
        try:
            domain = self.conn.lookupByName(domain_name)
            return domain.isActive()
        except libvirt.libvirtError:
            return False

    def wait_for_state(self, domain: libvirt.virDomain, target_state: int, timeout: int = 60) -> bool:
        """
        Wait for domain to reach target state

        Args:
            domain: Domain object
            target_state: Target state to wait for
            timeout: Timeout in seconds

        Returns:
            bool: True if state reached, False if timeout
        """
        import time
        start_time = time.time()
        while time.time() - start_time < timeout:
            current_state = self.get_domain_state(domain.name())
            if current_state == target_state:
                return True
            time.sleep(1)
        return False

    def manage_power_state(self, domain_name: str, state: str, force: bool = False) -> Dict:
        """
        Manage domain power state

        Args:
            domain_name: Name of the domain
            state: Desired state ('poweroff', 'reboot', 'start')
            force: Whether to force the operation

        Returns:
            dict: Operation result with changed status and final state
        """
        try:
            domain = self.conn.lookupByName(domain_name)
            current_state = self.get_domain_state(domain_name)
            changed = False

            if state == 'poweroff':
                if current_state != libvirt.VIR_DOMAIN_SHUTOFF:
                    if force:
                        domain.destroy()
                    else:
                        domain.shutdown()
                        if not self.wait_for_state(domain, libvirt.VIR_DOMAIN_SHUTOFF):
                            # Shutdown timed out, force if requested
                            if force:
                                domain.destroy()
                    changed = True

            elif state == 'reboot':
                if current_state == libvirt.VIR_DOMAIN_RUNNING:
                    if force:
                        domain.reset(0)
                    else:
                        domain.reboot(0)
                    changed = True

            elif state == 'running':
                if current_state != libvirt.VIR_DOMAIN_RUNNING:
                    domain.create()
                    changed = True

            return {
                'changed': changed,
                'state': self.get_domain_state(domain_name)
            }

        except libvirt.libvirtError as e:
            raise Exception(f"Failed to manage domain state: {str(e)}")