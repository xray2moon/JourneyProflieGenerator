from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple


class JourneyProfileImporter:
    """Parse Journey Profile JSON and extract route reconstruction inputs."""

    def __init__(self, backend):
        self._backend = backend

    def load_file(self, file_path: str) -> Tuple[List[int], List[int], Dict[int, dict]]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Journey profile file not found: {path}")

        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        return self.load_dict(raw)

    def load_dict(self, raw: dict) -> Tuple[List[int], List[int], Dict[int, dict]]:
        model = self._backend.model
        replay_tp_ids: List[int] = []
        stop_constraints: Dict[int, dict] = self._extract_generator_timing_constraints(raw)

        for segment in raw.get("segmentProfileReferences", []):
            for tp_constraint in segment.get("timingPointConstraints", []):
                tp_id_raw = tp_constraint.get("timingPointId")
                if tp_id_raw is None:
                    continue

                try:
                    tp_id = int(tp_id_raw)
                except (TypeError, ValueError):
                    continue

                tp = model.timing_points.get(tp_id)
                if tp is None:
                    continue

                if not replay_tp_ids or replay_tp_ids[-1] != tp_id:
                    replay_tp_ids.append(tp_id)

        selected_tp_ids = self._extract_selected_tp_ids(raw, replay_tp_ids)
        if not selected_tp_ids and replay_tp_ids:
            selected_tp_ids = [replay_tp_ids[0]]
            if replay_tp_ids[-1] != replay_tp_ids[0]:
                selected_tp_ids.append(replay_tp_ids[-1])

        return replay_tp_ids, selected_tp_ids, stop_constraints

    def _extract_selected_tp_ids(self, raw: dict, replay_tp_ids: List[int]) -> List[int]:
        model = self._backend.model
        payload = raw.get("generatorRouteSelection", {})
        if not isinstance(payload, dict):
            payload = {}

        start = payload.get("startTimingPointId")
        end = payload.get("endTimingPointId")
        waypoints = payload.get("waypointTimingPointIds", [])

        ordered: List[int] = []

        def _append_if_valid(tp_id_raw) -> None:
            try:
                tp_id = int(tp_id_raw)
            except (TypeError, ValueError):
                return
            if tp_id not in model.timing_points:
                return
            if tp_id in ordered:
                return
            ordered.append(tp_id)

        _append_if_valid(start)
        if isinstance(waypoints, list):
            for tp_id_raw in waypoints:
                _append_if_valid(tp_id_raw)
        _append_if_valid(end)

        if ordered:
            return ordered

        if not replay_tp_ids:
            return []
        if replay_tp_ids[0] == replay_tp_ids[-1]:
            return [replay_tp_ids[0]]
        return [replay_tp_ids[0], replay_tp_ids[-1]]

    def _extract_generator_timing_constraints(self, raw: dict) -> Dict[int, dict]:
        model = self._backend.model
        payload = raw.get("generatorTimingConstraints", [])
        if not isinstance(payload, list):
            return {}

        constraints: Dict[int, dict] = {}
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            tp_id_raw = entry.get("timingPointId")
            try:
                tp_id = int(tp_id_raw)
            except (TypeError, ValueError):
                continue
            tp = model.timing_points.get(tp_id)
            if tp is None:
                continue

            point_type = str(entry.get("pointType", "STOP")).upper()
            if point_type not in {"STOP", "PASS"}:
                point_type = "STOP"

            constraints[tp_id] = {
                "timingPointId": tp.id,
                "trackId": tp.track_id,
                "targetNodeId": tp.target_node_id,
                "distanceToTargetNodeInMeters": tp.distance_to_target_m,
                "pointType": point_type,
                "arrivalTime": str(entry.get("arrivalTime", "") or ""),
                "departureTime": str(entry.get("departureTime", "") or ""),
            }

        return constraints
