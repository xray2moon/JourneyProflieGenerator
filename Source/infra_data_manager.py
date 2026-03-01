from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, List, Set, FrozenSet, Optional
from Source.infra_models import Node, Track, TimingPoint, StoppingLocation

class InfrastructureModel:
    """
    Pure data container for the railway infrastructure.
    """
    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.tracks: Dict[str, Track] = {}
        self.timing_points: Dict[int, TimingPoint] = {}
        self.stopping_locations: Dict[str, StoppingLocation] = {}
        self.sl_to_group: Dict[str, str] = {}
        self.simple_point_connections: Dict[str, Set[FrozenSet[str]]] = {}
        self.json_path: Optional[str] = None

    def clear(self):
        self.nodes.clear()
        self.tracks.clear()
        self.timing_points.clear()
        self.stopping_locations.clear()
        self.sl_to_group.clear()
        self.simple_point_connections.clear()
        self.json_path = None

class InfrastructureParser:
    """
    Logic for parsing EBD JSON data into an InfrastructureModel.
    """
    @staticmethod
    def parse_file(json_path: str) -> InfrastructureModel:
        p = Path(json_path)
        if not p.exists():
            raise FileNotFoundError(f"JSON file not found: {p}")

        with p.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        
        model = InfrastructureParser.parse_dict(raw)
        model.json_path = str(p)
        return model

    @staticmethod
    def parse_dict(raw: dict) -> InfrastructureModel:
        """
        Parses raw infrastructure dictionary data into a structured InfrastructureModel,
        extracting and validating nodes, tracks, timing points, and stopping locations.
        """
        model = InfrastructureModel()
        
        # Nodes
        for n in raw.get("nodes", []):
            coord = n.get("coordinate") or {}
            node = Node(
                id=n["id"],
                x=float(coord.get("x", 0.0)),
                y=float(coord.get("y", 0.0)),
                numeric_id=n.get("numericId"),
            )
            model.nodes[node.id] = node
            
            sp = n.get("simplePoint") or {}
            allowed = set()
            for c in sp.get("connections") or []:
                a = c.get("trackA")
                b = c.get("trackB")
                if a and b:
                    allowed.add(frozenset((a, b)))
            if allowed:
                model.simple_point_connections[node.id] = allowed

        # Tracks
        for t in raw.get("tracks", []):
            shaping = [(float(p["x"]), float(p["y"])) for p in (t.get("shapingPoints") or [])]
            track = Track(
                id=t["id"],
                source=t["sourceNodeId"],
                target=t["targetNodeId"],
                shaping_points=shaping,
                length_m=float(t.get("lengthMeter", 0.0)),
                numeric_id=t.get("numericId"),
            )
            model.tracks[track.id] = track

        # Timing points
        for tp in raw.get("timingPoints", []):
            timing_point = TimingPoint(
                id=int(tp["id"]),
                track_id=tp["trackId"],
                target_node_id=tp["targetNodeId"],
                distance_to_target_m=float(tp["distanceToTargetNodeInMeters"]),
                stopping_location_id=tp.get("stoppingLocationId", ""),
                segment_profile_id=int(tp.get("segmentProfileId", 0)),
            )
            model.timing_points[timing_point.id] = timing_point

        # Stopping location groups
        for g in raw.get("stoppingLocationGroups", []):
            gname = g.get("id", "")
            for entry in g.get("stoppingLocations", []):
                sl_id = entry.get("stoppingLocationId")
                if sl_id:
                    model.sl_to_group[sl_id] = gname

        # Stopping locations
        for sl in raw.get("stoppingLocations", []):
            pos = sl.get("position") or {}
            stopping_location = StoppingLocation(
                id=sl["id"],
                track_id=pos.get("trackId", ""),
                reference_node_id=pos.get("referenceNodeId", ""),
                distance_from_ref_m=float(pos.get("distanceFromRefNode", 0.0)),
                target_direction_node_id=sl.get("targetDirectionNodeId", ""),
                platform_id=sl.get("platformId", ""),
            )
            model.stopping_locations[stopping_location.id] = stopping_location

        return model
