from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class Node:
    """Infrastructure graph node with optional human-readable numeric identifier."""

    id: str
    x: float
    y: float
    numeric_id: Optional[int] = None


@dataclass(frozen=True)
class Track:
    """Directed infrastructure connection between two nodes."""

    id: str
    source: str
    target: str
    shaping_points: List[Tuple[float, float]]
    length_m: float
    numeric_id: Optional[int] = None


@dataclass(frozen=True)
class TimingPoint:
    """Operational point on a track, defined by distance to a target node."""

    id: int  # integer ID
    track_id: str
    target_node_id: str
    distance_to_target_m: float
    stopping_location_id: str
    segment_profile_id: int


@dataclass(frozen=True)
class StoppingLocation:
    """Stopping/platform metadata anchored on a track and reference node."""

    id: str
    track_id: str
    reference_node_id: str
    distance_from_ref_m: float
    target_direction_node_id: str
    platform_id: str


@dataclass(frozen=True)
class SchematicSegment:
    """
    A contracted connection between two 'kept' nodes in schematic mode.

    - node_path contains original node IDs including endpoints.
    - track_ids contains all original track IDs that lie on the node_path hops.
    """

    id: str
    source: str
    target: str
    node_path: List[str]
    track_ids: List[str]
    length_m: float
