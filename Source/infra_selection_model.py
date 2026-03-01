from __future__ import annotations
import copy
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
    selectedStoppingPointChanged = pyqtSignal(str)
    startTpChanged = pyqtSignal(object) # Optional[int]
    endTpChanged = pyqtSignal(object)   # Optional[int]
    waypointTpsChanged = pyqtSignal(list)
    segmentSpeedLimitsChanged = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._current_route: List[str] = []
        self._current_tracks: List[str] = []
        self._timing_constraints: Dict[int, dict] = {}
        self._visible_tp_tracks: Set[str] = set()
        self._selected_stopping_point_id: Optional[str] = None
        self._start_tp_id: Optional[int] = None
        self._end_tp_id: Optional[int] = None
        self._waypoint_tp_ids: List[int] = []
        self._segment_speed_limits: Dict[str, Dict[str, float]] = {}

    @property
    def current_route(self) -> List[str]:
        return self._current_route

    def set_route(self, nodes: List[str], tracks: List[str]):
        self._current_route = nodes
        self._current_tracks = tracks
        self.routeChanged.emit(self._current_route)
        self.tracksChanged.emit(self._current_tracks)

    @property
    def start_tp_id(self) -> Optional[int]:
        return self._start_tp_id

    def set_start_tp(self, tp_id: Optional[int]):
        self._start_tp_id = tp_id
        self.startTpChanged.emit(tp_id)

    @property
    def end_tp_id(self) -> Optional[int]:
        return self._end_tp_id

    def set_end_tp(self, tp_id: Optional[int]):
        self._end_tp_id = tp_id
        self.endTpChanged.emit(tp_id)

    @property
    def waypoint_tp_ids(self) -> List[int]:
        return self._waypoint_tp_ids

    def set_waypoint_tp_ids(self, tp_ids: List[int]):
        self._waypoint_tp_ids = list(tp_ids)
        self.waypointTpsChanged.emit(list(self._waypoint_tp_ids))

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

    def clear_timing_constraints(self):
        if not self._timing_constraints:
            return
        self._timing_constraints.clear()
        self.timingConstraintsChanged.emit(self._timing_constraints)

    @property
    def visible_tp_tracks(self) -> Set[str]:
        return self._visible_tp_tracks

    def set_visible_tp_tracks(self, tracks: Set[str]):
        self._visible_tp_tracks = tracks
        self.visibleTpTracksChanged.emit(self._visible_tp_tracks)

    @property
    def selected_stopping_point_id(self) -> Optional[str]:
        return self._selected_stopping_point_id

    def set_selected_stopping_point(self, sl_id: Optional[str]):
        self._selected_stopping_point_id = sl_id
        self.selectedStoppingPointChanged.emit(sl_id or "")

    @property
    def segment_speed_limits(self) -> Dict[str, Dict[str, float]]:
        return self._segment_speed_limits

    def get_segment_speed_limit(self, track_id: str, target_node_id: str) -> Optional[float]:
        track_limits = self._segment_speed_limits.get(str(track_id))
        if not isinstance(track_limits, dict):
            return None
        raw = track_limits.get(str(target_node_id))
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if value < 0.0:
            return None
        return value

    def set_segment_speed_limit(
        self,
        track_id: str,
        target_node_id: str,
        speed_limit: Optional[float],
    ) -> None:
        track_key = str(track_id)
        node_key = str(target_node_id)
        current = self.get_segment_speed_limit(track_key, node_key)

        normalized: Optional[float]
        if speed_limit is None:
            normalized = None
        else:
            try:
                parsed = float(speed_limit)
            except (TypeError, ValueError):
                return
            if parsed < 0.0:
                return
            normalized = parsed

        if normalized is not None and current is not None and abs(current - normalized) <= 1e-9:
            return
        if normalized is None and current is None:
            return

        if normalized is None:
            track_limits = self._segment_speed_limits.get(track_key)
            if isinstance(track_limits, dict):
                track_limits.pop(node_key, None)
                if not track_limits:
                    self._segment_speed_limits.pop(track_key, None)
        else:
            track_limits = self._segment_speed_limits.setdefault(track_key, {})
            track_limits[node_key] = normalized

        self.segmentSpeedLimitsChanged.emit(copy.deepcopy(self._segment_speed_limits))

    def set_segment_speed_limits(self, limits: Dict[str, Dict[str, float]]) -> None:
        cleaned: Dict[str, Dict[str, float]] = {}
        for track_id, node_limits in (limits or {}).items():
            if not isinstance(node_limits, dict):
                continue
            normalized_nodes: Dict[str, float] = {}
            for target_node_id, raw_speed in node_limits.items():
                try:
                    speed = float(raw_speed)
                except (TypeError, ValueError):
                    continue
                if speed < 0.0:
                    continue
                normalized_nodes[str(target_node_id)] = speed
            if normalized_nodes:
                cleaned[str(track_id)] = normalized_nodes

        if cleaned == self._segment_speed_limits:
            return

        self._segment_speed_limits = cleaned
        self.segmentSpeedLimitsChanged.emit(copy.deepcopy(self._segment_speed_limits))

    def clear_segment_speed_limits(self) -> None:
        if not self._segment_speed_limits:
            return
        self._segment_speed_limits = {}
        self.segmentSpeedLimitsChanged.emit({})

    def clear_selection(self):
        self._current_route = []
        self._current_tracks = []
        self._selected_stopping_point_id = None
        self._start_tp_id = None
        self._end_tp_id = None
        self._waypoint_tp_ids = []
        self._segment_speed_limits = {}
        self.routeChanged.emit([])
        self.tracksChanged.emit([])
        self.selectedStoppingPointChanged.emit("")
        self.startTpChanged.emit(None)
        self.endTpChanged.emit(None)
        self.waypointTpsChanged.emit([])
        self.segmentSpeedLimitsChanged.emit({})

    def snapshot_state(self) -> dict:
        return {
            "current_route": list(self._current_route),
            "current_tracks": list(self._current_tracks),
            "timing_constraints": copy.deepcopy(self._timing_constraints),
            "visible_tp_tracks": set(self._visible_tp_tracks),
            "selected_stopping_point_id": self._selected_stopping_point_id,
            "start_tp_id": self._start_tp_id,
            "end_tp_id": self._end_tp_id,
            "waypoint_tp_ids": list(self._waypoint_tp_ids),
            "segment_speed_limits": copy.deepcopy(self._segment_speed_limits),
        }

    def restore_state(self, state: dict) -> None:
        self._current_route = list(state.get("current_route", []))
        self._current_tracks = list(state.get("current_tracks", []))
        self._timing_constraints = copy.deepcopy(state.get("timing_constraints", {}))
        self._visible_tp_tracks = set(state.get("visible_tp_tracks", set()))
        self._selected_stopping_point_id = state.get("selected_stopping_point_id")
        self._start_tp_id = state.get("start_tp_id")
        self._end_tp_id = state.get("end_tp_id")
        self._waypoint_tp_ids = list(state.get("waypoint_tp_ids", []))
        self._segment_speed_limits = copy.deepcopy(state.get("segment_speed_limits", {}))

        self.routeChanged.emit(list(self._current_route))
        self.tracksChanged.emit(list(self._current_tracks))
        self.timingConstraintsChanged.emit(dict(self._timing_constraints))
        self.visibleTpTracksChanged.emit(set(self._visible_tp_tracks))
        self.selectedStoppingPointChanged.emit(self._selected_stopping_point_id or "")
        self.startTpChanged.emit(self._start_tp_id)
        self.endTpChanged.emit(self._end_tp_id)
        self.waypointTpsChanged.emit(list(self._waypoint_tp_ids))
        self.segmentSpeedLimitsChanged.emit(copy.deepcopy(self._segment_speed_limits))
