from __future__ import annotations

from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer
from PyQt6.QtWidgets import QGraphicsView

from Source.infra_items import NodeItem, TrackItem, TimingPointItem, StoppingLocationItem


class InfrastructureViewScene:
    def __init__(self, view):
        self._host = view
        self._view = view._view

    def __getattr__(self, name):
        return getattr(self._host, name)

    def _on_layout_mode_changed(self, mode_text: str) -> None:
        lowered = mode_text.lower().strip()
        if lowered.startswith("schem") or lowered.startswith("topo"):
            mode = "topological"
        else:
            mode = "geographic"
        if mode == self._layout_mode:
            return
        self._layout_mode = mode
        self._rebuild_scene()
        self._update_legend_text()
        self._initial_fit_done = False
        QTimer.singleShot(0, self._fit_to_scene)

    # -----------
    # Loading
    # -----------

    def _rebuild_scene(self) -> None:
        self._scene_builder.clear()
        self._host._node_items.clear()
        self._host._track_items.clear()
        self._host._tp_items.clear()
        self._host._sl_items.clear()
        self._host._tp_track_map.clear()

        model = self._backend.model
        selection = self._backend.selection

        if self._layout_mode == "topological":
            self._rebuild_schematic_scene()
            return

        self._host._node_positions = self._compute_node_positions()
        
        track_paths = {}
        for tr_id, tr in model.tracks.items():
            path = self._track_to_path(tr)
            if path: track_paths[tr_id] = path
            
        tp_positions = {}
        for tp_id, tp in model.timing_points.items():
            pos = self._timing_point_position(tp)
            if pos: tp_positions[tp_id] = pos
            
        sl_positions = {}
        for sl_id, sl in model.stopping_locations.items():
            pos = self._stopping_location_position(sl)
            if pos: sl_positions[sl_id] = pos

        self._scene_builder.set_theme(self._current_theme)
        
        build_results = self._scene_builder.build_geographic(
            nodes=model.nodes,
            tracks=model.tracks,
            timing_points=model.timing_points,
            stopping_locations=model.stopping_locations,
            node_positions=self._host._node_positions,
            track_paths=track_paths,
            tp_positions=tp_positions,
            sl_positions=sl_positions,
            sl_to_group=model.sl_to_group,
            show_all_tp=self._show_all_tp,
            visible_tp_tracks=selection.visible_tp_tracks,
            timing_constraints=selection.timing_constraints,
            start_tp_id=selection.start_tp_id,
            end_tp_id=selection.end_tp_id,
            waypoint_tp_ids=set(selection.waypoint_tp_ids),
        )
        
        self._host._node_items = build_results["node_items"]
        self._host._track_items = build_results["track_items"]
        self._host._tp_items = build_results["tp_items"]
        self._host._sl_items = build_results["sl_items"]
        self._host._tp_track_map = build_results["tp_track_map"]

        self._scene.installEventFilter(self._host)
        self._restore_timing_point_markers()
        self.update_route_highlights_ui()

    def _rebuild_schematic_scene(self) -> None:
        """
        Schematic view is intentionally disabled.

        This project currently only supports the geographic rendering mode.
        """
        self._host._node_positions = {}
        self._scene.setSceneRect(QRectF(-1000.0, -1000.0, 2000.0, 2000.0))
        self._scene.installEventFilter(self._host)

    def _fit_to_scene(self) -> None:
        """Fit the view so the whole infrastructure is visible.

        We call this after the widget has a real size (QTimer.singleShot(0, ...)).
        """
        if self._view.viewport().width() <= 2 or self._view.viewport().height() <= 2:
            return

        items_rect = self._scene.itemsBoundingRect()
        if items_rect.isNull():
            return

        if self._layout_mode == "topological":
            # In schematic view, keep the baseline around y=0 visually centered and
            # give some extra scroll room so panning works even when zoomed out.
            pad_x = max(items_rect.width() * 0.06, 220.0)
            pad_y = max(items_rect.height() * 0.10, 220.0)
            fit_rect = items_rect.adjusted(-pad_x, -pad_y, pad_x, pad_y)

            half_y = max(abs(float(fit_rect.top())), abs(float(fit_rect.bottom())))
            half_y = max(half_y, float(fit_rect.height()) / 2.0)
            fit_rect = QRectF(fit_rect.left(), -half_y, fit_rect.width(), 2.0 * half_y)

            pan_pad = max(max(fit_rect.width(), fit_rect.height()) * 0.25, 420.0)
            scene_rect = fit_rect.adjusted(-pan_pad, -pan_pad, pan_pad, pan_pad)
        else:
            pad = max(items_rect.width(), items_rect.height()) * 0.02  # 2%
            pad = max(pad, 20.0)
            fit_rect = items_rect.adjusted(-pad, -pad, pad, pad)
            scene_rect = fit_rect

        self._scene.setSceneRect(scene_rect)

        prev_anchor = self._view.transformationAnchor()
        prev_resize_anchor = self._view.resizeAnchor()
        self._view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self._view.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self._view.resetTransform()
        self._view.fitInView(fit_rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._view.centerOn(fit_rect.center())
        self._view.setTransformationAnchor(prev_anchor)
        self._view.setResizeAnchor(prev_resize_anchor)
        self._initial_fit_done = True
