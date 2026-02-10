from __future__ import annotations
from typing import Dict, List, Optional, Tuple, Set
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtWidgets import QGraphicsScene

from Source.infra_models import Node, Track, TimingPoint, StoppingLocation
from Source.infra_items import NodeItem, TrackItem, TimingPointItem, StoppingLocationItem

class InfrastructureSceneBuilder:
    """
    Handles the creation and placement of QGraphicsItems on the scene.
    Separates the 'Building' logic from the View/Mixin logic.
    """
    def __init__(self, scene: QGraphicsScene):
        self._scene = scene
        self._current_theme = "light" # Default
        # Merge nearly co-located timing points on the same track into one marker.
        # This keeps hidden/overlapping points discoverable via the aggregated tooltip.
        self._tp_aggregation_tolerance_m = 0.25

    def set_theme(self, theme: str):
        self._current_theme = theme

    def clear(self):
        self._scene.clear()

    def build_geographic(
        self,
        nodes: Dict[str, Node],
        tracks: Dict[str, Track],
        timing_points: Dict[int, TimingPoint],
        stopping_locations: Dict[str, StoppingLocation],
        node_positions: Dict[str, QPointF],
        track_paths: Dict[str, any], # Painter paths
        tp_positions: Dict[int, QPointF],
        sl_positions: Dict[str, QPointF],
        sl_to_group: Dict[str, str],
        show_all_tp: bool,
        visible_tp_tracks: Set[str],
        timing_constraints: Dict[int, dict],
        start_tp_id: Optional[int] = None,
        end_tp_id: Optional[int] = None,
        waypoint_tp_ids: Optional[Set[int]] = None,
    ) -> Dict[str, any]:
        """
        Builds the geographic representation.
        Returns a dictionary of created items for the View to keep track of.
        """
        results = {
            "node_items": {},
            "track_items": {},
            "tp_items": {},
            "sl_items": {},
            "tp_track_map": {}
        }

        # Tracks first
        for tr_id, path in track_paths.items():
            tr = tracks[tr_id]
            item = TrackItem(tr.id, path)
            item.set_theme(self._current_theme)
            item.setAcceptHoverEvents(True)
            label = f"Track {tr.numeric_id}" if tr.numeric_id is not None else "Track"
            tip = f"{label}\nlen={tr.length_m:.0f} m\n{tr.id}"
            item.setToolTip(tip)
            item.inner_overlay().setToolTip(tip)
            item.route_overlay().setToolTip(tip)
            item.inner_overlay().setAcceptHoverEvents(False)
            item.route_overlay().setAcceptHoverEvents(False)
            item.set_timing_points_visible(show_all_tp or tr.id in visible_tp_tracks)
            
            self._scene.addItem(item)
            self._scene.addItem(item.inner_overlay())
            self._scene.addItem(item.route_overlay())
            results["track_items"][tr.id] = item
            results["tp_track_map"].setdefault(tr.id, [])

        # Nodes
        for node_id, node in nodes.items():
            pos = node_positions.get(node_id, QPointF(node.x, node.y))
            ni = NodeItem(node)
            ni.set_theme(self._current_theme)
            ni.setPos(pos)
            self._scene.addItem(ni)
            results["node_items"][node_id] = ni

        # Timing points
        def _tp_pos_from_source(tp_obj: TimingPoint) -> float:
            tr_obj = tracks.get(tp_obj.track_id)
            if tr_obj is None or tr_obj.length_m <= 0:
                return float("inf")
            if tp_obj.target_node_id == tr_obj.target:
                return tr_obj.length_m - tp_obj.distance_to_target_m
            return tp_obj.distance_to_target_m

        tp_positions_by_track: Dict[str, List[Tuple[float, TimingPoint]]] = {}
        for tp in timing_points.values():
            pos_from_source = _tp_pos_from_source(tp)
            if pos_from_source == float("inf"):
                continue
            tp_positions_by_track.setdefault(tp.track_id, []).append((pos_from_source, tp))

        ordered_groups: List[List[TimingPoint]] = []
        for track_id in sorted(tp_positions_by_track.keys()):
            members = sorted(
                tp_positions_by_track[track_id],
                key=lambda entry: (entry[0], int(entry[1].id)),
            )
            current_group: List[TimingPoint] = []
            current_center: Optional[float] = None
            current_count = 0

            for pos_from_source, tp in members:
                if not current_group:
                    current_group = [tp]
                    current_center = float(pos_from_source)
                    current_count = 1
                    continue

                if (
                    current_center is not None
                    and abs(float(pos_from_source) - current_center) <= self._tp_aggregation_tolerance_m
                ):
                    current_group.append(tp)
                    current_count += 1
                    # Keep a stable running center for the current cluster.
                    current_center += (float(pos_from_source) - current_center) / float(current_count)
                    continue

                ordered_groups.append(current_group)
                current_group = [tp]
                current_center = float(pos_from_source)
                current_count = 1

            if current_group:
                ordered_groups.append(current_group)

        for tp_group in ordered_groups:
            variants = sorted(tp_group, key=lambda tp_obj: tp_obj.id)
            primary_tp = variants[0]
            pos = tp_positions.get(primary_tp.id)
            if pos is None:
                fallback = None
                for tp_obj in variants:
                    fallback = tp_positions.get(tp_obj.id)
                    if fallback is not None:
                        break
                pos = fallback
            if pos is None:
                continue

            track_obj = tracks.get(primary_tp.track_id)
            tpi = TimingPointItem(
                primary_tp,
                pos,
                variants=variants,
                track_source_node_id=track_obj.source if track_obj else "",
                track_target_node_id=track_obj.target if track_obj else "",
                track_length_m=track_obj.length_m if track_obj else 0.0,
                node_numeric_ids={node_id: node.numeric_id for node_id, node in nodes.items()},
            )
            tpi.set_theme(self._current_theme)

            tp_ids = {tp_obj.id for tp_obj in variants}
            has_stop = any(
                (
                    tp_id in timing_constraints
                    and timing_constraints[tp_id].get("pointType") == "STOP"
                )
                for tp_id in tp_ids
            )

            waypoint_ids = waypoint_tp_ids or set()
            is_route_selected_tp = any(
                tp_id in waypoint_ids or tp_id in {start_tp_id, end_tp_id}
                for tp_id in tp_ids
            )
            is_visible = (
                show_all_tp
                or (primary_tp.track_id in visible_tp_tracks)
                or has_stop
                or is_route_selected_tp
            )
            tpi.setVisible(is_visible)
            self._scene.addItem(tpi)
            for tp_obj in variants:
                results["tp_items"][tp_obj.id] = tpi
            results["tp_track_map"].setdefault(primary_tp.track_id, []).append(tpi)

        # Stopping locations
        for sl_id, sl in stopping_locations.items():
            pos = sl_positions.get(sl_id)
            if pos is None: continue

            group = sl_to_group.get(sl_id, "")
            suffix = ""
            if "-SL-" in sl_id:
                suffix = sl_id.split("-SL-")[-1].strip()
            label = group if group else sl_id
            if group and suffix:
                label = f"{group} {suffix}"

            sli = StoppingLocationItem(sl.id, pos, label)
            sli.set_theme(self._current_theme)
            self._scene.addItem(sli)
            self._scene.addItem(sli.label_item())
            results["sl_items"][sl_id] = sli

        return results
