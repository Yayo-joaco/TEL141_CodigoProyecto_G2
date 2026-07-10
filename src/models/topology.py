# ==============================================================
# Topology definitions: Lineal and Anillo
# Generates link pairs between VMs based on topology type
# ==============================================================

from typing import List, Tuple
from .slice import TopologyType


class Topology:
    """
    Generates the links (edges) between VMs for a given topology.

    Lineal:
        VM0 --- VM1 --- VM2 --- ... --- VM{n-1}

    Anillo:
        VM0 --- VM1 --- VM2 --- ... --- VM{n-1}
         |                                     |
         +-------------------------------------+
    """

    # TopologyType has separate Spanish and English aliases with distinct
    # string values (e.g. LINEAL="lineal" vs LINEAR="linear") that are NOT
    # equal to each other as enum members — normalize here so callers can
    # pass either without every dispatch site needing its own alias table.
    _ALIASES = {
        TopologyType.LINEAR: TopologyType.LINEAL,
        TopologyType.RING: TopologyType.ANILLO,
        TopologyType.MESH: TopologyType.MALLA,
        TopologyType.TREE: TopologyType.ARBOL,
    }

    @staticmethod
    def get_links(topology: TopologyType, num_vms: int) -> List[Tuple[int, int]]:
        if num_vms < 2:
            return []

        topology = Topology._ALIASES.get(topology, topology)

        if topology == TopologyType.LINEAL:
            return Topology._lineal_links(num_vms)
        elif topology == TopologyType.ANILLO:
            return Topology._anillo_links(num_vms)
        elif topology == TopologyType.MALLA:
            return Topology._malla_links(num_vms)
        elif topology == TopologyType.ARBOL:
            return Topology._arbol_links(num_vms)
        elif topology == TopologyType.BUS:
            return Topology._bus_links(num_vms)
        else:
            return []

    @staticmethod
    def _lineal_links(n: int) -> List[Tuple[int, int]]:
        return [(i, i + 1) for i in range(n - 1)]

    @staticmethod
    def _anillo_links(n: int) -> List[Tuple[int, int]]:
        links = [(i, i + 1) for i in range(n - 1)]
        links.append((n - 1, 0))
        return links

    @staticmethod
    def _malla_links(n: int) -> List[Tuple[int, int]]:
        return [(i, j) for i in range(n) for j in range(i + 1, n)]

    @staticmethod
    def _arbol_links(n: int) -> List[Tuple[int, int]]:
        links = []
        for i in range(1, n):
            parent = (i - 1) // 2
            links.append((parent, i))
        return links

    @staticmethod
    def _bus_links(n: int) -> List[Tuple[int, int]]:
        return [(0, i) for i in range(1, n)]

    @staticmethod
    def build_vm_link_map(vms, links: List[Tuple[int, int]],
                          link_vlans: List[dict]) -> dict:
        """
        Returns {vm_name: [{link_idx, vlan_id, peer_vm_name}]} for each VM.
        Each entry represents one link interface the VM needs (one per
        topology edge it participates in) — shared by the Linux driver
        (per-link taps) and the OpenStack driver (per-link Neutron networks).
        """
        vm_names = [vm.name for vm in vms]
        vlan_by_link = {lv["link_idx"]: lv["vlan_id"] for lv in link_vlans}
        result = {vm.name: [] for vm in vms}
        # Use actual link_idx from link_vlans (not enumerate) so edit_slice offsets work
        link_indices = [lv["link_idx"] for lv in link_vlans]
        for i, (a, b) in enumerate(links):
            if a >= len(vm_names) or b >= len(vm_names):
                continue
            actual_link_idx = link_indices[i] if i < len(link_indices) else i
            vlan_id = vlan_by_link.get(actual_link_idx)
            result[vm_names[a]].append({
                "link_idx": actual_link_idx,
                "vlan_id": vlan_id,
                "peer_vm_name": vm_names[b],
            })
            result[vm_names[b]].append({
                "link_idx": actual_link_idx,
                "vlan_id": vlan_id,
                "peer_vm_name": vm_names[a],
            })
        return result

    @staticmethod
    def get_topology_name(topology: TopologyType) -> str:
        topology = Topology._ALIASES.get(topology, topology)
        names = {
            TopologyType.LINEAL: "Lineal",
            TopologyType.ANILLO: "Anillo",
            TopologyType.MALLA: "Malla",
            TopologyType.ARBOL: "Árbol",
            TopologyType.BUS: "Bus",
        }
        return names.get(topology, "Desconocida")
