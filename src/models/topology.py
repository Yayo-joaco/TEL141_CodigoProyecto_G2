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

    @staticmethod
    def get_links(topology: TopologyType, num_vms: int) -> List[Tuple[int, int]]:
        if num_vms < 2:
            return []

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
    def get_topology_name(topology: TopologyType) -> str:
        names = {
            TopologyType.LINEAL: "Lineal",
            TopologyType.ANILLO: "Anillo",
            TopologyType.MALLA: "Malla",
            TopologyType.ARBOL: "Árbol",
            TopologyType.BUS: "Bus",
        }
        return names.get(topology, "Desconocida")
