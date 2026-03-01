from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from collections import Counter

from PyQt6.QtCore import Qt, QPointF, QEvent
from PyQt6.QtWidgets import (
    QGraphicsItem,
    QDialog,
    QInputDialog,
    QMessageBox,
    QWidget,
)

from Source.infra_items import NodeItem, TrackItem, TimingPointItem, StoppingLocationItem
from Source.infra_ui import TimingConstraintDialog


class InfrastructureViewInteraction:
    MAX_UNDO_STEPS = 100

    def __init__(self, view):
        self._view = view
        self._undo_stack: List[dict] = []
        self._redo_stack: List[dict] = []
        self._restoring_undo = False
        self._update_history_buttons()

    def __getattr__(self, name):
        return getattr(self._view, name)

    def _iter_unique_tp_items(self) -> List[TimingPointItem]:
        seen: set[int] = set()
        items: List[TimingPointItem] = []
        for item in self._tp_items.values():
            item_key = id(item)
            if item_key in seen:
                continue
            seen.add(item_key)
            items.append(item)
        return items

    def _tp_ids_for_item(self, item: TimingPointItem) -> List[int]:
        if hasattr(item, "tp_ids"):
            return [int(tp_id) for tp_id in item.tp_ids()]
        return [int(item.tp.id)]

    def _resolve_click_tp_id(self, item: TimingPointItem) -> Optional[int]:
        selection = self._backend.selection
        candidate_ids = self._tp_ids_for_item(item)
        if not candidate_ids:
            return None
        if selection.end_tp_id in candidate_ids:
            return int(selection.end_tp_id)
        chosen = self._choose_best_tp_candidate(candidate_ids)
        if chosen is not None:
            return int(chosen)
        return min(candidate_ids)

    def _resolve_existing_member_tp_id(self, item: TimingPointItem) -> Optional[int]:
        selection = self._backend.selection
        candidate_ids = set(self._tp_ids_for_item(item))
        if not candidate_ids:
            return None

        if selection.end_tp_id in candidate_ids:
            return int(selection.end_tp_id)
        for waypoint_tp_id in selection.waypoint_tp_ids:
            if waypoint_tp_id in candidate_ids:
                return int(waypoint_tp_id)
        if selection.start_tp_id in candidate_ids:
            return int(selection.start_tp_id)
        for constrained_tp_id in selection.timing_constraints.keys():
            if constrained_tp_id in candidate_ids:
                return int(constrained_tp_id)
        return self._resolve_click_tp_id(item)

    def _route_matching_tp_ids(self, candidate_tp_ids: List[int]) -> List[int]:
        selection = self._backend.selection
        model = self._backend.model

        if not selection.current_tracks or len(selection.current_route) < 2:
            return []

        unique_candidates: List[int] = []
        for tp_id in candidate_tp_ids:
            if tp_id in unique_candidates:
                continue
            if tp_id not in model.timing_points:
                continue
            unique_candidates.append(int(tp_id))
        if not unique_candidates:
            return []

        from Source.journey_profile_exporter import JourneyProfileExporter
        exporter = JourneyProfileExporter(self._backend)
        traversal_ranges = exporter._compute_traversal_ranges(selection, model)

        matched: List[int] = []
        for tp_id in unique_candidates:
            tp = model.timing_points.get(tp_id)
            tp_pct = exporter._tp_pct_from_source(tp_id)
            if tp is None or tp_pct is None:
                continue

            is_on_route = False
            for i, track_id in enumerate(selection.current_tracks):
                if tp.track_id != track_id:
                    continue
                if i + 1 >= len(selection.current_route):
                    continue

                track = model.tracks.get(track_id)
                if track is None:
                    continue

                s_pct, e_pct = traversal_ranges[i] if i < len(traversal_ranges) else (0.0, 1.0)
                lo = min(s_pct, e_pct) - 1e-6
                hi = max(s_pct, e_pct) + 1e-6
                if tp_pct < lo or tp_pct > hi:
                    continue

                v = selection.current_route[i + 1]
                preferred_target_node_id = track.target if v == track.target else track.source
                if tp.target_node_id != preferred_target_node_id:
                    continue

                is_on_route = True
                break

            if is_on_route:
                matched.append(tp_id)

        return matched

    def _node_display_id(self, node_id: str) -> str:
        node = self._backend.model.nodes.get(node_id)
        numeric_id = getattr(node, "numeric_id", None) if node is not None else None
        return str(numeric_id) if numeric_id is not None else str(node_id)

    def _prompt_stop_tp_choice(
        self,
        route_tp_ids: List[int],
        *,
        preferred_tp_id: Optional[int] = None,
    ) -> Optional[int]:
        model = self._backend.model
        options: List[Tuple[str, int]] = []
        for tp_id in route_tp_ids:
            tp = model.timing_points.get(tp_id)
            if tp is None:
                continue
            target_node_display = self._node_display_id(tp.target_node_id)
            options.append((f"TP {int(tp.id)} (towards node {target_node_display})", int(tp.id)))
        if not options:
            return None

        initial_index = 0
        if preferred_tp_id is not None:
            for idx, (_, tp_id) in enumerate(options):
                if tp_id == int(preferred_tp_id):
                    initial_index = idx
                    break

        labels = [label for label, _ in options]
        chosen_label, ok = QInputDialog.getItem(
            self._view,
            "Choose Route Direction TP",
            "This marker is on the route in both directions.\nChoose which TP to mark as STOP:",
            labels,
            initial_index,
            False,
        )
        if not ok:
            return None

        for label, tp_id in options:
            if label == chosen_label:
                return tp_id
        return None

    def _constraint_point_type_for_item(self, item: TimingPointItem) -> Optional[str]:
        selection = self._backend.selection
        marker_point_types: List[str] = []
        for tp_id in self._tp_ids_for_item(item):
            constraint = selection.timing_constraints.get(tp_id)
            if not isinstance(constraint, dict):
                continue
            point_type = str(constraint.get("pointType", "")).upper()
            if point_type in {"STOP", "PASS"}:
                marker_point_types.append(point_type)
        if "STOP" in marker_point_types:
            return "STOP"
        if "PASS" in marker_point_types:
            return "PASS"
        return None

    def _set_hovered_track(self, track_id: Optional[str]) -> None:
        prev = getattr(self, "_hover_track_id", None)
        if prev == track_id:
            return
        if isinstance(prev, str):
            prev_item = self._track_items.get(prev)
            if prev_item:
                prev_item.set_hover_highlight(False)
        if isinstance(track_id, str):
            item = self._track_items.get(track_id)
            if item:
                item.set_hover_highlight(True)
        self._hover_track_id = track_id

    def _can_start_background_pan(self, scene_pos: QPointF) -> bool:
        if self._layout_mode == "topological":
            return True

        for cand in self._scene.items(scene_pos):
            top = cand.topLevelItem()
            if isinstance(top, (TimingPointItem, NodeItem)):
                return False

        return self._pick_track_id_near(scene_pos) is None

    def _track_id_from_item(self, item: Optional[QGraphicsItem]) -> Optional[str]:
        if item is None:
            return None
        if isinstance(item, TrackItem):
            return item.track_id
        data = item.data(0)
        model = self._backend.model
        if isinstance(data, str) and data in model.tracks:
            return data
        return None

    def _toggle_track_timing_points(self, track_id: str) -> None:
        selection = self._backend.selection
        visible_tp_tracks = selection.visible_tp_tracks
        
        if not self._keep_selection and track_id not in visible_tp_tracks:
            old_visible = list(visible_tp_tracks)
            selection.set_visible_tp_tracks(set())
            for old_id in old_visible:
                self._apply_track_tp_visibility(old_id, False)

        new_visible_tracks = set(selection.visible_tp_tracks)
        is_visible = track_id not in new_visible_tracks
        if is_visible:
            new_visible_tracks.add(track_id)
        else:
            new_visible_tracks.discard(track_id)
        
        selection.set_visible_tp_tracks(new_visible_tracks)
        self._apply_track_tp_visibility(track_id, is_visible)

    def _apply_track_tp_visibility(self, track_id: str, visible: bool) -> None:
        selection = self._backend.selection
        start_tp_id = selection.start_tp_id
        end_tp_id = selection.end_tp_id
        waypoint_tp_ids = set(selection.waypoint_tp_ids)
        for tpi in self._tp_track_map.get(track_id, []):
            tp_ids = self._tp_ids_for_item(tpi)
            has_stop = any(
                (
                    tp_id in selection.timing_constraints
                    and selection.timing_constraints[tp_id].get("pointType") == "STOP"
                )
                for tp_id in tp_ids
            )

            # Keep route-defining timing points always visible.
            is_route_selected_tp = any(
                tp_id in {start_tp_id, end_tp_id} or tp_id in waypoint_tp_ids
                for tp_id in tp_ids
            )
            should_show = self._show_all_tp or visible or has_stop or is_route_selected_tp
            tpi.setVisible(should_show)
            
            if not should_show:
                tpi.setSelected(False)
                
        track_item = self._track_items.get(track_id)
        if track_item:
            track_item.set_timing_points_visible(visible)

    def eventFilter(self, obj, event):
        if obj is self._scene:
            if event.type() == QEvent.Type.GraphicsSceneMouseMove:
                if self._layout_mode not in {"geographic"}:
                    self._set_hovered_track(None)
                elif event.buttons() == Qt.MouseButton.NoButton:
                    tol_px = 4.0
                    tol_scene = self._scene_distance_for_view_pixels(tol_px)
                    tol_sq = tol_scene * tol_scene

                    hovered: Optional[str] = None
                    model = self._backend.model
                    for cand in self._scene.items(event.scenePos()):
                        tid = self._track_id_from_item(cand.topLevelItem())
                        if not tid:
                            continue
                        pts = self._polyline_points_for_track(model.tracks[tid])
                        if not pts:
                            continue
                        d = self._min_dist_sq_to_polyline(event.scenePos(), pts)
                        if d <= tol_sq:
                            hovered = tid
                            break

                    if hovered is None:
                        hovered = self._pick_track_id_near(event.scenePos(), tolerance_px=tol_px)
                    self._set_hovered_track(hovered)

            if event.type() == QEvent.Type.GraphicsSceneMousePress:
                item: Optional[QGraphicsItem] = None
                for cand in self._scene.items(event.scenePos()):
                    top = cand.topLevelItem()
                    if isinstance(top, (TimingPointItem, NodeItem, StoppingLocationItem)):
                        item = top
                        break

                if isinstance(item, TimingPointItem):
                    if event.button() == Qt.MouseButton.LeftButton:
                        resolved_tp_id = self._resolve_click_tp_id(item)
                        if resolved_tp_id is None:
                            return True
                        self._push_undo_snapshot()
                        self._extend_route_with_tp(resolved_tp_id)
                        return True
                    if event.button() == Qt.MouseButton.RightButton:
                        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                            selection = self._backend.selection
                            route_tp_ids = set(selection.waypoint_tp_ids)
                            if selection.start_tp_id is not None:
                                route_tp_ids.add(selection.start_tp_id)
                            if selection.end_tp_id is not None:
                                route_tp_ids.add(selection.end_tp_id)

                            candidate_ids = self._tp_ids_for_item(item)
                            tp_id_to_remove: Optional[int] = None
                            for preferred_tp_id in (
                                [selection.end_tp_id]
                                + list(selection.waypoint_tp_ids)
                                + [selection.start_tp_id]
                            ):
                                if preferred_tp_id is None:
                                    continue
                                if preferred_tp_id in route_tp_ids and preferred_tp_id in candidate_ids:
                                    tp_id_to_remove = int(preferred_tp_id)
                                    break
                            if tp_id_to_remove is None:
                                for candidate_tp_id in candidate_ids:
                                    if candidate_tp_id in route_tp_ids:
                                        tp_id_to_remove = int(candidate_tp_id)
                                        break

                            if tp_id_to_remove is not None:
                                self._push_undo_snapshot()
                                self._remove_tp_from_route(tp_id_to_remove)
                            else:
                                item.setSelected(False)
                        else:
                            resolved_tp_id = self._resolve_existing_member_tp_id(item)
                            if resolved_tp_id is not None:
                                self._edit_timing_constraint(
                                    resolved_tp_id,
                                    marker_tp_ids=self._tp_ids_for_item(item),
                                )
                        return True

                if isinstance(item, StoppingLocationItem):
                    if event.button() == Qt.MouseButton.LeftButton:
                        return False # Disabled routing via SL

                if isinstance(item, NodeItem):
                    if event.button() == Qt.MouseButton.LeftButton:
                        return False # Disabled routing via Node

                if event.button() == Qt.MouseButton.LeftButton:
                    track_id = self._pick_track_id_near(event.scenePos())
                else:
                    track_id = None

                if self._layout_mode == "geographic" and track_id and event.button() == Qt.MouseButton.LeftButton:
                    if getattr(self, "_selected_segment_track_id", None) == track_id:
                        self.set_selected_segment_track(None)
                    else:
                        self.set_selected_segment_track(track_id)
                    self._toggle_track_timing_points(track_id)
                    return True

        return QWidget.eventFilter(self._view, obj, event)

    def _on_selection_changed(self) -> None:
        sel = self._scene.selectedItems()
        if not sel:
            self.selectionChanged.emit({})
            return

        item = sel[0]
        info: Dict[str, Any] = {}
        if isinstance(item, NodeItem):
            info = {"type": "node", "id": item.node.id, "numericId": item.node.numeric_id}
        elif isinstance(item, TimingPointItem):
            marker_tp_ids = self._tp_ids_for_item(item)
            resolved_tp_id = self._resolve_click_tp_id(item)
            info = {
                "type": "timingPoint",
                "id": resolved_tp_id if resolved_tp_id is not None else item.tp.id,
                "timingPointIds": marker_tp_ids,
                "trackId": item.tp.track_id,
            }
            if resolved_tp_id is not None:
                resolved_tp = self._backend.model.timing_points.get(resolved_tp_id)
                if resolved_tp is not None:
                    info["targetNodeId"] = resolved_tp.target_node_id
            if "targetNodeId" not in info:
                info["targetNodeId"] = item.tp.target_node_id
        self.selectionChanged.emit(info)

    def clear_route(self) -> None:
        self._push_undo_snapshot()
        selection = self._backend.selection
        selection.clear_timing_constraints()
        selection.clear_selection()
        selection.set_visible_tp_tracks(set())
        self.set_selected_segment_track(None)

        # Reset action should hide all TPs immediately.
        for track_item in self._track_items.values():
            track_item.set_timing_points_visible(False)
        for tpi in self._iter_unique_tp_items():
            tpi.set_constraint_point_type(None)
            tpi.setVisible(False)
            tpi.setSelected(False)

    def update_route_highlights_ui(self) -> None:
        selection = self._backend.selection
        model = self._backend.model
        route_nodes = selection.current_route
        route_tracks = selection.current_tracks
        
        node_ids_set = set(route_nodes)
        
        # Calculate traversals for each track in order
        # track_id -> list of "forward" or "backward"
        track_traversals: Dict[str, List[str]] = {}
        # Also keep track of the sequence of (track_id, direction) in the route
        route_traversal_sequence: List[Tuple[str, str]] = []

        for i in range(len(route_tracks)):
            tid = route_tracks[i]
            if tid not in model.tracks:
                continue
            
            if i + 1 >= len(route_nodes):
                break
                
            u = route_nodes[i]
            v = route_nodes[i+1]
            tr = model.tracks[tid]
            
            direction = "forward" if (u == tr.source and v == tr.target) else "backward"
            
            if tid not in track_traversals:
                track_traversals[tid] = []
            track_traversals[tid].append(direction)
            route_traversal_sequence.append((tid, direction))

        # Determine which tracks are "double" in the context of this route
        # (either traversed both ways, or traversed more than once)
        is_double_in_route = {tid: len(dirs) > 1 for tid, dirs in track_traversals.items()}
        
        # Calculate offsets for each step in the sequence
        spacing = 7.0
        sequence_offsets: List[Tuple[float, float]] = [] # list of (start_off, end_off) for each step
        
        for i, (tid, direction) in enumerate(route_traversal_sequence):
            # Target offset for this direction
            target = (spacing / 2.0) if direction == "forward" else (-spacing / 2.0)
            
            # If it's a double track, it's always at the target offset
            if is_double_in_route[tid]:
                s_off = e_off = target
            else:
                # It's a single track. Should it taper?
                s_off = 0.0
                e_off = 0.0
                
                # Check previous step in route
                if i > 0:
                    prev_tid, prev_dir = route_traversal_sequence[i-1]
                    if is_double_in_route[prev_tid]:
                        s_off = target
                
                # Check next step in route
                if i < len(route_traversal_sequence) - 1:
                    next_tid, next_dir = route_traversal_sequence[i+1]
                    if is_double_in_route[next_tid]:
                        e_off = target
            
            sequence_offsets.append((s_off, e_off))

        # Map these back to track_id -> list of (s_off, e_off) and list of (s_pct, e_pct)
        track_to_offsets: Dict[str, List[Tuple[float, float]]] = {}
        track_to_ranges: Dict[str, List[Tuple[float, float]]] = {}

        start_tp_id = selection.start_tp_id
        end_tp_id = selection.end_tp_id
        waypoint_tp_ids = set(selection.waypoint_tp_ids)
        
        start_tp = model.timing_points.get(start_tp_id) if start_tp_id is not None else None
        end_tp = model.timing_points.get(end_tp_id) if end_tp_id is not None else None
        traversal_local_indices: List[int] = []

        def _tp_pct_from_source(tp_id: Optional[int]) -> Optional[float]:
            if tp_id is None:
                return None
            tp_obj = model.timing_points.get(tp_id)
            if not tp_obj:
                return None
            tr_obj = model.tracks.get(tp_obj.track_id)
            if not tr_obj or tr_obj.length_m <= 0:
                return None
            pos = (
                tr_obj.length_m - tp_obj.distance_to_target_m
                if tp_obj.target_node_id == tr_obj.target
                else tp_obj.distance_to_target_m
            )
            pct = pos / tr_obj.length_m
            return max(0.0, min(1.0, pct))

        for i, ((tid, direction), offsets) in enumerate(zip(route_traversal_sequence, sequence_offsets)):
            if tid not in track_to_offsets:
                track_to_offsets[tid] = []
                track_to_ranges[tid] = []
            
            track_to_offsets[tid].append(offsets)
            tr = model.tracks[tid]
            local_idx = len(track_to_ranges[tid])
            traversal_local_indices.append(local_idx)
            
            # Start and End absolute percentages on the track (0.0 = source, 1.0 = target)
            # Default: whole track in direction of traversal
            if direction == "forward":
                s_pct, e_pct = 0.0, 1.0
            else:
                s_pct, e_pct = 1.0, 0.0

            # Adjust first track if there is a start TP
            if i == 0 and start_tp and start_tp.track_id == tid:
                # Absolute position of start TP from tr.source
                tp_pos = (tr.length_m - start_tp.distance_to_target_m) if start_tp.target_node_id == tr.target else start_tp.distance_to_target_m
                if tr.length_m > 0:
                    s_pct = tp_pos / tr.length_m

            # Adjust last track if there is an end TP
            if i == len(route_traversal_sequence) - 1 and end_tp and end_tp.track_id == tid:
                # Absolute position of end TP from tr.source
                tp_pos = (tr.length_m - end_tp.distance_to_target_m) if end_tp.target_node_id == tr.target else end_tp.distance_to_target_m
                if tr.length_m > 0:
                    e_pct = tp_pos / tr.length_m

            track_to_ranges[tid].append((s_pct, e_pct))

        ordered_tp_ids: List[int] = []
        if start_tp_id is not None:
            ordered_tp_ids.append(start_tp_id)
        for w in selection.waypoint_tp_ids:
            if w not in ordered_tp_ids:
                ordered_tp_ids.append(w)
        if end_tp_id is not None and end_tp_id not in ordered_tp_ids:
            ordered_tp_ids.append(end_tp_id)

        # Waypoint-aware clipping for same-track reversals: clip previous traversal
        # at waypoint and start the opposite traversal from that same TP position.
        search_from = 0
        for tp_a_id, tp_b_id in zip(ordered_tp_ids, ordered_tp_ids[1:]):
            tp_a = model.timing_points.get(tp_a_id)
            tp_b = model.timing_points.get(tp_b_id)
            if not tp_a or not tp_b or tp_a.track_id != tp_b.track_id:
                continue

            pct_a = _tp_pct_from_source(tp_a_id)
            pct_b = _tp_pct_from_source(tp_b_id)
            if pct_a is None or pct_b is None:
                continue

            reversal_pair: Optional[Tuple[int, int]] = None
            for idx in range(search_from, len(route_traversal_sequence) - 1):
                tid_i, dir_i = route_traversal_sequence[idx]
                tid_j, dir_j = route_traversal_sequence[idx + 1]
                if tid_i != tp_a.track_id or tid_j != tp_a.track_id:
                    continue
                if dir_i == dir_j:
                    continue
                reversal_pair = (idx, idx + 1)
                break

            if reversal_pair is None:
                continue

            i_prev, i_next = reversal_pair

            # Only clip when the direction change is consistent with a
            # reversal at tp_a's position.  If both TPs are on the same
            # side of the turn (e.g. both before the track endpoint where
            # the actual U-turn occurs), skip and let the per-waypoint
            # loop below handle clipping at the real reversal TP.
            dir_prev = route_traversal_sequence[i_prev][1]
            dir_next = route_traversal_sequence[i_next][1]
            if dir_prev == "forward" and dir_next == "backward" and pct_a < pct_b:
                continue
            if dir_prev == "backward" and dir_next == "forward" and pct_a > pct_b:
                continue

            prev_tid = route_traversal_sequence[i_prev][0]
            prev_local = traversal_local_indices[i_prev]
            prev_s, prev_e = track_to_ranges[prev_tid][prev_local]
            track_to_ranges[prev_tid][prev_local] = (prev_s, pct_a)

            next_tid = route_traversal_sequence[i_next][0]
            next_local = traversal_local_indices[i_next]
            _, next_e = track_to_ranges[next_tid][next_local]
            track_to_ranges[next_tid][next_local] = (pct_a, pct_b if tp_b.track_id == next_tid else next_e)

            search_from = i_next

        # Also anchor any direction change on the same track to an explicit waypoint TP
        # (even when adjacent selected TPs are on different tracks).
        # Only process waypoints that are actual reversal/STOP points so that
        # pass-through waypoints do not incorrectly consume a direction change.
        search_from = 0
        for wp_id in selection.waypoint_tp_ids:
            constraint = selection.timing_constraints.get(wp_id)
            if not constraint or constraint.get("pointType") != "STOP":
                continue
            wp = model.timing_points.get(wp_id)
            if not wp:
                continue
            wp_pct = _tp_pct_from_source(wp_id)
            if wp_pct is None:
                continue

            reversal_pair: Optional[Tuple[int, int]] = None
            for idx in range(search_from, len(route_traversal_sequence) - 1):
                tid_i, dir_i = route_traversal_sequence[idx]
                tid_j, dir_j = route_traversal_sequence[idx + 1]
                if tid_i != wp.track_id or tid_j != wp.track_id:
                    continue
                if dir_i == dir_j:
                    continue
                reversal_pair = (idx, idx + 1)
                break

            if reversal_pair is None:
                continue

            i_prev, i_next = reversal_pair
            prev_tid = route_traversal_sequence[i_prev][0]
            prev_local = traversal_local_indices[i_prev]
            prev_s, _ = track_to_ranges[prev_tid][prev_local]
            track_to_ranges[prev_tid][prev_local] = (prev_s, wp_pct)

            next_tid = route_traversal_sequence[i_next][0]
            next_local = traversal_local_indices[i_next]
            _, next_e = track_to_ranges[next_tid][next_local]
            track_to_ranges[next_tid][next_local] = (wp_pct, next_e)
            search_from = i_next

        start_id = route_nodes[0] if route_nodes else None
        end_id = route_nodes[-1] if route_nodes else None
        
        selected_sp_id = selection.selected_stopping_point_id

        for nid, item in self._node_items.items():
            item.set_highlight(nid in node_ids_set)
            item.set_route_role(None) # Nodes no longer have roles in the new logic

        for tid, item in self._track_items.items():
            traversals = track_traversals.get(tid, [])
            offsets = track_to_offsets.get(tid, [])
            ranges = track_to_ranges.get(tid, [])
            item.set_route_highlight(
                len(traversals) > 0, 
                traversals=traversals, 
                traversal_offsets=offsets,
                traversal_ranges=ranges
            )

        for sl_id, item in self._sl_items.items():
            role = "end" if sl_id == selected_sp_id else None
            item.set_route_role(role)

        for item in self._iter_unique_tp_items():
            member_ids = set(self._tp_ids_for_item(item))
            role = None
            if start_tp_id in member_ids:
                role = "start"
            elif end_tp_id in member_ids:
                role = "end"
            is_waypoint = bool(member_ids.intersection(waypoint_tp_ids))
            is_route_selected_tp = role is not None or is_waypoint

            item.set_route_role(role)
            item.set_highlight(is_waypoint)

            has_stop_constraint = any(
                (
                    member_id in selection.timing_constraints
                    and selection.timing_constraints[member_id].get("pointType") == "STOP"
                )
                for member_id in member_ids
            )
            is_track_visible = item.tp.track_id in selection.visible_tp_tracks

            should_show = (
                self._show_all_tp
                or is_track_visible
                or has_stop_constraint
                or is_route_selected_tp
            )
            item.setVisible(should_show)
            if not should_show:
                item.setSelected(False)

        self._update_route_status_labels()

    def _format_route_node_label(self, node_id: Optional[str]) -> Tuple[str, str]:
        if not node_id:
            return "-", "No node selected"
        node = self._backend.model.nodes.get(node_id)
        if node and node.numeric_id is not None:
            return str(node.numeric_id), f"Node {node.numeric_id}\n{node.id}"
        return node_id or "-", node_id or ""

    def _update_route_status_labels(self) -> None:
        start_label = getattr(self, "_route_start_label", None)
        end_label = getattr(self, "_route_end_label", None)
        if start_label is None or end_label is None:
            return

        selection = self._backend.selection
        start_tp_id = selection.start_tp_id
        end_tp_id = selection.end_tp_id
        
        start_text = str(start_tp_id) if start_tp_id is not None else "-"
        end_text = str(end_tp_id) if end_tp_id is not None else "-"

        start_label.setText(f"Start TP: {start_text}")
        end_label.setText(f"End TP: {end_text}")

    def _restore_timing_point_markers(self) -> None:
        for item in self._iter_unique_tp_items():
            marker_point_type = self._constraint_point_type_for_item(item)
            item.set_constraint_point_type(marker_point_type)
            if marker_point_type is not None:
                item.setVisible(True)

    def _edit_timing_constraint(
        self,
        tp_id: int,
        *,
        marker_tp_ids: Optional[List[int]] = None,
    ) -> None:
        model = self._backend.model
        selection = self._backend.selection
        tp = model.timing_points.get(tp_id)
        if tp is None:
            return

        marker_ids = [int(x) for x in (marker_tp_ids or [tp_id])]
        if tp_id not in marker_ids:
            marker_ids.append(tp_id)

        existing = selection.timing_constraints.get(tp_id)
        dlg = TimingConstraintDialog(self._view, tp_id, existing=existing)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        c = dlg.result_constraint()
        target_tp_id = tp_id
        if c.get("pointType") == "STOP":
            route_tp_ids = self._route_matching_tp_ids(marker_ids)
            if not route_tp_ids:
                QMessageBox.warning(
                    self._view,
                    "Stop Not On Route",
                    "STOP constraints can only be set on timing points that are on the current route.",
                )
                return
            if len(route_tp_ids) == 1:
                target_tp_id = route_tp_ids[0]
            else:
                chosen_tp_id = self._prompt_stop_tp_choice(
                    route_tp_ids,
                    preferred_tp_id=tp_id,
                )
                if chosen_tp_id is None:
                    return
                target_tp_id = chosen_tp_id

        if c.get("pointType") == "PASS" and not c.get("arrivalTime") and not c.get("departureTime"):
            self._remove_timing_constraint(target_tp_id)
            return

        target_tp = model.timing_points.get(target_tp_id)
        if target_tp is None:
            return

        constraint = {
            "timingPointId": target_tp_id,
            "trackId": target_tp.track_id,
            "targetNodeId": target_tp.target_node_id,
            "distanceToTargetNodeInMeters": target_tp.distance_to_target_m,
            "pointType": c["pointType"],
            "arrivalTime": c["arrivalTime"],
            "departureTime": c["departureTime"],
        }
        existing_target = selection.timing_constraints.get(target_tp_id)
        if existing_target == constraint:
            return

        self._push_undo_snapshot()
        selection.set_timing_constraint(target_tp_id, constraint)

        item = self._tp_items.get(target_tp_id)
        if item:
            item.set_constraint_point_type(self._constraint_point_type_for_item(item))
            is_track_visible = target_tp.track_id in selection.visible_tp_tracks
            self._apply_track_tp_visibility(target_tp.track_id, is_track_visible)

    def _remove_timing_constraint(self, tp_id: int) -> None:
        selection = self._backend.selection
        if tp_id not in selection.timing_constraints:
            return

        self._push_undo_snapshot()
        track_id = selection.timing_constraints[tp_id]["trackId"]
        selection.set_timing_constraint(tp_id, None)
        
        item = self._tp_items.get(tp_id)
        if item:
            item.set_constraint_point_type(self._constraint_point_type_for_item(item))
            is_track_visible = track_id in selection.visible_tp_tracks
            self._apply_track_tp_visibility(track_id, is_track_visible)

    def _push_undo_snapshot(self) -> None:
        if self._restoring_undo:
            return
        selection = self._backend.selection
        snapshot = selection.snapshot_state()
        if self._undo_stack and self._undo_stack[-1] == snapshot:
            return
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > self.MAX_UNDO_STEPS:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._update_history_buttons()

    def undo_last_change(self) -> None:
        if not self._undo_stack:
            return
        current_state = self._backend.selection.snapshot_state()
        previous_state = self._undo_stack.pop()
        self._redo_stack.append(current_state)
        if len(self._redo_stack) > self.MAX_UNDO_STEPS:
            self._redo_stack.pop(0)
        self._restoring_undo = True
        try:
            self._backend.selection.restore_state(previous_state)
        finally:
            self._restoring_undo = False
        self._update_history_buttons()

    def redo_last_change(self) -> None:
        if not self._redo_stack:
            return
        current_state = self._backend.selection.snapshot_state()
        next_state = self._redo_stack.pop()
        self._undo_stack.append(current_state)
        if len(self._undo_stack) > self.MAX_UNDO_STEPS:
            self._undo_stack.pop(0)
        self._restoring_undo = True
        try:
            self._backend.selection.restore_state(next_state)
        finally:
            self._restoring_undo = False
        self._update_history_buttons()

    def _update_history_buttons(self) -> None:
        self._view.update_history_buttons(
            can_undo=bool(self._undo_stack),
            can_redo=bool(self._redo_stack),
        )
