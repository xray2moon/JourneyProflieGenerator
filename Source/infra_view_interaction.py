from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from collections import Counter

from PyQt6.QtCore import Qt, QPointF, QEvent
from PyQt6.QtWidgets import (
    QGraphicsItem,
    QDialog,
    QWidget,
)

from Source.infra_items import NodeItem, TrackItem, TimingPointItem
from Source.infra_ui import TimingConstraintDialog


class InfrastructureViewInteractionMixin:
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
        for tpi in self._tp_track_map.get(track_id, []):
            has_stop = False
            if tpi.tp.id in selection.timing_constraints:
                c = selection.timing_constraints[tpi.tp.id]
                if c.get("pointType") == "STOP":
                    has_stop = True
            
            should_show = self._show_all_tp or visible or has_stop
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
                    if isinstance(top, (TimingPointItem, NodeItem)):
                        item = top
                        break

                if isinstance(item, TimingPointItem):
                    if event.button() == Qt.MouseButton.LeftButton:
                        self._edit_timing_constraint(item.tp.id)
                        return True
                    if event.button() == Qt.MouseButton.RightButton:
                        self._remove_timing_constraint(item.tp.id)
                        return True

                if isinstance(item, NodeItem):
                    if event.button() == Qt.MouseButton.LeftButton:
                        if self._layout_mode != "geographic":
                            return False
                        self._extend_route_with_node(item.node.id)
                        return True

                if event.button() == Qt.MouseButton.LeftButton:
                    track_id = self._pick_track_id_near(event.scenePos())
                else:
                    track_id = None

                if self._layout_mode == "geographic" and track_id and event.button() == Qt.MouseButton.LeftButton:
                    self._toggle_track_timing_points(track_id)
                    return True

        return QWidget.eventFilter(self, obj, event)

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
        self._backend.selection.clear_selection()

    def _update_route_highlights_ui(self) -> None:
        selection = self._backend.selection
        route_nodes = set(selection.current_route)
        track_counts = Counter(selection.current_tracks)
        
        start_id = selection.current_route[0] if selection.current_route else None
        end_id = selection.current_route[-1] if selection.current_route else None

        for nid, item in self._node_items.items():
            item.set_highlight(nid in route_nodes)
            role = None
            if start_id is not None:
                if nid == start_id: role = "start"
                elif nid == end_id: role = "end"
            item.set_route_role(role)

        for tid, item in self._track_items.items():
            count = track_counts.get(tid, 0)
            item.set_route_highlight(count > 0, is_double=(count > 1))

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
        start_id = selection.current_route[0] if selection.current_route else None
        end_id = selection.current_route[-1] if selection.current_route else None
        
        start_text, start_tip = self._format_route_node_label(start_id)
        end_text, end_tip = self._format_route_node_label(end_id)

        start_label.setText(f"Start: {start_text}")
        start_label.setToolTip(start_tip)
        end_label.setText(f"End: {end_text}")
        end_label.setToolTip(end_tip)

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
        dlg = TimingConstraintDialog(self, tp_id, existing=existing)
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