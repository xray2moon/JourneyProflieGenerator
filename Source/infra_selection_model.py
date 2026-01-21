from __future__ import annotations
from typing import List, Dict, Set, Optional
from PyQt6.QtCore import QObject, pyqtSignal

class InfrastructureSelectionModel(QObject):
    """
    Manages the 'Selected Model' state: current route, selected nodes,
    and timing constraints.
    """
    routeChanged = pyqtSignal(list)  # list of node IDs
    tracksChanged = pyqtSignal(list)  # list of track IDs
    timingConstraintsChanged = pyqtSignal(dict)
    visibleTpTracksChanged = pyqtSignal(set)
    selectionChanged = pyqtSignal(dict)  # for tooltips/sidepanels

    def __init__(self):
        super().__init__()
        self._current_route: List[str] = []
        self._current_tracks: List[str] = []
        self._timing_constraints: Dict[int, dict] = {}
        self._visible_tp_tracks: Set[str] = set()

    @property
    def current_route(self) -> List[str]:
        return self._current_route

    def set_route(self, nodes: List[str], tracks: List[str]):
        self._current_route = nodes
        self._current_tracks = tracks
        self.routeChanged.emit(self._current_route)
        self.tracksChanged.emit(self._current_tracks)

    @property
    def current_tracks(self) -> List[str]:
        return self._current_tracks

    @property
    def timing_constraints(self) -> Dict[int, dict]:
        return self._timing_constraints

    def set_timing_constraint(self, tp_id: int, constraint: Optional[dict]):
        if constraint is None:
            self._timing_constraints.pop(tp_id, None)
        else:
            self._timing_constraints[tp_id] = constraint
        self.timingConstraintsChanged.emit(self._timing_constraints)

    @property
    def visible_tp_tracks(self) -> Set[str]:
        return self._visible_tp_tracks

    def set_visible_tp_tracks(self, tracks: Set[str]):
        self._visible_tp_tracks = tracks
        self.visibleTpTracksChanged.emit(self._visible_tp_tracks)

    def clear_selection(self):
        self._current_route = []
        self._current_tracks = []
        self._timing_constraints = {}
        self._visible_tp_tracks = set()
        self.routeChanged.emit([])
        self.tracksChanged.emit([])
        self.timingConstraintsChanged.emit({})
        self.visibleTpTracksChanged.emit(set())
