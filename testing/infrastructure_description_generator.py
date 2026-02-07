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
        cfg = config or InfrastructureGenerationConfig()
        build_seed = self._seed if self._seed is not None else str(uuid.uuid4())
        self._current_build_seed = build_seed
        rng = random.Random(build_seed)
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

        main_node_ids: List[str] = []
        x_cursor = 0.0
        for i in range(cfg.main_node_count):
            node_id = self._uid("node", i)
            main_node_ids.append(node_id)
            x_cursor += cfg.track_length_m * rng.uniform(0.8, 1.25)
            y = rng.uniform(-220.0, 220.0)
            node_defs.append(
                {
                    "id": node_id,
                    "coordinate": {"x": round(float(x_cursor), 3), "y": round(float(y), 3)},
                    "numericId": numeric_id,
                }
            )
            numeric_id += 1

        branch_node_id = None
        if cfg.include_branch:
            branch_node_id = self._uid("node", "branch")
            branch_anchor = next(n for n in node_defs if n["id"] == main_node_ids[1])["coordinate"]
            node_defs.append(
                {
                    "id": branch_node_id,
                    "coordinate": {
                        "x": round(float(branch_anchor["x"] + rng.uniform(-300.0, 300.0)), 3),
                        "y": round(float(branch_anchor["y"] + rng.uniform(650.0, 1300.0)), 3),
                    },
                    "numericId": numeric_id,
                }
            )
            numeric_id += 1

        main_track_ids: List[str] = []
        for i in range(cfg.main_node_count - 1):
            tr_id = self._uid("track", i)
            main_track_ids.append(tr_id)
            length = max(120.0, cfg.track_length_m * rng.uniform(0.7, 1.35) + (i * 20.0))
            source_id = main_node_ids[i]
            target_id = main_node_ids[i + 1]
            source_coord = next(n for n in node_defs if n["id"] == source_id)["coordinate"]
            target_coord = next(n for n in node_defs if n["id"] == target_id)["coordinate"]
            shaping_points: List[Dict[str, float]] = []
            if rng.random() < 0.55:
                mid_x = (float(source_coord["x"]) + float(target_coord["x"])) / 2.0
                mid_y = (float(source_coord["y"]) + float(target_coord["y"])) / 2.0
                shaping_points = [
                    {
                        "x": round(mid_x + rng.uniform(-200.0, 200.0), 3),
                        "y": round(mid_y + rng.uniform(-160.0, 160.0), 3),
                    }
                ]

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

            tp_entries, timing_point_id = self._timing_points_for_track(
                track_id=tr_id,
                source_node_id=source_id,
                target_node_id=target_id,
                length=length,
                count_per_direction=cfg.timing_points_per_direction,
                tp_start_id=timing_point_id,
                forward_segment_profile_id=forward_segment_id,
                reverse_segment_profile_id=reverse_segment_id,
            )
            timing_points.extend(tp_entries)

        if branch_node_id is not None:
            branch_track_id = self._uid("track", "branch")
            main_track_ids.append(branch_track_id)
            branch_source = main_node_ids[1]
            branch_target = branch_node_id
            branch_length = max(200.0, cfg.track_length_m * rng.uniform(0.45, 0.95))
            source_coord = next(n for n in node_defs if n["id"] == branch_source)["coordinate"]
            target_coord = next(n for n in node_defs if n["id"] == branch_target)["coordinate"]
            branch_mid_x = (float(source_coord["x"]) + float(target_coord["x"])) / 2.0
            branch_mid_y = (float(source_coord["y"]) + float(target_coord["y"])) / 2.0
            track_defs.append(
                {
                    "id": branch_track_id,
                    "sourceNodeId": branch_source,
                    "targetNodeId": branch_target,
                    "shapingPoints": [
                        {
                            "x": round(branch_mid_x + rng.uniform(-120.0, 120.0), 3),
                            "y": round(branch_mid_y + rng.uniform(-100.0, 100.0), 3),
                        }
                    ],
                    "lengthMeter": round(float(branch_length), 3),
                    "numericId": numeric_id,
                }
            )
            numeric_id += 1

            allocation_sections.extend(
                [
                    self._allocation_extent(branch_track_id, branch_source, allocation_group_id, branch_length),
                    self._allocation_extent(branch_track_id, branch_target, allocation_group_id + 1, branch_length),
                ]
            )
            allocation_group_id += 2

            forward_segment_id = segment_profile_id
            segment_profiles.append(
                {
                    "trackId": branch_track_id,
                    "id": forward_segment_id,
                    "targetNodeId": branch_target,
                    "distanceSegmentStartToTargetNodeInMeters": float(branch_length),
                    "distanceSegmentEndToTargetNodeInMeters": 0.0,
                }
            )
            segment_profile_id += 1

            reverse_segment_id = segment_profile_id
            segment_profiles.append(
                {
                    "trackId": branch_track_id,
                    "id": reverse_segment_id,
                    "targetNodeId": branch_source,
                    "distanceSegmentStartToTargetNodeInMeters": float(branch_length),
                    "distanceSegmentEndToTargetNodeInMeters": 0.0,
                }
            )
            segment_profile_id += 1

            tp_entries, timing_point_id = self._timing_points_for_track(
                track_id=branch_track_id,
                source_node_id=branch_source,
                target_node_id=branch_target,
                length=branch_length,
                count_per_direction=cfg.timing_points_per_direction,
                tp_start_id=timing_point_id,
                forward_segment_profile_id=forward_segment_id,
                reverse_segment_profile_id=reverse_segment_id,
            )
            timing_points.extend(tp_entries)

            # Add switch-like constraints on the branching node.
            main_left = self._uid("track", 0)
            main_right = self._uid("track", 1)
            switch_node = next(n for n in node_defs if n["id"] == branch_source)
            switch_node["simplePoint"] = {
                "connections": [
                    {"trackA": main_left, "trackB": main_right},
                    {"trackA": main_left, "trackB": branch_track_id},
                ],
                "switchDurationSecond": 1,
                "allocationGroupId": str(allocation_group_id),
            }
            allocation_group_id += 1

        # Create a small station-like subset of stopping locations.
        if main_track_ids:
            first_track = next(t for t in track_defs if t["id"] == main_track_ids[0])
            last_track = next(t for t in track_defs if t["id"] == main_track_ids[-1])

            st1 = self._station_stopping_locations("TestStationA", first_track)
            st2 = self._station_stopping_locations("TestStationB", last_track)
            stopping_locations.extend(st1["stopping_locations"])
            stopping_locations.extend(st2["stopping_locations"])
            stopping_location_groups.append(st1["group"])
            stopping_location_groups.append(st2["group"])

        self._attach_stopping_locations_to_timing_points(timing_points, stopping_locations)

        if cfg.include_virtual_tracks:
            for i, endpoint in enumerate((main_node_ids[0], main_node_ids[-1])):
                anchor = next(n for n in node_defs if n["id"] == endpoint)
                vnode_id = f"{endpoint}_virtual_track_virtual_node"
                vtrack_id = f"{endpoint}_virtual_track"

                virtual_nodes.append(
                    {
                        "id": vnode_id,
                        "coordinate": {
                            "x": round(float(anchor["coordinate"]["x"] + (-400.0 if i == 0 else 400.0)), 3),
                            "y": round(float(anchor["coordinate"]["y"] - 350.0 + rng.uniform(-80.0, 80.0)), 3),
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
                        "lengthMeter": 10000.0,
                        "numericId": numeric_id,
                    }
                )
                numeric_id += 1

        if track_defs:
            first_track = track_defs[0]
            dps_len = float(first_track["lengthMeter"])
            start = round(min(max(5.0, dps_len * 0.05), max(5.0, dps_len * 0.25)), 3)
            end = round(min(dps_len, start + max(10.0, dps_len * 0.08)), 3)
            dps_groups.append(
                {
                    "id": self._uid("dps", 0),
                    "protectedNodeIds": [first_track["sourceNodeId"]],
                    "sections": [
                        {
                            "id": self._uid("dps-section", 0),
                            "trackSections": [
                                {
                                    "trackId": first_track["id"],
                                    "referenceNodeId": first_track["sourceNodeId"],
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
        self._current_build_seed = None
        return result

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
