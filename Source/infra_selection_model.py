from __future__ import annotations
from typing import List, Dict, Set, Optional
from PyQt6.QtCore import QObject, pyqtSignal

class InfrastructureSelectionModel(QObject):
    """
    Manages the 'Selected Model' state: current route, selected nodes,
    and timing constraints.
    """
    routeChanged = pyqtSignal(list)
    timingConstraintsChanged = pyqtSignal(dict)
    visibleTpTracksChanged = pyqtSignal(set)

    def __init__(self):
        super().__init__()
        self._current_route: List[str] = []
        self._timing_constraints: Dict[int, dict] = {}
        self._visible_tp_tracks: Set[str] = set()

    @property
    def current_route(self) -> List[str]:
        return self._current_route

    @current_route.setter
    def current_route(self, route: List[str]):
        self._current_route = route
        self.routeChanged.emit(self._current_route)

    @property
    def timing_constraints(self) -> Dict[int, dict]:
        return self._timing_constraints

    @timing_constraints.setter
    def timing_constraints(self, constraints: Dict[int, dict]):
        self._timing_constraints = constraints
        self.timingConstraintsChanged.emit(self._timing_constraints)

    @property
    def visible_tp_tracks(self) -> Set[str]:
        return self._visible_tp_tracks

    @visible_tp_tracks.setter
    def visible_tp_tracks(self, tracks: Set[str]):
        self._visible_tp_tracks = tracks
        self.visibleTpTracksChanged.emit(self._visible_tp_tracks)

    def clear(self):
        self._current_route = []
        self._timing_constraints = {}
        self._visible_tp_tracks = set()
        self.routeChanged.emit([])
        self.timingConstraintsChanged.emit({})
        self.visibleTpTracksChanged.emit(set())
