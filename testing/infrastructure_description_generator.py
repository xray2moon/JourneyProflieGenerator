from __future__ import annotations

import json
import random
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

@dataclass(frozen=True)
class InfrastructureGenerationConfig:
    """Configuration for generating synthetic infrastructure JSON data."""

    main_node_count: int = 5
    track_length_m: float = 1000.0
    timing_points_per_direction: int = 5
    include_branch: bool = True
    include_virtual_tracks: bool = True


class InfrastructureDescriptionGenerator:
    """
    Creates synthetic infrastructure JSON files shaped like
    `ebd_v7_3_stations-infrastructure-description.json`.

    The output is random by default.
    Provide a seed for deterministic/reproducible generation.
    """

    def __init__(self, seed: Optional[str] = None):
        self._seed = str(seed) if seed is not None else None
        self._current_build_seed: Optional[str] = None

    def default_output_dir(self) -> Path:
        return Path("testing") / "testing infrastructures"

    def default_output_path(
        self,
        file_name: Optional[str] = None,
        index: Optional[int] = None,
    ) -> Path:
        if file_name:
            return self.default_output_dir() / file_name
        resolved_index = self._next_output_index() if index is None else int(index)
        return self.default_output_dir() / f"infrastructure_{resolved_index}.json"

    def build(self, config: InfrastructureGenerationConfig | None = None) -> Dict[str, Any]:
        build_seed = self._seed if self._seed is not None else str(uuid.uuid4())
        self._current_build_seed = build_seed
        try:
            rng = random.Random(build_seed)

            if config is None:
                profile = rng.choice(("compact", "corridor", "branching", "mesh"))
                if profile == "compact":
                    cfg = InfrastructureGenerationConfig(
                        main_node_count=rng.randint(4, 6),
                        track_length_m=rng.uniform(350.0, 700.0),
                        timing_points_per_direction=rng.randint(3, 6),
                        include_branch=rng.random() < 0.7,
                        include_virtual_tracks=rng.random() < 0.5,
                    )
                elif profile == "corridor":
                    cfg = InfrastructureGenerationConfig(
                        main_node_count=rng.randint(7, 11),
                        track_length_m=rng.uniform(900.0, 2200.0),
                        timing_points_per_direction=rng.randint(4, 10),
                        include_branch=rng.random() < 0.85,
                        include_virtual_tracks=rng.random() < 0.8,
                    )
                elif profile == "branching":
                    cfg = InfrastructureGenerationConfig(
                        main_node_count=rng.randint(6, 10),
                        track_length_m=rng.uniform(500.0, 1300.0),
                        timing_points_per_direction=rng.randint(5, 12),
                        include_branch=True,
                        include_virtual_tracks=rng.random() < 0.75,
                    )
                else:
                    cfg = InfrastructureGenerationConfig(
                        main_node_count=rng.randint(8, 13),
                        track_length_m=rng.uniform(450.0, 1200.0),
                        timing_points_per_direction=rng.randint(4, 9),
                        include_branch=True,
                        include_virtual_tracks=rng.random() < 0.65,
                    )
            else:
                cfg = config

            if cfg.main_node_count < 3:
                raise ValueError("main_node_count must be >= 3")
            if cfg.track_length_m <= 0:
                raise ValueError("track_length_m must be > 0")
            if cfg.timing_points_per_direction < 2:
                raise ValueError("timing_points_per_direction must be >= 2")

            node_defs: List[Dict[str, Any]] = []
            track_defs: List[Dict[str, Any]] = []
            allocation_sections: List[Dict[str, Any]] = []
            segment_profiles: List[Dict[str, Any]] = []
            timing_points: List[Dict[str, Any]] = []
            stopping_locations: List[Dict[str, Any]] = []
            stopping_location_groups: List[Dict[str, Any]] = []
            virtual_nodes: List[Dict[str, Any]] = []
            virtual_tracks: List[Dict[str, Any]] = []
            dps_groups: List[Dict[str, Any]] = []

            numeric_id = 1
            segment_profile_id = 1
            timing_point_id = 1000
            allocation_group_id = 1

            node_by_id: Dict[str, Dict[str, Any]] = {}
            edge_pairs: set[frozenset[str]] = set()
            node_to_tracks: Dict[str, List[str]] = {}

            def add_node(tag: str, x: float, y: float) -> str:
                nonlocal numeric_id
                node_id = self._uid("node", tag)
                node = {
                    "id": node_id,
                    "coordinate": {"x": round(float(x), 3), "y": round(float(y), 3)},
                    "numericId": numeric_id,
                }
                numeric_id += 1
                node_defs.append(node)
                node_by_id[node_id] = node
                return node_id

            def add_track(source_id: str, target_id: str, tag: str, *, force_shape: bool = False) -> Optional[str]:
                nonlocal numeric_id, segment_profile_id, timing_point_id, allocation_group_id
                if source_id == target_id:
                    return None
                pair = frozenset((source_id, target_id))
                if pair in edge_pairs:
                    return None
                edge_pairs.add(pair)

                tr_id = self._uid("track", tag)
                source = node_by_id[source_id]["coordinate"]
                target = node_by_id[target_id]["coordinate"]
                euclidean = ((float(target["x"]) - float(source["x"])) ** 2 + (float(target["y"]) - float(source["y"])) ** 2) ** 0.5
                length = max(90.0, euclidean * rng.uniform(0.95, 1.65))

                shaping_points: List[Dict[str, float]] = []
                shape_count = rng.choices((0, 1, 2), weights=(0.35, 0.45, 0.20))[0]
                if force_shape and shape_count == 0:
                    shape_count = 1
                for i in range(shape_count):
                    alpha = (i + 1) / float(shape_count + 1)
                    x = (1.0 - alpha) * float(source["x"]) + alpha * float(target["x"]) + rng.uniform(-320.0, 320.0)
                    y = (1.0 - alpha) * float(source["y"]) + alpha * float(target["y"]) + rng.uniform(-260.0, 260.0)
                    shaping_points.append({"x": round(x, 3), "y": round(y, 3)})

                track_defs.append(
                    {
                        "id": tr_id,
                        "sourceNodeId": source_id,
                        "targetNodeId": target_id,
                        "shapingPoints": shaping_points,
                        "lengthMeter": round(float(length), 3),
                        "numericId": numeric_id,
                    }
                )
                numeric_id += 1

                node_to_tracks.setdefault(source_id, []).append(tr_id)
                node_to_tracks.setdefault(target_id, []).append(tr_id)

                allocation_sections.extend(
                    [
                        self._allocation_extent(tr_id, source_id, allocation_group_id, length),
                        self._allocation_extent(tr_id, target_id, allocation_group_id + 1, length),
                    ]
                )
                allocation_group_id += 2

                forward_segment_id = segment_profile_id
                segment_profiles.append(
                    {
                        "trackId": tr_id,
                        "id": forward_segment_id,
                        "targetNodeId": target_id,
                        "distanceSegmentStartToTargetNodeInMeters": float(length),
                        "distanceSegmentEndToTargetNodeInMeters": 0.0,
                    }
                )
                segment_profile_id += 1

                reverse_segment_id = segment_profile_id
                segment_profiles.append(
                    {
                        "trackId": tr_id,
                        "id": reverse_segment_id,
                        "targetNodeId": source_id,
                        "distanceSegmentStartToTargetNodeInMeters": float(length),
                        "distanceSegmentEndToTargetNodeInMeters": 0.0,
                    }
                )
                segment_profile_id += 1

                tp_count = max(2, int(round(cfg.timing_points_per_direction * rng.uniform(0.55, 2.2))))
                tp_entries, timing_point_id_local = self._timing_points_for_track(
                    track_id=tr_id,
                    source_node_id=source_id,
                    target_node_id=target_id,
                    length=length,
                    count_per_direction=tp_count,
                    tp_start_id=timing_point_id,
                    forward_segment_profile_id=forward_segment_id,
                    reverse_segment_profile_id=reverse_segment_id,
                )
                timing_points.extend(tp_entries)
                timing_point_id = timing_point_id_local
                return tr_id

            # Main corridor.
            main_node_ids: List[str] = []
            x_cursor = 0.0
            y_cursor = rng.uniform(-100.0, 100.0)
            for i in range(cfg.main_node_count):
                x_cursor += cfg.track_length_m * rng.uniform(0.65, 1.35)
                y_cursor += rng.uniform(-300.0, 300.0)
                main_node_ids.append(add_node(f"main-{i}", x_cursor, y_cursor))

            main_track_ids: List[str] = []
            for i in range(cfg.main_node_count - 1):
                track_id = add_track(main_node_ids[i], main_node_ids[i + 1], f"main-{i}")
                if track_id is not None:
                    main_track_ids.append(track_id)

            # Branches / spurs.
            branch_node_ids: List[str] = []
            branch_anchors: Dict[str, str] = {}
            if cfg.include_branch:
                max_branches = max(1, min(6, cfg.main_node_count // 2 + 1))
                branch_count = rng.randint(1, max_branches)
                for b in range(branch_count):
                    anchor_idx = rng.randint(1, max(1, cfg.main_node_count - 2))
                    anchor_id = main_node_ids[anchor_idx]
                    anchor = node_by_id[anchor_id]["coordinate"]
                    angle = rng.uniform(-2.8, 2.8)
                    radius = cfg.track_length_m * rng.uniform(0.6, 1.8)
                    bx = float(anchor["x"]) + radius * (1.0 if angle >= 0 else -1.0) * rng.uniform(0.3, 1.0)
                    by = float(anchor["y"]) + radius * rng.uniform(0.35, 1.1) * (1.0 if b % 2 == 0 else -1.0)
                    branch_node_id = add_node(f"branch-{b}", bx, by)
                    branch_node_ids.append(branch_node_id)
                    branch_anchors[branch_node_id] = anchor_id
                    add_track(anchor_id, branch_node_id, f"branch-{b}", force_shape=True)

            # Cross-links to introduce loops and shortcut paths.
            cross_target = rng.randint(0, max(1, cfg.main_node_count // 2))
            attempts = 0
            cross_added = 0
            while cross_added < cross_target and attempts < 30:
                attempts += 1
                i = rng.randint(0, cfg.main_node_count - 3)
                j = rng.randint(i + 2, cfg.main_node_count - 1)
                tr = add_track(main_node_ids[i], main_node_ids[j], f"cross-{i}-{j}-{cross_added}", force_shape=True)
                if tr is not None:
                    cross_added += 1

            # Reconnect some branches back to corridor for different network styles.
            if branch_node_ids and cfg.main_node_count >= 5:
                loop_target = rng.randint(0, len(branch_node_ids))
                loop_added = 0
                attempts = 0
                while loop_added < loop_target and attempts < 25:
                    attempts += 1
                    bnode = rng.choice(branch_node_ids)
                    anchor_id = branch_anchors[bnode]
                    target_main = rng.choice(main_node_ids)
                    if target_main == anchor_id:
                        continue
                    tr = add_track(bnode, target_main, f"loop-{bnode}-{target_main}-{loop_added}", force_shape=True)
                    if tr is not None:
                        loop_added += 1

            # Station-like stopping locations on a random subset of tracks.
            if track_defs:
                station_track_count = rng.randint(2, min(6, len(track_defs)))
                chosen_tracks = rng.sample(track_defs, k=station_track_count)
                for idx, tr in enumerate(chosen_tracks):
                    station = self._station_stopping_locations(f"TestStation{idx}", tr)
                    stopping_locations.extend(station["stopping_locations"])
                    stopping_location_groups.append(station["group"])
            self._attach_stopping_locations_to_timing_points(timing_points, stopping_locations)

            # Add simple-point constraints on nodes with multiple incident tracks.
            for node_id, incident_tracks in node_to_tracks.items():
                unique_tracks = sorted(set(incident_tracks))
                degree = len(unique_tracks)
                if degree < 2:
                    continue
                if degree == 2 and rng.random() > 0.25:
                    continue
                if degree >= 3 and rng.random() > 0.9:
                    continue
                connections: List[Dict[str, str]] = []
                for i in range(len(unique_tracks)):
                    for j in range(i + 1, len(unique_tracks)):
                        connections.append({"trackA": unique_tracks[i], "trackB": unique_tracks[j]})
                if not connections:
                    continue
                node_by_id[node_id]["simplePoint"] = {
                    "connections": connections,
                    "switchDurationSecond": rng.randint(1, 3),
                    "allocationGroupId": str(allocation_group_id),
                }
                allocation_group_id += 1

            # Virtual ingress/egress tracks on randomly chosen endpoints.
            if cfg.include_virtual_tracks:
                portal_candidates = list(main_node_ids)
                for bnode in branch_node_ids:
                    if rng.random() < 0.5:
                        portal_candidates.append(bnode)
                portal_count = min(len(portal_candidates), rng.randint(2, 4))
                for idx, endpoint in enumerate(rng.sample(portal_candidates, k=portal_count)):
                    anchor = node_by_id[endpoint]["coordinate"]
                    vnode_id = f"{endpoint}_virtual_track_virtual_node"
                    vtrack_id = f"{endpoint}_virtual_track"
                    virtual_nodes.append(
                        {
                            "id": vnode_id,
                            "coordinate": {
                                "x": round(float(anchor["x"] + rng.uniform(-900.0, 900.0)), 3),
                                "y": round(float(anchor["y"] + rng.uniform(-900.0, 900.0)), 3),
                            },
                            "numericId": numeric_id,
                        }
                    )
                    numeric_id += 1
                    virtual_tracks.append(
                        {
                            "id": vtrack_id,
                            "sourceNodeId": vnode_id,
                            "targetNodeId": endpoint,
                            "shapingPoints": [],
                            "lengthMeter": round(rng.uniform(7000.0, 18000.0), 3),
                            "numericId": numeric_id,
                        }
                    )
                    numeric_id += 1

            # DPS groups on random tracks.
            if track_defs:
                dps_count = min(len(track_defs), rng.randint(1, 5))
                for idx, tr in enumerate(rng.sample(track_defs, k=dps_count)):
                    tr_len = float(tr["lengthMeter"])
                    start = round(rng.uniform(0.0, max(1.0, tr_len * 0.45)), 3)
                    span = rng.uniform(max(8.0, tr_len * 0.04), max(20.0, tr_len * 0.3))
                    end = round(min(tr_len, start + span), 3)
                    protected = [tr["sourceNodeId"]]
                    if rng.random() < 0.45:
                        protected.append(tr["targetNodeId"])
                    dps_groups.append(
                        {
                            "id": self._uid("dps", idx),
                            "protectedNodeIds": protected,
                            "sections": [
                                {
                                    "id": self._uid("dps-section", idx),
                                    "trackSections": [
                                        {
                                            "trackId": tr["id"],
                                            "referenceNodeId": tr["sourceNodeId"],
                                            "coordinateStart": start,
                                            "coordinateEnd": end,
                                        }
                                    ],
                                }
                            ],
                            "dependencyType": "DRIVE_PROTECTION_SECTION_GROUP_DEPENDENCY_EXCLUSIVE",
                        }
                    )

            result = {
                "nodes": node_defs,
                "tracks": track_defs,
                "allocationSections": allocation_sections,
                "platforms": [],
                "stoppingLocations": stopping_locations,
                "speedConstraints": [],
                "stoppingLocationGroups": stopping_location_groups,
                "segmentProfiles": segment_profiles,
                "timingPoints": timing_points,
                "virtualNodes": virtual_nodes,
                "virtualTracks": virtual_tracks,
                "blockSections": [],
                "dpsGroups": dps_groups,
            }
            self._validate(result)
            return result
        finally:
            self._current_build_seed = None

    def write_json(
        self,
        output_path: str | Path | None = None,
        config: InfrastructureGenerationConfig | None = None,
    ) -> Path:
        path = Path(output_path) if output_path is not None else self.default_output_path()
        data = self.build(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        return path

    def _uid(self, kind: str, idx: object) -> str:
        seed = self._current_build_seed or self._seed or "default-seed"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{seed}:{kind}:{idx}"))

    def _allocation_extent(
        self, track_id: str, reference_node_id: str, group_id: int, length: float
    ) -> Dict[str, Any]:
        return {
            "extent": {
                "trackId": track_id,
                "referenceNodeId": reference_node_id,
                "distanceClose": 0.0,
                "distanceFar": round(min(60.0, length / 2.0), 3),
            },
            "allocationGroupId": group_id,
        }

    def _timing_points_for_track(
        self,
        *,
        track_id: str,
        source_node_id: str,
        target_node_id: str,
        length: float,
        count_per_direction: int,
        tp_start_id: int,
        forward_segment_profile_id: int,
        reverse_segment_profile_id: int,
    ) -> tuple[List[Dict[str, Any]], int]:
        seed = self._current_build_seed or self._seed or "default-seed"
        rng = random.Random(f"{seed}:tp:{track_id}")
        tp_entries: List[Dict[str, Any]] = []
        tp_id = tp_start_id
        min_clearance = max(10.0, length * 0.05)
        max_clearance = max(min_clearance + 5.0, length - min_clearance)
        raw_positions = [rng.uniform(min_clearance, max_clearance) for _ in range(count_per_direction)]
        positions = [round(p, 3) for p in sorted(raw_positions)]

        for pos in positions:
            tp_entries.append(
                {
                    "trackId": track_id,
                    "id": tp_id,
                    "targetNodeId": target_node_id,
                    "distanceToTargetNodeInMeters": round(length - pos, 3),
                    "stoppingLocationId": "",
                    "segmentProfileId": forward_segment_profile_id,
                }
            )
            tp_id += 1

        for pos in positions:
            tp_entries.append(
                {
                    "trackId": track_id,
                    "id": tp_id,
                    "targetNodeId": source_node_id,
                    "distanceToTargetNodeInMeters": round(pos, 3),
                    "stoppingLocationId": "",
                    "segmentProfileId": reverse_segment_profile_id,
                }
            )
            tp_id += 1

        return tp_entries, tp_id

    def _station_stopping_locations(
        self, station_name: str, track: Dict[str, Any]
    ) -> Dict[str, Any]:
        seed = self._current_build_seed or self._seed or "default-seed"
        rng = random.Random(f"{seed}:station:{station_name}:{track['id']}")
        tr_id = track["id"]
        source = track["sourceNodeId"]
        target = track["targetNodeId"]
        length = float(track["lengthMeter"])
        base = self._uid("station", station_name)

        sl_a = {
            "id": f"{base}-SL-A",
            "targetDirectionNodeId": target,
            "position": {
                "trackId": tr_id,
                "referenceNodeId": source,
                "distanceFromRefNode": round(length * rng.uniform(0.15, 0.3), 3),
            },
            "platformId": "",
        }
        sl_b = {
            "id": f"{base}-SL-B",
            "targetDirectionNodeId": source,
            "position": {
                "trackId": tr_id,
                "referenceNodeId": source,
                "distanceFromRefNode": round(length * rng.uniform(0.7, 0.85), 3),
            },
            "platformId": "",
        }

        group = {
            "id": station_name,
            "stoppingLocations": [
                {"trackId": tr_id, "stoppingLocationId": sl_a["id"]},
                {"trackId": tr_id, "stoppingLocationId": sl_b["id"]},
            ],
            "borders": [],
        }
        return {"stopping_locations": [sl_a, sl_b], "group": group}

    def _attach_stopping_locations_to_timing_points(
        self, timing_points: List[Dict[str, Any]], stopping_locations: List[Dict[str, Any]]
    ) -> None:
        sl_by_track: Dict[str, List[str]] = {}
        for sl in stopping_locations:
            tr_id = sl.get("position", {}).get("trackId", "")
            if tr_id:
                sl_by_track.setdefault(tr_id, []).append(sl["id"])

        used_on_track: Dict[str, int] = {}
        for tp in timing_points:
            tr_id = tp["trackId"]
            options = sl_by_track.get(tr_id, [])
            if not options:
                continue
            idx = used_on_track.get(tr_id, 0)
            if idx < len(options):
                tp["stoppingLocationId"] = options[idx]
                used_on_track[tr_id] = idx + 1

    def _validate(self, raw: Dict[str, Any]) -> None:
        node_ids = {n["id"] for n in raw["nodes"]}
        track_ids = {t["id"] for t in raw["tracks"]}
        stopping_location_ids = {sl["id"] for sl in raw["stoppingLocations"]}

        for t in raw["tracks"]:
            if t["sourceNodeId"] not in node_ids or t["targetNodeId"] not in node_ids:
                raise ValueError(f"Track {t['id']} references unknown nodes")

        for n in raw["nodes"]:
            sp = n.get("simplePoint")
            if not sp:
                continue
            for c in sp.get("connections", []):
                if c.get("trackA") not in track_ids or c.get("trackB") not in track_ids:
                    raise ValueError(f"simplePoint on node {n['id']} references unknown track")

        for tp in raw["timingPoints"]:
            if tp["trackId"] not in track_ids:
                raise ValueError(f"Timing point {tp['id']} references unknown track")
            if tp["targetNodeId"] not in node_ids:
                raise ValueError(f"Timing point {tp['id']} references unknown node")
            sl_id = tp.get("stoppingLocationId")
            if sl_id and sl_id not in stopping_location_ids:
                raise ValueError(f"Timing point {tp['id']} references unknown stopping location")

        for sl in raw["stoppingLocations"]:
            pos = sl.get("position", {})
            if pos.get("trackId") not in track_ids:
                raise ValueError(f"Stopping location {sl['id']} references unknown track")
            if pos.get("referenceNodeId") not in node_ids:
                raise ValueError(f"Stopping location {sl['id']} references unknown reference node")

    def _next_output_index(self) -> int:
        out_dir = self.default_output_dir()
        if not out_dir.exists():
            return 0
        pattern = re.compile(r"^infrastructure_(\d+)\.json$")
        max_seen = -1
        for child in out_dir.iterdir():
            if not child.is_file():
                continue
            match = pattern.match(child.name)
            if match:
                max_seen = max(max_seen, int(match.group(1)))
        return max_seen + 1


if __name__ == "__main__":
    gen = InfrastructureDescriptionGenerator()
    written = gen.write_json()
    print(f"Generated: {written}")
