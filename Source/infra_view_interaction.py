from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from collections import Counter

from PyQt6.QtCore import Qt, QPointF, QEvent
from PyQt6.QtWidgets import (
    QGraphicsItem,
    QDialog,
    QWidget,
)

from Source.infra_items import NodeItem, TrackItem, TimingPointItem, StoppingLocationItem
from Source.infra_ui import TimingConstraintDialog


class InfrastructureViewInteraction:
    def __init__(self, view):
        self._view = view

    def __getattr__(self, name):
        return getattr(self._view, name)

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
            has_stop = False
            if tpi.tp.id in selection.timing_constraints:
                c = selection.timing_constraints[tpi.tp.id]
                if c.get("pointType") == "STOP":
                    has_stop = True

            # Keep route-defining timing points always visible.
            is_route_selected_tp = tpi.tp.id in {start_tp_id, end_tp_id} or tpi.tp.id in waypoint_tp_ids
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
                        self._extend_route_with_tp(item.tp.id)
                        return True
                    if event.button() == Qt.MouseButton.RightButton:
                        # Keep plain right-click focused on routing flow.
                        # Use Shift+RightClick for STOP/PASS constraint editing.
                        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                            self._edit_timing_constraint(item.tp.id)
                        else:
                            self._extend_route_with_tp(item.tp.id)
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
            info = {
                "type": "timingPoint",
                "id": item.tp.id,
                "trackId": item.tp.track_id,
                "targetNodeId": item.tp.target_node_id,
            }
        self.selectionChanged.emit(info)

    def clear_route(self) -> None:
        selection = self._backend.selection
        selection.clear_selection()
        selection.set_visible_tp_tracks(set())

        # Reset action should hide all TPs immediately.
        for track_item in self._track_items.values():
            track_item.set_timing_points_visible(False)
        for tpi in self._tp_items.values():
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
        search_from = 0
        for wp_id in selection.waypoint_tp_ids:
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

        for tp_id, item in self._tp_items.items():
            role = None
            if tp_id == start_tp_id:
                role = "start"
            elif tp_id == end_tp_id:
                role = "end"
            item.set_route_role(role)
            item.set_highlight(tp_id in waypoint_tp_ids)

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
        selection = self._backend.selection
        for tp_id, constraint in selection.timing_constraints.items():
            item = self._tp_items.get(tp_id)
            if item:
                item.set_constraint_point_type(constraint.get("pointType"))
                item.setVisible(True)

    def _edit_timing_constraint(self, tp_id: int) -> None:
        model = self._backend.model
        selection = self._backend.selection
        tp = model.timing_points.get(tp_id)
        if tp is None:
            return

        existing = selection.timing_constraints.get(tp_id)
        dlg = TimingConstraintDialog(self._view, tp_id, existing=existing)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        c = dlg.result_constraint()
        if c.get("pointType") == "PASS" and not c.get("arrivalTime") and not c.get("departureTime"):
            self._remove_timing_constraint(tp_id)
            return
            
        constraint = {
            "timingPointId": tp_id,
            "trackId": tp.track_id,
            "targetNodeId": tp.target_node_id,
            "distanceToTargetNodeInMeters": tp.distance_to_target_m,
            "pointType": c["pointType"],
            "arrivalTime": c["arrivalTime"],
            "departureTime": c["departureTime"],
        }
        selection.set_timing_constraint(tp_id, constraint)

        item = self._tp_items.get(tp_id)
        if item:
            item.set_constraint_point_type(c["pointType"])
            is_track_visible = tp.track_id in selection.visible_tp_tracks
            self._apply_track_tp_visibility(tp.track_id, is_track_visible)

    def _remove_timing_constraint(self, tp_id: int) -> None:
        selection = self._backend.selection
        if tp_id not in selection.timing_constraints:
            return
        
        track_id = selection.timing_constraints[tp_id]["trackId"]
        selection.set_timing_constraint(tp_id, None)
        
        item = self._tp_items.get(tp_id)
        if item:
            item.set_constraint_point_type(None)
            is_track_visible = track_id in selection.visible_tp_tracks
            self._apply_track_tp_visibility(track_id, is_track_visible)
