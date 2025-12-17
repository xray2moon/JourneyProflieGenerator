"""
InfrastructureView.py

PyQt6 widget that loads an EBD infrastructure JSON (nodes/tracks/timingPoints/stoppingLocations),
renders it with a QGraphicsScene, and supports:
- zoom (mouse wheel) + pan (middle mouse drag or space+left drag)
- route selection by clicking infrastructure nodes (red)
- timing constraints by clicking timing points (blue markers along tracks)

Layout modes:
- Geographic: uses the raw node coordinates and shaping points.
- Schematic: uses a 1D baseline with track "lanes" (railway-style schematic).

Notes:
- Virtual nodes/tracks are ignored by design.
- "Timing points" are rendered as interactive markers positioned along tracks using
  distanceToTargetNodeInMeters and the referenced targetNodeId.

Signals:
- routeChanged(list[str])                     : ordered list of node UUIDs representing the selected route
- timingConstraintsChanged(list[dict])        : list of timing point constraints (dicts)
- selectionChanged(dict)                      : emits small info dict on hover/click for tooltips/side panels
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QTimer, QEvent
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTabWidget,
    QGraphicsScene,
    QGraphicsView,
    QGraphicsEllipseItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
    QGraphicsItem,
    QDialog,
    QComboBox,
    QMessageBox,
    QHBoxLayout,
    QPushButton,
    QLabel,
)

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from Source.infra_items import NodeItem, TrackItem, TimingPointItem, StoppingLocationItem
from Source.infra_models import Node, Track, TimingPoint, StoppingLocation, SchematicSegment
from Source.infra_ui import ParameterView, TimingConstraintDialog, PanZoomGraphicsView, SettingsView


# --------------------------
# Main widget
# --------------------------

class InfrastructureView(QWidget):
    """
    Top-level QWidget with 3 tabs:
    - Infrastructure View (this canvas)
    - Parameter view (placeholder)
    - confirm (placeholder)

    Core API:
    - load_infrastructure(json_path)
    - clear_route()
    - export_state() -> {"routeNodeIds": [...], "timingConstraints": [...]}
    """
    routeChanged = pyqtSignal(list)  # list[str]
    timingConstraintsChanged = pyqtSignal(list)  # list[dict]
    selectionChanged = pyqtSignal(dict)  # for tooltips/sidepanels

    def __init__(self, json_path: Optional[str] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._scene = QGraphicsScene(self)
        self._view = PanZoomGraphicsView(self._scene, self)
        self._view.set_can_start_background_pan(self._can_start_background_pan)
        self._legend = QLabel(self._view.viewport())
        self._legend.setTextFormat(Qt.TextFormat.RichText)
        self._legend.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._legend.setStyleSheet(
            "QLabel {"
            " background: rgba(255, 255, 255, 230);"
            " border: 1px solid rgba(0, 0, 0, 70);"
            " border-radius: 6px;"
            " padding: 6px 8px;"
            " color: #111;"
            " font-size: 11px;"
            "}"
        )
        self._legend.setText(
            "<b>Legende</b><br>"
            "<span style='color:#606060'>■</span> Gleis&nbsp;&nbsp;"
            "<span style='color:#00008B'>■</span> Gleis (TPs an)&nbsp;&nbsp;"
            "<span style='color:#00BCD4'>■</span> Route<br>"
            "<span style='color:#1E90FF'>■</span> Hover&nbsp;&nbsp;"
            "<span style='color:#D32F2F'>●</span> Bahnhof/Node&nbsp;&nbsp;"
            "<span style='color:#1976D2'>●</span> Timing point&nbsp;&nbsp;"
            "<span style='color:#8B0000'>●</span> Halt"
        )
        self._legend.adjustSize()
        self._legend.move(12, 12)
        self._legend.raise_()

        # Small toolbar area (optional but useful)
        self._clear_route_btn = QPushButton("Clear route")
        self._clear_route_btn.clicked.connect(self.clear_route)
        self._start_status = QLabel("Start: -")
        self._goal_status = QLabel("Ziel: -")
        self._layout_combo = QComboBox()
        self._layout_combo.addItems(["Geographic", "Schematic", "Plan"])
        self._layout_combo.currentTextChanged.connect(self._on_layout_mode_changed)
        layout_label = QLabel("Layout:")
        layout_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._clear_route_btn)
        toolbar.addSpacing(10)
        toolbar.addWidget(self._start_status)
        toolbar.addSpacing(6)
        toolbar.addWidget(self._goal_status)
        toolbar.addSpacing(12)
        toolbar.addWidget(layout_label)
        toolbar.addWidget(self._layout_combo)
        toolbar.addStretch(1)

        infra_tab = QWidget()
        infra_layout = QVBoxLayout(infra_tab)
        infra_layout.addLayout(toolbar)
        infra_layout.addWidget(self._view)

        self._tabs = QTabWidget()
        self._tabs.addTab(infra_tab, "Infrastructure View")
        self._parameter_view = ParameterView(self)
        self._parameter_view.infrastructureLoadRequested.connect(self._on_infrastructure_load_requested)
        self._parameter_view.parametersChanged.connect(self._on_parameters_changed)
        self._tabs.addTab(self._parameter_view, "Parameter view")
        
        self._settings_view = SettingsView(self)
        self._settings_view.themeChanged.connect(self._on_theme_changed)
        self._settings_view.showAllTimingPointsChanged.connect(self._on_show_all_tp_changed)
        self._settings_view.keepSelectionChanged.connect(self._on_keep_selection_changed)
        self._settings_view.showLegendChanged.connect(self._on_show_legend_changed)
        self._settings_view.defaultViewChanged.connect(self._on_default_view_changed)
        self._tabs.addTab(self._settings_view, "Settings")

        self._tabs.addTab(QWidget(), "confirm")

        layout = QVBoxLayout(self)
        layout.addWidget(self._tabs)
        self.setLayout(layout)

        self._initial_fit_done = False
        self._layout_mode = "geographic"
        self._node_positions: Dict[str, QPointF] = {}
        # Schematic rendering helpers (populated on demand / rebuild)
        self._topo_node_index: Dict[str, int] = {}
        self._topo_track_offset_y: Dict[str, float] = {}
        self._track_render_paths: Dict[str, QPainterPath] = {}
        self._track_render_polylines: Dict[str, List[QPointF]] = {}
        self._topo_station_layout: List[Tuple[str, float, float, int]] = []  # (stationName, x0, x1, component)
        self._node_to_station: Dict[str, str] = {}  # nodeId -> stationName
        self._station_rep_node_id: Dict[str, str] = {}  # stationName -> nodeId (for routing)
        self._station_rect_items: Dict[str, QGraphicsRectItem] = {}
        self._topo_route_item: Optional[QGraphicsPathItem] = None
        self._schem_keep_nodes: set[str] = set()
        self._schem_segments: Dict[str, SchematicSegment] = {}
        self._schem_adj: Dict[str, List[Tuple[str, str, float]]] = {}  # nodeId -> (neighborId, segmentId, weight)
        self._schem_track_to_segment: Dict[str, str] = {}  # trackId -> segmentId
        self._schem_segment_parallel_offset_y: Dict[str, float] = {}  # segmentId -> small y offset for parallel edges
        self._schem_tree_segment_ids: set[str] = set()
        self._schem_station_items: List[QGraphicsItem] = []

        # Model caches
        self._nodes: Dict[str, Node] = {}
        self._tracks: Dict[str, Track] = {}
        self._timing_points: Dict[int, TimingPoint] = {}
        self._stopping_locations: Dict[str, StoppingLocation] = {}

        # Group label mapping for stopping locations
        self._sl_to_group: Dict[str, str] = {}  # stoppingLocationId -> groupName

        # Graphics items
        self._node_items: Dict[str, NodeItem] = {}
        self._track_items: Dict[str, TrackItem] = {}
        self._tp_items: Dict[int, TimingPointItem] = {}
        self._sl_items: Dict[str, StoppingLocationItem] = {}
        self._tp_track_map: Dict[str, List[TimingPointItem]] = {}
        self._visible_tp_tracks: set[str] = set()

        # Routing graph: nodeId -> list of (neighborNodeId, trackId, weight)
        self._graph: Dict[str, List[Tuple[str, str, float]]] = {}

        # Current state
        self._route_node_ids: List[str] = []
        self._route_track_ids: List[str] = []
        self._route_plan_start: Optional[str] = None
        self._route_plan_goal: Optional[str] = None
        self._route_plan_waypoints: List[str] = []
        # timingPointId -> constraint dict
        self._timing_constraints: Dict[int, dict] = {}
        self._infrastructure_json_path: Optional[str] = None
        self._parameters: dict = self._parameter_view.parameters()
        self._current_theme: str = "light"
        
        # New settings state
        self._show_all_tp: bool = False
        self._keep_selection: bool = False
        self._show_legend: bool = True
        self._default_view: str = "Geographic"

        # Scene interaction
        self._scene.selectionChanged.connect(self._on_selection_changed)
        self._update_planning_status_labels()
        self._update_legend_text()

        if json_path:
            self.load_infrastructure(json_path)
            
        self._load_settings()

    def _position_overlay_widgets(self) -> None:
        if getattr(self, "_legend", None) is None:
            return
        self._legend.adjustSize()
        self._legend.move(12, 12)
        self._legend.raise_()

    def _load_settings(self) -> None:
        settings_path = Path("user_settings.json")
        if settings_path.exists():
            try:
                with open(settings_path, "r") as f:
                    settings = json.load(f)
                    self._current_theme = settings.get("theme", "light")
                    self._show_all_tp = settings.get("show_all_tp", False)
                    self._keep_selection = settings.get("keep_selection", False)
                    self._show_legend = settings.get("show_legend", True)
                    self._default_view = settings.get("default_view", "Geographic")
                    
                    # Apply settings to UI
                    self._settings_view._theme_combo.setCurrentText(self._current_theme.capitalize())
                    self._settings_view._show_all_tp_check.setChecked(self._show_all_tp)
                    self._settings_view._keep_selection_check.setChecked(self._keep_selection)
                    self._settings_view._show_legend_check.setChecked(self._show_legend)
                    self._settings_view._default_view_combo.setCurrentText(self._default_view)
                    
                    # Apply to view
                    self._on_theme_changed(self._current_theme)
                    self._on_layout_mode_changed(self._default_view)
                    self._layout_combo.setCurrentText(self._default_view)
                    self._on_show_legend_changed(self._show_legend)
            except Exception as e:
                print(f"Failed to load settings: {e}")

    def _save_settings(self) -> None:
        settings = {
            "theme": self._current_theme,
            "show_all_tp": self._show_all_tp,
            "keep_selection": self._keep_selection,
            "show_legend": self._show_legend,
            "default_view": self._default_view
        }
        try:
            with open("user_settings.json", "w") as f:
                json.dump(settings, f)
        except Exception as e:
            print(f"Failed to save settings: {e}")

    def _on_infrastructure_load_requested(self, json_path: str) -> None:
        try:
            self.load_infrastructure(json_path)
        except Exception as exc:
            self._parameter_view.set_infrastructure_error(json_path, str(exc))
            QMessageBox.critical(self, "Failed to load infrastructure", str(exc))
            return
        self._tabs.setCurrentIndex(0)

    def _on_parameters_changed(self, params: dict) -> None:
        self._parameters = dict(params or {})

    def _on_theme_changed(self, theme: str) -> None:
        self._current_theme = theme
        self._save_settings()
        
        # Update view background
        if theme == "dark":
            self._view.setBackgroundBrush(QBrush(QColor(34, 34, 34)))
            self._legend.setStyleSheet(
                "QLabel {"
                " background: rgba(45, 45, 45, 230);"
                " border: 1px solid rgba(255, 255, 255, 70);"
                " border-radius: 6px;"
                " padding: 6px 8px;"
                " color: #eee;"
                " font-size: 11px;"
                "}"
            )
        else:
            self._view.setBackgroundBrush(QBrush(Qt.GlobalColor.white))
            self._legend.setStyleSheet(
                "QLabel {"
                " background: rgba(255, 255, 255, 230);"
                " border: 1px solid rgba(0, 0, 0, 70);"
                " border-radius: 6px;"
                " padding: 6px 8px;"
                " color: #111;"
                " font-size: 11px;"
                "}"
            )

        self._rebuild_scene()

    def _on_show_all_tp_changed(self, enabled: bool) -> None:
        self._show_all_tp = enabled
        self._save_settings()
        self._rebuild_scene() # Rebuild to apply visibility rules

    def _on_keep_selection_changed(self, enabled: bool) -> None:
        self._keep_selection = enabled
        self._save_settings()

    def _on_show_legend_changed(self, enabled: bool) -> None:
        self._show_legend = enabled
        self._legend.setVisible(enabled)
        self._save_settings()

    def _on_default_view_changed(self, view_name: str) -> None:
        self._default_view = view_name
        self._save_settings()

    def _on_layout_mode_changed(self, mode_text: str) -> None:
        lowered = mode_text.lower().strip()
        if lowered.startswith("plan"):
            mode = "plan"
        elif lowered.startswith("schem") or lowered.startswith("topo"):
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

    def load_infrastructure(self, json_path: str) -> None:
        """
        Load and render infrastructure from JSON file.
        """
        p = Path(json_path)
        if not p.exists():
            raise FileNotFoundError(f"JSON file not found: {p}")

        with p.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        self._parse_raw(raw)
        self._build_graph()
        self._rebuild_scene()
        self.clear_route()
        self._initial_fit_done = False
        self._infrastructure_json_path = str(p)
        self._parameter_view.set_infrastructure_summary(
            str(p),
            nodes=len(self._nodes),
            tracks=len(self._tracks),
            timing_points=len(self._timing_points),
            stopping_locations=len(self._stopping_locations),
        )
        QTimer.singleShot(0, self._fit_to_scene)

    def _parse_raw(self, raw: dict) -> None:
        self._nodes.clear()
        self._tracks.clear()
        self._timing_points.clear()
        self._stopping_locations.clear()
        self._sl_to_group.clear()
        self._visible_tp_tracks.clear()
        self._timing_constraints.clear()

        # Nodes
        for n in raw.get("nodes", []):
            coord = n.get("coordinate") or {}
            node = Node(
                id=n["id"],
                x=float(coord.get("x", 0.0)),
                y=float(coord.get("y", 0.0)),
                numeric_id=n.get("numericId"),
            )
            self._nodes[node.id] = node

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
            self._tracks[track.id] = track

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
            self._timing_points[timing_point.id] = timing_point

        # Stopping location groups -> mapping
        for g in raw.get("stoppingLocationGroups", []):
            gname = g.get("id", "")
            for entry in g.get("stoppingLocations", []):
                sl_id = entry.get("stoppingLocationId")
                if sl_id:
                    self._sl_to_group[sl_id] = gname

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
            self._stopping_locations[stopping_location.id] = stopping_location

    # -----------
    # Graph & routing
    # -----------

    def _build_graph(self) -> None:
        """
        Undirected graph (physical tracks) with edge weight = track length.
        """
        self._graph = {nid: [] for nid in self._nodes.keys()}
        for tr in self._tracks.values():
            if tr.source not in self._nodes or tr.target not in self._nodes:
                continue
            w = tr.length_m if tr.length_m > 0 else 1.0
            self._graph[tr.source].append((tr.target, tr.id, w))
            self._graph[tr.target].append((tr.source, tr.id, w))

    def _shortest_path(self, start: str, goal: str) -> Tuple[List[str], List[str]]:
        """
        Dijkstra over nodes, returning (node_path, track_path).
        node_path includes both endpoints.
        """
        if start == goal:
            return [start], []

        import heapq
        dist: Dict[str, float] = {start: 0.0}
        prev: Dict[str, Tuple[str, str]] = {}  # node -> (prevNode, trackId)
        pq = [(0.0, start)]
        seen = set()

        while pq:
            d, u = heapq.heappop(pq)
            if u in seen:
                continue
            seen.add(u)
            if u == goal:
                break
            for v, track_id, w in self._graph.get(u, []):
                nd = d + w
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    prev[v] = (u, track_id)
                    heapq.heappush(pq, (nd, v))

        if goal not in prev and goal != start:
            return [start], []

        # reconstruct
        nodes = [goal]
        tracks = []
        cur = goal
        while cur != start:
            pu, tr_id = prev[cur]
            tracks.append(tr_id)
            nodes.append(pu)
            cur = pu
        nodes.reverse()
        tracks.reverse()
        return nodes, tracks

    # -----------
    # Scene build
    # -----------

    def _rebuild_scene(self) -> None:
        self._scene.clear()
        self._node_items.clear()
        self._track_items.clear()
        self._tp_items.clear()
        self._sl_items.clear()
        self._tp_track_map.clear()
        self._track_render_paths.clear()
        self._track_render_polylines.clear()
        self._schem_station_items = []

        if self._layout_mode == "topological":
            self._rebuild_schematic_scene()
            return
        if self._layout_mode == "plan":
            self._rebuild_plan_scene()
            return

        self._node_positions = self._compute_node_positions()

        # Tracks first
        for tr in self._tracks.values():
            path = self._track_to_path(tr)
            if path is None:
                continue
            item = TrackItem(tr.id, path)
            item.set_theme(self._current_theme)
            label = f"Track {tr.numeric_id}" if tr.numeric_id is not None else "Track"
            tip = f"{label}\nlen={tr.length_m:.0f} m\n{tr.id}"
            item.setToolTip(tip)
            item.inner_overlay().setToolTip(tip)
            item.route_overlay().setToolTip(tip)
            item.set_timing_points_visible(self._show_all_tp or tr.id in self._visible_tp_tracks)
            self._scene.addItem(item)
            self._scene.addItem(item.inner_overlay())
            self._scene.addItem(item.route_overlay())
            self._track_items[tr.id] = item
            self._tp_track_map.setdefault(tr.id, [])

        # Nodes
        for node in self._nodes.values():
            pos = self._node_positions.get(node.id, QPointF(node.x, node.y))
            ni = NodeItem(node)
            ni.set_theme(self._current_theme)
            ni.setPos(pos)
            self._scene.addItem(ni)
            self._node_items[node.id] = ni

        # Timing points (blue)
        for tp in self._timing_points.values():
            pos = self._timing_point_position(tp)
            if pos is None:
                continue
            tpi = TimingPointItem(tp, pos)
            tpi.set_theme(self._current_theme)
            
            # Visibility logic:
            # 1. Show all TPs if setting is enabled.
            # 2. Show if track is selected.
            # 3. Show if it has a 'STOP' constraint (even if track unchecked).
            # 4. 'PASS' constraint should behave like normal (only visible if track is visible),
            #    unless show_all_tp is on.
            
            has_stop = False
            if tp.id in self._timing_constraints:
                c = self._timing_constraints[tp.id]
                if c.get("pointType") == "STOP":
                    has_stop = True

            is_visible = (
                self._show_all_tp 
                or (tp.track_id in self._visible_tp_tracks) 
                or has_stop
            )
            tpi.setVisible(is_visible)
            self._scene.addItem(tpi)
            self._tp_items[tp.id] = tpi
            self._tp_track_map.setdefault(tp.track_id, []).append(tpi)

        # Stopping locations + labels
        for sl in self._stopping_locations.values():
            pos = self._stopping_location_position(sl)
            if pos is None:
                continue

            group = self._sl_to_group.get(sl.id, "")
            suffix = ""
            if "-SL-" in sl.id:
                suffix = sl.id.split("-SL-")[-1].strip()
            label = group if group else sl.id
            if group and suffix:
                label = f"{group} {suffix}"

            sli = StoppingLocationItem(sl.id, pos, label)
            sli.set_theme(self._current_theme)
            self._scene.addItem(sli)
            self._scene.addItem(sli.label_item())
            self._sl_items[sl.id] = sli

        # Hook mouse events by installing a scene event filter
        # (We route clicks based on item types.)
        self._scene.installEventFilter(self)

        self._restore_timing_point_markers()
        self._update_route_highlights()

    def _rebuild_schematic_scene(self) -> None:
        """
        Schematic view:
        - Contract degree-2 nodes into segments (reduces clutter)
        - Lay out a backbone path (y=0) and attach branches above/below
        - Render contracted segments and a reduced node set
        """
        self._topo_route_item = None
        self._station_rect_items = {}
        self._topo_station_layout = []
        self._topo_node_index = {}
        self._topo_track_offset_y = {}
        self._node_to_station = {}
        self._station_rep_node_id = {}

        self._build_schematic_graph()
        self._node_positions = self._compute_schematic_positions()

        # Segments first
        for seg in self._schem_segments.values():
            path = self._schematic_segment_path(seg)
            if path is None:
                continue
            item = TrackItem(seg.id, path)
            item.set_theme(self._current_theme)
            tip = f"Segment\nlen≈{seg.length_m:.0f} m\ntracks={len(seg.track_ids)}"
            item.setToolTip(tip)
            item.inner_overlay().setToolTip(tip)
            item.route_overlay().setToolTip(tip)
            item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            item.inner_overlay().setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            item.route_overlay().setAcceptedMouseButtons(Qt.MouseButton.NoButton)

            dimmed = seg.id not in self._schem_tree_segment_ids
            opacity = 0.12 if dimmed else 1.0
            item.setOpacity(opacity)
            item.inner_overlay().setOpacity(opacity)

            self._scene.addItem(item)
            self._scene.addItem(item.inner_overlay())
            self._scene.addItem(item.route_overlay())
            self._track_items[seg.id] = item

        # Kept nodes only
        for node_id in sorted(self._schem_keep_nodes, key=self._node_sort_key):
            node = self._nodes.get(node_id)
            if node is None:
                continue
            pos = self._node_positions.get(node_id)
            if pos is None:
                continue
            ni = NodeItem(node, radius=4.0, brush=Qt.GlobalColor.darkGray)
            ni.set_theme(self._current_theme)
            ni.setPos(pos)
            self._scene.addItem(ni)
            self._node_items[node_id] = ni

        self._add_schematic_station_markers()

        self._scene.installEventFilter(self)
        self._update_route_highlights()

    def _rebuild_plan_scene(self) -> None:
        """
        Plan view:
        Purpose-built "track plan" rendering:
        - emphasize stations (blocks) and main connections
        - draw bundled/parallel tracks as multiple rails
        - route segments with orthogonal + 45° corners for readability
        """
        self._topo_route_item = None
        self._station_rect_items = {}
        self._topo_station_layout = []
        self._topo_node_index = {}
        self._topo_track_offset_y = {}
        self._node_to_station = {}
        self._station_rep_node_id = {}

        self._build_schematic_graph()
        self._node_positions = self._compute_plan_positions()

        track_spacing = 10.0
        station_block_len = 140.0

        # Parallel-track count between original node pairs.
        pair_parallel: Dict[Tuple[str, str], int] = {}
        for tr in self._tracks.values():
            if tr.source not in self._nodes or tr.target not in self._nodes:
                continue
            a, b = (tr.source, tr.target)
            if a > b:
                a, b = b, a
            pair_parallel[(a, b)] = pair_parallel.get((a, b), 0) + 1

        def segment_parallel_tracks(seg: SchematicSegment) -> int:
            counts: List[int] = []
            for u, v in zip(seg.node_path[:-1], seg.node_path[1:]):
                a, b = (u, v)
                if a > b:
                    a, b = b, a
                counts.append(max(1, int(pair_parallel.get((a, b), 1))))
            return max(counts) if counts else 1

        endpoint_overrides, station_blocks = self._plan_build_station_blocks(
            pair_parallel=pair_parallel,
            segment_parallel_tracks=segment_parallel_tracks,
            track_spacing=track_spacing,
            block_len=station_block_len,
        )

        # Segments first (station blocks are drawn above).
        for seg in self._schem_segments.values():
            # Internal station wiring is represented by the station block itself.
            s_station = self._node_to_station.get(seg.source)
            t_station = self._node_to_station.get(seg.target)
            if s_station and s_station == t_station:
                continue

            p0 = endpoint_overrides.get((seg.id, seg.source)) or self._node_positions.get(seg.source)
            p1 = endpoint_overrides.get((seg.id, seg.target)) or self._node_positions.get(seg.target)
            if p0 is None or p1 is None:
                continue

            n_tracks = max(1, min(6, segment_parallel_tracks(seg)))
            path = self._plan_segment_path(p0, p1, n_tracks=n_tracks, track_spacing=track_spacing)
            item = TrackItem(seg.id, path)
            item.set_theme(self._current_theme)

            plan_outer = QPen(Qt.GlobalColor.black)
            plan_outer.setWidthF(7.0)
            plan_outer.setCapStyle(Qt.PenCapStyle.RoundCap)
            plan_outer.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            plan_hover = QPen(Qt.GlobalColor.darkBlue)
            plan_hover.setWidthF(8.0)
            plan_hover.setCapStyle(Qt.PenCapStyle.RoundCap)
            plan_hover.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            plan_inner = QPen(Qt.GlobalColor.white)
            plan_inner.setWidthF(2.4)
            plan_inner.setCapStyle(Qt.PenCapStyle.RoundCap)
            plan_inner.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

            item.set_outer_pens(default=plan_outer, visible=plan_outer, hover=plan_hover, inner=plan_inner)
            tip = f"Segment\nlen≈{seg.length_m:.0f} m\nGleise≈{n_tracks}"
            item.setToolTip(tip)
            item.inner_overlay().setToolTip(tip)
            item.route_overlay().setToolTip(tip)
            item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            item.inner_overlay().setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            item.route_overlay().setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            # Single-line plan look: keep only the thick "outer" stroke; no inner white stroke.
            item.inner_overlay().setVisible(False)
            # Make the route overlay a bit more visible over thick black tracks.
            route_pen = QPen(item.route_overlay().pen())
            route_pen.setWidthF(4.2)
            item.route_overlay().setPen(route_pen)

            self._scene.addItem(item)
            self._scene.addItem(item.route_overlay())
            self._track_items[seg.id] = item

        self._plan_draw_station_blocks(
            station_blocks,
            track_spacing=track_spacing,
            block_len=station_block_len,
        )

        self._scene.installEventFilter(self)
        self._update_route_highlights()

    def _path_from_points(self, pts: List[QPointF]) -> QPainterPath:
        path = QPainterPath(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        return path

    def _axis_polyline_with_45deg_corners(self, pts: List[QPointF], bevel: float) -> List[QPointF]:
        """
        Replace 90° corners in an axis-aligned polyline with 45° chamfers.

        This is used in schematic mode to make paths look more like railway schematics.
        """
        if len(pts) < 3:
            return pts

        cleaned: List[QPointF] = [pts[0]]
        for p in pts[1:]:
            if (p.x() - cleaned[-1].x()) ** 2 + (p.y() - cleaned[-1].y()) ** 2 > 1e-12:
                cleaned.append(p)
        if len(cleaned) < 3:
            return cleaned

        out: List[QPointF] = [cleaned[0]]
        for prev, cur, nxt in zip(cleaned[:-2], cleaned[1:-1], cleaned[2:]):
            dx1 = float(cur.x() - prev.x())
            dy1 = float(cur.y() - prev.y())
            dx2 = float(nxt.x() - cur.x())
            dy2 = float(nxt.y() - cur.y())

            # Skip if straight / degenerate.
            if (abs(dx1) <= 1e-9 and abs(dy1) <= 1e-9) or (abs(dx2) <= 1e-9 and abs(dy2) <= 1e-9):
                out.append(cur)
                continue
            if abs(dx1) <= 1e-9 and abs(dx2) <= 1e-9:
                out.append(cur)
                continue
            if abs(dy1) <= 1e-9 and abs(dy2) <= 1e-9:
                out.append(cur)
                continue

            # Only chamfer axis-aligned right angles.
            axis1 = (abs(dx1) <= 1e-9) != (abs(dy1) <= 1e-9)
            axis2 = (abs(dx2) <= 1e-9) != (abs(dy2) <= 1e-9)
            if not (axis1 and axis2):
                out.append(cur)
                continue
            if (abs(dx1) <= 1e-9 and abs(dy2) <= 1e-9) or (abs(dy1) <= 1e-9 and abs(dx2) <= 1e-9):
                pass
            else:
                out.append(cur)
                continue

            len1 = abs(dx1) + abs(dy1)
            len2 = abs(dx2) + abs(dy2)
            b = min(float(bevel), float(len1) * 0.49, float(len2) * 0.49)
            if b <= 0.5:
                out.append(cur)
                continue

            ux1 = 0.0 if abs(dx1) <= 1e-9 else (1.0 if dx1 > 0 else -1.0)
            uy1 = 0.0 if abs(dy1) <= 1e-9 else (1.0 if dy1 > 0 else -1.0)
            ux2 = 0.0 if abs(dx2) <= 1e-9 else (1.0 if dx2 > 0 else -1.0)
            uy2 = 0.0 if abs(dy2) <= 1e-9 else (1.0 if dy2 > 0 else -1.0)

            p_in = QPointF(cur.x() - ux1 * b, cur.y() - uy1 * b)
            p_out = QPointF(cur.x() + ux2 * b, cur.y() + uy2 * b)
            out.append(p_in)
            out.append(p_out)

        out.append(cleaned[-1])

        # Remove any accidental duplicates created by tiny bevels.
        final: List[QPointF] = [out[0]]
        for p in out[1:]:
            if (p.x() - final[-1].x()) ** 2 + (p.y() - final[-1].y()) ** 2 > 1e-12:
                final.append(p)
        return final

    def _offset_polyline(self, pts: List[QPointF], offset: float) -> List[QPointF]:
        """
        Approximate parallel polyline by offsetting vertices along the local normal.

        Used in Plan view to draw multiple parallel tracks per schematic segment.
        """
        if len(pts) < 2 or abs(float(offset)) <= 1e-9:
            return list(pts)

        # Per-segment unit normals.
        normals: List[Tuple[float, float]] = []
        for a, b in zip(pts[:-1], pts[1:]):
            dx = float(b.x() - a.x())
            dy = float(b.y() - a.y())
            l = math.hypot(dx, dy)
            if l <= 1e-9:
                normals.append((0.0, 0.0))
            else:
                ux = dx / l
                uy = dy / l
                normals.append((-uy, ux))

        out: List[QPointF] = []
        n = len(pts)
        for i, p in enumerate(pts):
            if i == 0:
                nx, ny = normals[0]
            elif i == n - 1:
                nx, ny = normals[-1]
            else:
                n1x, n1y = normals[i - 1]
                n2x, n2y = normals[i]
                nx = n1x + n2x
                ny = n1y + n2y
                ln = math.hypot(nx, ny)
                if ln <= 1e-9:
                    nx, ny = n1x, n1y
                else:
                    nx /= ln
                    ny /= ln
            out.append(QPointF(p.x() + nx * offset, p.y() + ny * offset))
        return out

    def _sample_path_points(self, path: QPainterPath, steps: int = 120) -> List[QPointF]:
        steps = max(8, int(steps))
        return [path.pointAtPercent(i / steps) for i in range(steps + 1)]

    def _geographic_polyline_points_for_track(self, tr: Track) -> Optional[List[QPointF]]:
        if tr.source not in self._nodes or tr.target not in self._nodes:
            return None
        src = self._node_positions.get(tr.source)
        tgt = self._node_positions.get(tr.target)
        if src is None or tgt is None:
            return None
        pts = [QPointF(src)]
        pts += [QPointF(x, y) for (x, y) in tr.shaping_points]
        pts.append(QPointF(tgt))
        return pts

    def _topological_track_path(self, tr: Track) -> Optional[QPainterPath]:
        src = self._node_positions.get(tr.source)
        tgt = self._node_positions.get(tr.target)
        if src is None or tgt is None:
            return None

        lane_y = float(self._topo_track_offset_y.get(tr.id, 0.0))
        dx = tgt.x() - src.x()
        if abs(dx) <= 1e-6 or abs(lane_y) <= 1e-6:
            path = QPainterPath(QPointF(src))
            path.lineTo(QPointF(tgt))
            return path

        sign = 1.0 if dx >= 0.0 else -1.0
        abs_dx = abs(dx)
        ramp = min(90.0, abs_dx * 0.22)
        if ramp * 2.0 > abs_dx:
            ramp = abs_dx / 2.0

        p0 = QPointF(src)
        p3 = QPointF(tgt)
        p1 = QPointF(p0.x() + sign * ramp * 0.5, p0.y())
        p2 = QPointF(p0.x() + sign * ramp * 0.5, lane_y)
        p4 = QPointF(p0.x() + sign * ramp, lane_y)

        p5 = QPointF(p3.x() - sign * ramp, lane_y)
        p6 = QPointF(p3.x() - sign * ramp * 0.5, lane_y)
        p7 = QPointF(p3.x() - sign * ramp * 0.5, p3.y())

        path = QPainterPath(p0)
        path.cubicTo(p1, p2, p4)
        if (sign > 0 and p4.x() < p5.x()) or (sign < 0 and p4.x() > p5.x()):
            path.lineTo(p5)
        path.cubicTo(p6, p7, p3)
        return path

    def _track_to_path(self, tr: Track) -> Optional[QPainterPath]:
        cached = self._track_render_paths.get(tr.id)
        if cached is not None:
            return cached

        if self._layout_mode == "topological":
            path = self._topological_track_path(tr)
        else:
            pts = self._geographic_polyline_points_for_track(tr)
            path = self._path_from_points(pts) if pts else None

        if path is not None:
            self._track_render_paths[tr.id] = path
        return path

    def _polyline_points_for_track(self, tr: Track) -> Optional[List[QPointF]]:
        cached = self._track_render_polylines.get(tr.id)
        if cached is not None:
            return cached

        if self._layout_mode == "geographic":
            pts = self._geographic_polyline_points_for_track(tr)
        else:
            path = self._track_to_path(tr)
            pts = self._sample_path_points(path) if path is not None else None

        if pts is not None:
            self._track_render_polylines[tr.id] = pts
        return pts

    def _point_along_polyline(self, pts: List[QPointF], fraction: float) -> QPointF:
        """
        Return point at 'fraction' of total polyline length (0..1),
        using Euclidean length of drawn geometry.
        """
        fraction = max(0.0, min(1.0, fraction))
        seglens = []
        total = 0.0
        for a, b in zip(pts[:-1], pts[1:]):
            dx = b.x() - a.x()
            dy = b.y() - a.y()
            l = math.hypot(dx, dy)
            seglens.append(l)
            total += l

        if total <= 1e-9:
            return pts[0]

        target = fraction * total
        acc = 0.0
        for (a, b, l) in zip(pts[:-1], pts[1:], seglens):
            if acc + l >= target:
                t = (target - acc) / l if l > 1e-9 else 0.0
                return QPointF(a.x() + t * (b.x() - a.x()), a.y() + t * (b.y() - a.y()))
            acc += l
        return pts[-1]

    def _timing_point_position(self, tp: TimingPoint) -> Optional[QPointF]:
        tr = self._tracks.get(tp.track_id)
        if tr is None or tr.length_m <= 0:
            return None
        pts = self._polyline_points_for_track(tr)
        if pts is None:
            return None

        # distanceToTargetNodeInMeters is measured towards tp.target_node_id
        if tp.target_node_id == tr.target:
            frac = (tr.length_m - tp.distance_to_target_m) / tr.length_m
        elif tp.target_node_id == tr.source:
            frac = tp.distance_to_target_m / tr.length_m
        else:
            # unexpected; fallback to center
            frac = 0.5
        return self._point_along_polyline(pts, frac)

    def _stopping_location_position(self, sl: StoppingLocation) -> Optional[QPointF]:
        tr = self._tracks.get(sl.track_id)
        if tr is None or tr.length_m <= 0:
            return None
        pts = self._polyline_points_for_track(tr)
        if pts is None:
            return None

        if sl.reference_node_id == tr.source:
            frac = sl.distance_from_ref_m / tr.length_m
        elif sl.reference_node_id == tr.target:
            frac = (tr.length_m - sl.distance_from_ref_m) / tr.length_m
        else:
            frac = 0.5
        return self._point_along_polyline(pts, frac)

    def _compute_node_positions(self) -> Dict[str, QPointF]:
        if self._layout_mode == "topological":
            return self._compute_topological_positions()
        self._topo_node_index = {}
        self._topo_station_layout = []
        self._node_to_station = {}
        self._station_rep_node_id = {}
        self._station_rect_items = {}
        return {node.id: QPointF(node.x, node.y) for node in self._nodes.values()}

    def _station_nodes_map(self) -> Dict[str, set[str]]:
        """
        Map station/group name -> set(nodeIds) based on stoppingLocationGroups.

        This is a heuristic: we use the stopping location's reference/target-direction nodes
        and the endpoints of the track the stopping location sits on.
        """
        group_to_nodes: Dict[str, set[str]] = {}
        for sl_id, group in self._sl_to_group.items():
            if not group:
                continue
            sl = self._stopping_locations.get(sl_id)
            if sl is None:
                continue

            nodes = group_to_nodes.setdefault(group, set())
            if sl.reference_node_id in self._nodes:
                nodes.add(sl.reference_node_id)
            if sl.target_direction_node_id in self._nodes:
                nodes.add(sl.target_direction_node_id)

            tr = self._tracks.get(sl.track_id)
            if tr is not None:
                if tr.source in self._nodes:
                    nodes.add(tr.source)
                if tr.target in self._nodes:
                    nodes.add(tr.target)

        return {name: nodes for (name, nodes) in group_to_nodes.items() if nodes}

    # -----------------
    # Schematic helpers
    # -----------------

    def _build_schematic_graph(self) -> None:
        """
        Build a simplified multigraph for schematic rendering.

        - Nodes with exactly 2 unique neighbors are contracted away (unless part of a station group).
        - Each resulting schematic segment represents a chain of original node-to-node hops.
        - Parallel tracks on the same hop are bundled into the same segment (track_ids list).
        """
        self._schem_keep_nodes = set()
        self._schem_segments = {}
        self._schem_adj = {}
        self._schem_track_to_segment = {}
        self._schem_segment_parallel_offset_y = {}
        self._schem_tree_segment_ids = set()

        # Station mapping (for labels / route selection)
        self._node_to_station = {}
        self._station_rep_node_id = {}
        station_nodes = self._station_nodes_map()
        station_node_set: set[str] = set()
        for name, nodes in station_nodes.items():
            station_node_set |= nodes
            ordered = sorted(nodes, key=self._node_sort_key)
            if ordered:
                rep = ordered[len(ordered) // 2]
                self._station_rep_node_id[name] = rep
            for nid in nodes:
                self._node_to_station.setdefault(nid, name)

        # Hop bundling between original node pairs
        pair_to_track_ids: Dict[Tuple[str, str], List[str]] = {}
        for tr in self._tracks.values():
            if tr.source not in self._nodes or tr.target not in self._nodes:
                continue
            a, b = (tr.source, tr.target)
            if a > b:
                a, b = b, a
            pair_to_track_ids.setdefault((a, b), []).append(tr.id)

        neighbors: Dict[str, set[str]] = {nid: set() for nid in self._nodes.keys()}
        for (a, b) in pair_to_track_ids.keys():
            neighbors.setdefault(a, set()).add(b)
            neighbors.setdefault(b, set()).add(a)

        # Contract degree-2 nodes (in the simple unique-neighbor sense), except station nodes.
        contractible: set[str] = set()
        for nid, nbs in neighbors.items():
            if nid in station_node_set:
                continue
            if len(nbs) == 2:
                contractible.add(nid)

        self._schem_keep_nodes = set(self._nodes.keys()) - contractible

        visited_hops: set[Tuple[str, str]] = set()
        seg_idx = 0

        def hop_min_length(a: str, b: str) -> float:
            x, y = (a, b) if a < b else (b, a)
            tids = pair_to_track_ids.get((x, y), [])
            best = math.inf
            for tid in tids:
                tr = self._tracks.get(tid)
                if tr is None:
                    continue
                best = min(best, tr.length_m if tr.length_m > 0 else 1.0)
            return best if best != math.inf else 1.0

        for u in sorted(self._schem_keep_nodes, key=self._node_sort_key):
            for v in sorted(neighbors.get(u, set()), key=self._node_sort_key):
                a, b = (u, v) if u < v else (v, u)
                if (a, b) in visited_hops:
                    continue

                node_path: List[str] = [u]
                track_ids: List[str] = []
                length_m = 0.0
                hops: List[Tuple[str, str]] = []

                prev = u
                cur = v
                while True:
                    node_path.append(cur)
                    ha, hb = (prev, cur) if prev < cur else (cur, prev)
                    hops.append((ha, hb))
                    tids = pair_to_track_ids.get((ha, hb), [])
                    track_ids.extend(tids)
                    length_m += hop_min_length(prev, cur)

                    if cur in self._schem_keep_nodes:
                        break

                    nbs = list(neighbors.get(cur, set()))
                    if len(nbs) != 2:
                        # Fallback: treat this as a keep node for the traversal.
                        self._schem_keep_nodes.add(cur)
                        break

                    if nbs[0] == prev:
                        nxt = nbs[1]
                    elif nbs[1] == prev:
                        nxt = nbs[0]
                    else:
                        break

                    prev, cur = cur, nxt

                    # Stop on small loops; the remaining hops will be handled by other traversals.
                    ha2, hb2 = (prev, cur) if prev < cur else (cur, prev)
                    if (ha2, hb2) in visited_hops:
                        break

                for hop in hops:
                    visited_hops.add(hop)

                if len(node_path) < 2:
                    continue

                seg_id = f"__schem_seg__:{seg_idx}"
                seg_idx += 1
                unique_tracks = sorted({tid for tid in track_ids if tid in self._tracks})
                seg = SchematicSegment(
                    id=seg_id,
                    source=node_path[0],
                    target=node_path[-1],
                    node_path=node_path,
                    track_ids=unique_tracks,
                    length_m=length_m if length_m > 0 else 1.0,
                )
                self._schem_segments[seg_id] = seg

        # Build adjacency and track->segment mapping
        self._schem_adj = {nid: [] for nid in self._schem_keep_nodes}
        for seg in self._schem_segments.values():
            if seg.source not in self._schem_adj or seg.target not in self._schem_adj:
                continue
            w = seg.length_m if seg.length_m > 0 else 1.0
            self._schem_adj[seg.source].append((seg.target, seg.id, w))
            self._schem_adj[seg.target].append((seg.source, seg.id, w))
            for tid in seg.track_ids:
                self._schem_track_to_segment.setdefault(tid, seg.id)

        # Small offsets for parallel segments between the same endpoints.
        by_pair: Dict[Tuple[str, str], List[str]] = {}
        for seg in self._schem_segments.values():
            a, b = (seg.source, seg.target) if seg.source < seg.target else (seg.target, seg.source)
            by_pair.setdefault((a, b), []).append(seg.id)

        for (a, b), seg_ids in by_pair.items():
            if len(seg_ids) <= 1:
                continue
            seg_ids = sorted(seg_ids)
            mid = (len(seg_ids) - 1) / 2.0
            for i, sid in enumerate(seg_ids):
                self._schem_segment_parallel_offset_y[sid] = (i - mid) * 10.0

    def _schem_connected_components(self, nodes: set[str]) -> List[List[str]]:
        remaining = set(nodes)
        components: List[List[str]] = []
        while remaining:
            start = min(remaining, key=self._node_sort_key)
            stack = [start]
            remaining.remove(start)
            comp: List[str] = []
            while stack:
                u = stack.pop()
                comp.append(u)
                for v, _, _ in self._schem_adj.get(u, []):
                    if v in remaining:
                        remaining.remove(v)
                        stack.append(v)
            components.append(comp)
        return components

    def _schem_dijkstra(
        self,
        start_nodes: List[str],
        allowed: set[str],
    ) -> Tuple[Dict[str, float], Dict[str, str], Dict[str, str], Dict[str, str]]:
        """
        Multi-source Dijkstra on the schematic graph.

        Returns (dist, prev_node, prev_edge, root_backbone).
        """
        import heapq

        dist: Dict[str, float] = {}
        prev_node: Dict[str, str] = {}
        prev_edge: Dict[str, str] = {}
        root: Dict[str, str] = {}
        pq: List[Tuple[float, str]] = []

        for s in start_nodes:
            if s not in allowed:
                continue
            dist[s] = 0.0
            root[s] = s
            heapq.heappush(pq, (0.0, s))

        while pq:
            d, u = heapq.heappop(pq)
            if d != dist.get(u, float("inf")):
                continue
            for v, seg_id, w in self._schem_adj.get(u, []):
                if v not in allowed:
                    continue
                nd = d + (w if w > 0 else 1.0)
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    prev_node[v] = u
                    prev_edge[v] = seg_id
                    root[v] = root.get(u, u)
                    heapq.heappush(pq, (nd, v))

        return dist, prev_node, prev_edge, root

    def _compute_schematic_positions(self) -> Dict[str, QPointF]:
        """
        Backbone + branches layout on the contracted schematic graph.

        - Pick a backbone path (approx. diameter) and place it on y=0.
        - Attach the remaining nodes as trees above/below the backbone using a tidy-tree layout.
        """
        positions: Dict[str, QPointF] = {}
        self._schem_tree_segment_ids = set()

        if not self._schem_keep_nodes:
            return positions

        components = self._schem_connected_components(self._schem_keep_nodes)

        x_offset = 0.0
        component_gap = 520.0
        backbone_node_spacing = 220.0

        for comp in components:
            comp_set = set(comp)

            # Prefer a station representative as anchor when available.
            anchors = [nid for nid in self._station_rep_node_id.values() if nid in comp_set]
            start = anchors[0] if anchors else min(comp_set, key=self._node_sort_key)

            dist1, _, _, _ = self._schem_dijkstra([start], comp_set)
            if not dist1:
                # Isolated node
                positions[start] = QPointF(x_offset, 0.0)
                x_offset += component_gap
                continue

            a = max(dist1.items(), key=lambda kv: kv[1])[0]
            dist2, prev2, prev_edge2, _ = self._schem_dijkstra([a], comp_set)
            b = max(dist2.items(), key=lambda kv: kv[1])[0]

            backbone_nodes: List[str] = [b]
            backbone_edges: List[str] = []
            cur = b
            while cur != a and cur in prev2:
                backbone_edges.append(prev_edge2[cur])
                cur = prev2[cur]
                backbone_nodes.append(cur)
            backbone_nodes.reverse()
            backbone_edges.reverse()

            backbone_set = set(backbone_nodes)

            # Place backbone on the baseline (y=0) from left to right.
            x = x_offset
            positions[backbone_nodes[0]] = QPointF(x, 0.0)
            for u, seg_id in zip(backbone_nodes[1:], backbone_edges):
                seg = self._schem_segments.get(seg_id)
                w = seg.length_m if seg is not None else 1.0
                dx = backbone_node_spacing + min(320.0, math.log1p(max(0.0, w)) * 35.0)
                x += dx
                positions[u] = QPointF(x, 0.0)

            # Multi-source shortest-path forest rooted at the backbone nodes.
            dist_f, prev_f, prev_edge_f, root = self._schem_dijkstra(backbone_nodes, comp_set)
            children: Dict[str, List[str]] = {nid: [] for nid in comp_set}
            for nid, parent in prev_f.items():
                if nid in backbone_set:
                    continue
                children.setdefault(parent, []).append(nid)

            tree_segment_ids = set(backbone_edges)
            tree_segment_ids |= {eid for nid, eid in prev_edge_f.items() if nid not in backbone_set}
            self._schem_tree_segment_ids |= tree_segment_ids

            leaf_gap = 34.0
            band_padding = 30.0
            attach_dx = 140.0
            depth_dx = 110.0
            first_branch_offset = 170.0

            def leaf_count(nid: str) -> int:
                kids = children.get(nid, [])
                if not kids:
                    return 1
                return sum(leaf_count(k) for k in kids)

            def layout_subtree(
                nid: str,
                *,
                depth: int,
                x0: float,
                origin: float,
                sign: float,
                cursor: List[float],
            ) -> float:
                kids = sorted(children.get(nid, []), key=self._node_sort_key)
                x_here = x0 + depth * depth_dx
                if not kids:
                    y_local = cursor[0]
                    cursor[0] += leaf_gap
                    positions[nid] = QPointF(x_here, sign * (origin + y_local))
                    return y_local

                child_centers: List[float] = []
                for k in kids:
                    child_centers.append(
                        layout_subtree(k, depth=depth + 1, x0=x0, origin=origin, sign=sign, cursor=cursor)
                    )
                y_local = (child_centers[0] + child_centers[-1]) / 2.0
                positions[nid] = QPointF(x_here, sign * (origin + y_local))
                return y_local

            # Attach branches per backbone node in separate vertical bands above and below.
            for bnode in backbone_nodes:
                bx = positions[bnode].x()
                branch_roots = [c for c in children.get(bnode, []) if c not in backbone_set]
                if not branch_roots:
                    continue

                branch_roots = sorted(branch_roots, key=self._node_sort_key)
                up_offset = first_branch_offset
                down_offset = first_branch_offset

                for i, rnode in enumerate(branch_roots):
                    leaves = leaf_count(rnode)
                    height = leaves * leaf_gap
                    if i % 2 == 0:
                        sign = -1.0
                        origin = up_offset
                        up_offset += height + band_padding
                    else:
                        sign = 1.0
                        origin = down_offset
                        down_offset += height + band_padding

                    cursor = [0.0]
                    layout_subtree(
                        rnode,
                        depth=0,
                        x0=bx + attach_dx,
                        origin=origin,
                        sign=sign,
                        cursor=cursor,
                    )

            # Any leftover nodes (rare): place near their closest backbone root.
            for nid in comp_set:
                if nid in positions:
                    continue
                rb = root.get(nid)
                if rb and rb in positions:
                    positions[nid] = QPointF(positions[rb].x() + attach_dx, first_branch_offset)
                else:
                    positions[nid] = QPointF(x_offset, 0.0)

            x_offset = max(x_offset, x) + component_gap

        return positions

    def _schematic_segment_path(self, seg: SchematicSegment) -> Optional[QPainterPath]:
        a = self._node_positions.get(seg.source)
        b = self._node_positions.get(seg.target)
        if a is None or b is None:
            return None

        # Slight offset for parallel segments
        off = float(self._schem_segment_parallel_offset_y.get(seg.id, 0.0))

        p0 = QPointF(a)
        p1 = QPointF(b)
        mid_x = (p0.x() + p1.x()) / 2.0
        mid_x += off

        base = [p0, QPointF(mid_x, p0.y()), QPointF(mid_x, p1.y()), p1]
        dy = abs(float(p1.y() - p0.y()))
        bevel = min(32.0, 0.35 * dy)
        pts = self._axis_polyline_with_45deg_corners(base, bevel=bevel)
        return self._path_from_points(pts)

    def _plan_segment_path(
        self,
        p0: QPointF,
        p1: QPointF,
        *,
        n_tracks: int,
        track_spacing: float,
    ) -> QPainterPath:
        """
        Orthogonal connection with 45° chamfers, optionally repeated for N parallel tracks.

        Note: this operates purely on endpoints (plan has "station ports"), not on node IDs.
        """
        p0 = QPointF(p0)
        p1 = QPointF(p1)

        dx = float(p1.x() - p0.x())
        dy = float(p1.y() - p0.y())

        if abs(dy) <= 1e-6:
            base = [p0, p1]
        else:
            sign = 1.0 if dx >= 0.0 else -1.0
            abs_dx = abs(dx)
            stub = min(150.0, max(70.0, abs_dx * 0.18))
            stub = min(stub, abs_dx / 2.0) if abs_dx > 1e-6 else 0.0
            x0 = p0.x() + sign * stub
            x1 = p1.x() - sign * stub
            if abs_dx <= 1e-6:
                x0 = p0.x()
                x1 = p1.x()
            if (sign > 0 and x0 > x1) or (sign < 0 and x0 < x1):
                x0 = (p0.x() + p1.x()) / 2.0
                x1 = x0
            base = [p0, QPointF(x0, p0.y()), QPointF(x1, p0.y()), QPointF(x1, p1.y()), p1]

        bevel = min(36.0, 0.35 * max(18.0, abs(dy)))
        pts = self._axis_polyline_with_45deg_corners(base, bevel=bevel)

        n_tracks = max(1, min(6, int(n_tracks)))
        if n_tracks == 1:
            return self._path_from_points(pts)

        mid = (n_tracks - 1) / 2.0
        path = QPainterPath()
        for i in range(n_tracks):
            offset = (i - mid) * float(track_spacing)
            o_pts = self._offset_polyline(pts, offset)
            if len(o_pts) >= 2:
                path.addPath(self._path_from_points(o_pts))
        return path

    def _compute_plan_positions(self) -> Dict[str, QPointF]:
        """
        Layout for plan view (more spacing and a stronger "mainline" compared to schematic).
        """
        positions: Dict[str, QPointF] = {}
        self._schem_tree_segment_ids = set()

        if not self._schem_keep_nodes:
            return positions

        components = self._schem_connected_components(self._schem_keep_nodes)

        x_offset = 0.0
        component_gap = 620.0
        backbone_node_spacing = 240.0

        for comp in components:
            comp_set = set(comp)

            anchors = [nid for nid in self._station_rep_node_id.values() if nid in comp_set]
            start = anchors[0] if anchors else min(comp_set, key=self._node_sort_key)

            dist1, _, _, _ = self._schem_dijkstra([start], comp_set)
            if not dist1:
                positions[start] = QPointF(x_offset, 0.0)
                x_offset += component_gap
                continue

            a = max(dist1.items(), key=lambda kv: kv[1])[0]
            dist2, prev2, prev_edge2, _ = self._schem_dijkstra([a], comp_set)
            b = max(dist2.items(), key=lambda kv: kv[1])[0]

            backbone_nodes: List[str] = [b]
            backbone_edges: List[str] = []
            cur = b
            while cur != a and cur in prev2:
                backbone_edges.append(prev_edge2[cur])
                cur = prev2[cur]
                backbone_nodes.append(cur)
            backbone_nodes.reverse()
            backbone_edges.reverse()
            backbone_set = set(backbone_nodes)

            x = x_offset
            positions[backbone_nodes[0]] = QPointF(x, 0.0)
            for u, seg_id in zip(backbone_nodes[1:], backbone_edges):
                seg = self._schem_segments.get(seg_id)
                w = seg.length_m if seg is not None else 1.0
                dx = backbone_node_spacing + min(520.0, math.log1p(max(0.0, w)) * 55.0)
                x += dx
                positions[u] = QPointF(x, 0.0)

            dist_f, prev_f, prev_edge_f, root = self._schem_dijkstra(backbone_nodes, comp_set)
            children: Dict[str, List[str]] = {nid: [] for nid in comp_set}
            for nid, parent in prev_f.items():
                if nid in backbone_set:
                    continue
                children.setdefault(parent, []).append(nid)

            tree_segment_ids = set(backbone_edges)
            tree_segment_ids |= {eid for nid, eid in prev_edge_f.items() if nid not in backbone_set}
            self._schem_tree_segment_ids |= tree_segment_ids

            leaf_gap = 40.0
            band_padding = 55.0
            attach_dx = 180.0
            depth_dx = 140.0
            first_branch_offset = 220.0

            def leaf_count(nid: str) -> int:
                kids = children.get(nid, [])
                if not kids:
                    return 1
                return sum(leaf_count(k) for k in kids)

            def layout_subtree(
                nid: str,
                *,
                depth: int,
                x0: float,
                origin: float,
                sign: float,
                cursor: List[float],
            ) -> float:
                kids = sorted(children.get(nid, []), key=self._node_sort_key)
                x_here = x0 + depth * depth_dx
                if not kids:
                    y_local = cursor[0]
                    cursor[0] += leaf_gap
                    positions[nid] = QPointF(x_here, sign * (origin + y_local))
                    return y_local

                child_centers: List[float] = []
                for k in kids:
                    child_centers.append(
                        layout_subtree(k, depth=depth + 1, x0=x0, origin=origin, sign=sign, cursor=cursor)
                    )
                y_local = (child_centers[0] + child_centers[-1]) / 2.0
                positions[nid] = QPointF(x_here, sign * (origin + y_local))
                return y_local

            up_offset = 0.0
            down_offset = 0.0
            for bnode in backbone_nodes:
                bx = positions[bnode].x()
                branch_roots = [c for c in children.get(bnode, []) if c not in backbone_set]
                if not branch_roots:
                    continue

                branch_roots = sorted(branch_roots, key=lambda n: (-leaf_count(n), self._node_sort_key(n)))
                flip = True
                for rnode in branch_roots:
                    height = max(1, leaf_count(rnode)) * leaf_gap
                    if flip:
                        origin = first_branch_offset + up_offset
                        sign = -1.0
                        up_offset += height + band_padding
                    else:
                        origin = first_branch_offset + down_offset
                        sign = 1.0
                        down_offset += height + band_padding
                    flip = not flip

                    cursor = [0.0]
                    layout_subtree(
                        rnode,
                        depth=0,
                        x0=bx + attach_dx,
                        origin=origin,
                        sign=sign,
                        cursor=cursor,
                    )

            for nid in comp_set:
                if nid in positions:
                    continue
                rb = root.get(nid)
                if rb and rb in positions:
                    positions[nid] = QPointF(positions[rb].x() + attach_dx, first_branch_offset)
                else:
                    positions[nid] = QPointF(x_offset, 0.0)

            x_offset = max(x_offset, x) + component_gap

        # Small quantization for the plan look.
        qy = 6.0
        for nid, p in list(positions.items()):
            positions[nid] = QPointF(p.x(), round(p.y() / qy) * qy)

        return positions

    def _plan_build_station_blocks(
        self,
        *,
        pair_parallel: Dict[Tuple[str, str], int],
        segment_parallel_tracks,
        track_spacing: float,
        block_len: float,
    ) -> Tuple[Dict[Tuple[str, str], QPointF], Dict[str, Tuple[str, QPointF, int]]]:
        """
        Returns:
        - endpoint position overrides: (segmentId, endpointNodeId) -> QPointF
        - station blocks: stationName -> (repNodeId, centerPos, trackCount)
        """
        endpoint_overrides: Dict[Tuple[str, str], QPointF] = {}
        station_blocks: Dict[str, Tuple[str, QPointF, int]] = {}

        if not self._station_rep_node_id:
            return endpoint_overrides, station_blocks

        # Determine station track counts from external connections (heuristic).
        station_node_sets = self._station_nodes_map()
        schem_station_nodes: Dict[str, set[str]] = {}
        for name, rep in self._station_rep_node_id.items():
            nodes = {nid for nid, s in self._node_to_station.items() if s == name and nid in self._schem_keep_nodes}
            if not nodes:
                # fallback to heuristic station nodes (intersect keep set)
                nodes = {nid for nid in station_node_sets.get(name, set()) if nid in self._schem_keep_nodes}
            schem_station_nodes[name] = nodes

        def estimated_station_tracks(name: str) -> int:
            nodes = schem_station_nodes.get(name, set())
            if not nodes:
                return 1
            external = 0
            for seg in self._schem_segments.values():
                a_in = seg.source in nodes
                b_in = seg.target in nodes
                if a_in == b_in:
                    continue
                external += int(segment_parallel_tracks(seg))
            return max(1, int(math.ceil(external / 2.0)))

        for name, rep_node_id in sorted(self._station_rep_node_id.items(), key=lambda kv: kv[0]):
            pos = self._node_positions.get(rep_node_id)
            if pos is None:
                continue
            n_tracks = max(1, min(10, estimated_station_tracks(name)))
            station_blocks[name] = (rep_node_id, QPointF(pos), n_tracks)

        # Assign station "ports" per connected segment so lines attach to visible station tracks.
        block_len = float(block_len)
        spacing = float(track_spacing)

        for name, (rep_node_id, center, n_tracks) in station_blocks.items():
            nodes = schem_station_nodes.get(name, set())
            if not nodes:
                continue

            lanes = [center.y() + (i - (n_tracks - 1) / 2.0) * spacing for i in range(n_tracks)]
            lane_indices = list(range(n_tracks))

            left: List[Tuple[float, str, str]] = []   # (other_y, segId, endpointNodeId)
            right: List[Tuple[float, str, str]] = []
            for seg in self._schem_segments.values():
                if seg.source in nodes and seg.target not in nodes:
                    other = self._node_positions.get(seg.target)
                    if other is None:
                        continue
                    side = left if other.x() < center.x() else right
                    side.append((float(other.y()), seg.id, seg.source))
                elif seg.target in nodes and seg.source not in nodes:
                    other = self._node_positions.get(seg.source)
                    if other is None:
                        continue
                    side = left if other.x() < center.x() else right
                    side.append((float(other.y()), seg.id, seg.target))

            def assign_ports(items: List[Tuple[float, str, str]], *, x: float) -> None:
                if not items:
                    return
                items.sort(key=lambda t: (t[0], t[1], t[2]))
                if len(items) <= n_tracks:
                    # Spread across lanes in order.
                    for (item, li) in zip(items, lane_indices):
                        _, seg_id, endpoint = item
                        endpoint_overrides[(seg_id, endpoint)] = QPointF(x, lanes[li])
                else:
                    # More connections than tracks: wrap but keep visual order.
                    for idx, item in enumerate(items):
                        _, seg_id, endpoint = item
                        li = lane_indices[idx % n_tracks]
                        endpoint_overrides[(seg_id, endpoint)] = QPointF(x, lanes[li])

            assign_ports(left, x=center.x() - block_len / 2.0)
            assign_ports(right, x=center.x() + block_len / 2.0)

        return endpoint_overrides, station_blocks

    def _plan_draw_station_blocks(
        self,
        station_blocks: Dict[str, Tuple[str, QPointF, int]],
        *,
        track_spacing: float,
        block_len: float,
    ) -> None:
        if not station_blocks:
            return

        if self._current_theme == "dark":
            outer_pen = QPen(Qt.GlobalColor.lightGray)
        else:
            outer_pen = QPen(Qt.GlobalColor.black)
        outer_pen.setWidthF(7.2)
        outer_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        outer_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        for name, (rep_node_id, center, n_tracks) in station_blocks.items():
            n_tracks = max(1, int(n_tracks))
            mid = (n_tracks - 1) / 2.0
            x0 = center.x() - block_len / 2.0
            x1 = center.x() + block_len / 2.0

            path = QPainterPath()
            for i in range(n_tracks):
                y = center.y() + (i - mid) * float(track_spacing)
                path.moveTo(QPointF(x0, y))
                path.lineTo(QPointF(x1, y))

            outer = QGraphicsPathItem(path)
            outer.setPen(outer_pen)
            outer.setZValue(2.0)
            outer.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            outer.setData(1, rep_node_id)
            outer.setData(2, "station")
            outer.setToolTip(f"{name}\nGleise≈{n_tracks}")
            self._scene.addItem(outer)

            # Track numbers (1..N)
            for i in range(n_tracks):
                y = center.y() + (i - mid) * float(track_spacing)
                num = QGraphicsSimpleTextItem(str(i + 1))
                if self._current_theme == "dark":
                    num.setBrush(QBrush(Qt.GlobalColor.white))
                else:
                    num.setBrush(QBrush(Qt.GlobalColor.black))
                num.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                num.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
                brn = num.boundingRect()
                num.setPos(QPointF(x1 + 8.0, y - brn.height() / 2.0))
                num.setZValue(25.0)
                num.setData(1, rep_node_id)
                num.setData(2, "station")
                self._scene.addItem(num)

            # Label with white box (click target for route selection).
            label_text = name if len(name) <= 34 else (name[:31].rstrip() + "...")
            label = QGraphicsSimpleTextItem(label_text)
            if self._current_theme == "dark":
                label.setBrush(QBrush(Qt.GlobalColor.white))
            else:
                label.setBrush(QBrush(Qt.GlobalColor.black))
            label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            label.setData(1, rep_node_id)
            label.setData(2, "station")
            br = label.boundingRect()
            if center.y() >= 0.0:
                label_y = center.y() + (20.0 + mid * track_spacing)
            else:
                label_y = center.y() - (46.0 + mid * track_spacing)
            label_pos = QPointF(center.x() - br.width() / 2.0, label_y)

            box = QGraphicsRectItem(QRectF(0.0, 0.0, br.width() + 12.0, br.height() + 8.0))
            box.setPos(QPointF(label_pos.x() - 6.0, label_pos.y() - 4.0))
            if self._current_theme == "dark":
                box.setBrush(QBrush(QColor(34, 34, 34)))
                box_pen = QPen(Qt.GlobalColor.white)
            else:
                box.setBrush(QBrush(Qt.GlobalColor.white))
                box_pen = QPen(Qt.GlobalColor.black)
            box_pen.setWidthF(1.0)
            box.setPen(box_pen)
            box.setZValue(20.0)
            box.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            box.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            box.setData(1, rep_node_id)
            box.setData(2, "station")
            box.setToolTip(f"{name}\nGleise≈{n_tracks}")
            self._scene.addItem(box)

            label.setPos(label_pos)
            label.setZValue(21.0)
            self._scene.addItem(label)

    def _add_schematic_station_markers(self) -> None:
        # Clear old station overlay items
        for it in getattr(self, "_schem_station_items", []):
            try:
                self._scene.removeItem(it)
            except Exception:
                pass
        self._schem_station_items = []

        if not self._station_rep_node_id:
            return

        station_nodes = self._station_nodes_map()

        def estimated_station_tracks(nodes: set[str]) -> int:
            external = 0
            for seg in self._schem_segments.values():
                a_in = seg.source in nodes
                b_in = seg.target in nodes
                if a_in == b_in:
                    continue
                external += max(1, len(seg.track_ids))
            # Each through track typically contributes two external connections (left/right).
            return max(1, int(math.ceil(external / 2.0)))

        for name, rep_node_id in sorted(self._station_rep_node_id.items(), key=lambda kv: kv[0]):
            pos = self._node_positions.get(rep_node_id)
            if pos is None:
                continue

            nodes = station_nodes.get(name, set())
            n_tracks = estimated_station_tracks(nodes) if nodes else 1
            dot = QGraphicsEllipseItem(-7.0, -7.0, 14.0, 14.0)
            dot.setPos(pos)
            dot.setBrush(QBrush(Qt.GlobalColor.red))
            
            if self._current_theme == "dark":
                dot_pen = QPen(QColor(34, 34, 34))
            else:
                dot_pen = QPen(Qt.GlobalColor.black)
            dot_pen.setWidthF(1.0)
            dot.setPen(dot_pen)
            dot.setZValue(30)
            dot.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            dot.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            dot.setData(1, rep_node_id)
            dot.setData(2, "station")
            dot.setToolTip(f"{name}\nGleise≈{n_tracks}")
            self._scene.addItem(dot)
            self._schem_station_items.append(dot)

            label_text = name
            if len(label_text) > 28:
                label_text = label_text[:25].rstrip() + "..."
            label = QGraphicsSimpleTextItem(label_text)
            label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            
            if self._current_theme == "dark":
                label.setBrush(QBrush(Qt.GlobalColor.white))
            else:
                label.setBrush(QBrush(Qt.GlobalColor.black))

            label.setData(1, rep_node_id)
            label.setData(2, "station")
            br = label.boundingRect()
            label.setPos(QPointF(pos.x() - br.width() / 2.0, pos.y() - 22.0))
            label.setZValue(31)
            self._scene.addItem(label)
            self._schem_station_items.append(label)

    @staticmethod
    def _median(values: List[float]) -> float:
        if not values:
            return math.inf
        values = sorted(values)
        return values[len(values) // 2]

    def _compute_topological_positions(self) -> Dict[str, QPointF]:
        positions: Dict[str, QPointF] = {}
        if not self._nodes:
            return positions

        # Schematic layout:
        # - cluster nodes by station/stoppingLocationGroup
        # - keep everything mostly 1D (y=0) for route planning
        # - add large gaps between stations so the view is readable when zoomed out
        self._topo_node_index = {}
        self._topo_station_layout = []
        self._node_to_station = {}
        self._station_rep_node_id = {}
        self._station_rect_items = {}

        node_spacing = 190.0
        group_node_spacing = 115.0
        group_padding = 160.0
        group_gap = 520.0
        component_gap = 640.0

        station_nodes = self._station_nodes_map()

        def station_key(nodes: set[str]) -> float:
            nums = [
                float(self._nodes[nid].numeric_id)
                for nid in nodes
                if nid in self._nodes and self._nodes[nid].numeric_id is not None
            ]
            return self._median(nums)

        current_x_offset = 0.0
        global_idx = 0
        for comp_idx, comp in enumerate(self._connected_components()):
            comp_set = set(comp)

            comp_station_nodes: Dict[str, set[str]] = {}
            for name, nodes in station_nodes.items():
                inter = nodes & comp_set
                if inter:
                    comp_station_nodes[name] = inter

            grouped_nodes: set[str] = set()
            for nodes in comp_station_nodes.values():
                grouped_nodes |= nodes

            ungrouped = [nid for nid in comp if nid not in grouped_nodes]

            elements: List[Tuple[float, int, str]] = []
            group_payload: Dict[str, List[str]] = {}

            for name, nodes in comp_station_nodes.items():
                group_payload[name] = sorted(nodes, key=self._node_sort_key)
                rep = group_payload[name][len(group_payload[name]) // 2]
                self._station_rep_node_id[name] = rep
                for nid in group_payload[name]:
                    self._node_to_station.setdefault(nid, name)
                elements.append((station_key(nodes), 0, name))

            for nid in ungrouped:
                node = self._nodes.get(nid)
                key = float(node.numeric_id) if node and node.numeric_id is not None else math.inf
                elements.append((key, 1, nid))

            # kind: 0 = station cluster, 1 = standalone node
            elements.sort(key=lambda t: (t[0], t[1], t[2]))

            for _, kind, payload in elements:
                if kind == 0:
                    name = payload
                    nodes = group_payload.get(name, [])
                    if not nodes:
                        continue

                    x0 = current_x_offset
                    x = current_x_offset + group_padding
                    for nid in nodes:
                        positions[nid] = QPointF(x, 0.0)
                        self._topo_node_index[nid] = global_idx
                        global_idx += 1
                        x += group_node_spacing
                    x1 = (x - group_node_spacing) + group_padding

                    self._topo_station_layout.append((name, x0, x1, comp_idx))
                    current_x_offset = x1 + group_gap
                else:
                    nid = payload
                    positions[nid] = QPointF(current_x_offset, 0.0)
                    self._topo_node_index[nid] = global_idx
                    global_idx += 1
                    current_x_offset += node_spacing

            current_x_offset += component_gap

        return positions

    def _connected_components(self) -> List[List[str]]:
        remaining = set(self._nodes.keys())
        components: List[List[str]] = []
        while remaining:
            start = min(remaining, key=self._node_sort_key)
            stack = [start]
            remaining.remove(start)
            comp: List[str] = []
            while stack:
                u = stack.pop()
                comp.append(u)
                for v, _, _ in self._graph.get(u, []):
                    if v in remaining:
                        remaining.remove(v)
                        stack.append(v)
            components.append(comp)
        return components

    @staticmethod
    def _intervals_overlap(a0: int, a1: int, b0: int, b1: int) -> bool:
        return not (a1 <= b0 or b1 <= a0)

    def _compute_topological_track_offsets(self) -> Dict[str, float]:
        """
        Assign per-track vertical offsets for schematic (topological) rendering.

        - "Mainline" tracks between adjacent nodes are drawn on the baseline (y=0).
        - Additional parallel tracks between adjacent nodes get small offsets.
        - Longer connections are routed as arcs in higher lanes to stay readable.
        """
        idx = self._topo_node_index
        if not idx:
            return {}

        adjacent: Dict[Tuple[int, int], List[str]] = {}
        skip_intervals: List[Tuple[int, int, str]] = []

        for tr in self._tracks.values():
            a = idx.get(tr.source)
            b = idx.get(tr.target)
            if a is None or b is None or a == b:
                continue
            i0, i1 = (a, b) if a < b else (b, a)
            if i1 - i0 == 1:
                adjacent.setdefault((i0, i1), []).append(tr.id)
            else:
                skip_intervals.append((i0, i1, tr.id))

        offsets: Dict[str, float] = {}

        parallel_gap = 14.0
        for _, track_ids in adjacent.items():
            # Pick one to represent the baseline connection.
            baseline = min(
                track_ids,
                key=lambda tid: (
                    self._tracks[tid].length_m if self._tracks[tid].length_m > 0 else math.inf,
                    tid,
                ),
            )
            offsets[baseline] = 0.0
            others = [tid for tid in track_ids if tid != baseline]
            for k, tid in enumerate(sorted(others)):
                offsets[tid] = (k + 1) * parallel_gap

        lane_spacing = 72.0
        lanes: List[List[Tuple[int, int]]] = []
        skip_intervals.sort(key=lambda t: (-(t[1] - t[0]), t[0], t[2]))

        for a0, a1, tid in skip_intervals:
            if tid in offsets:
                continue
            lane_idx: Optional[int] = None
            for i, lane in enumerate(lanes):
                if all(not self._intervals_overlap(a0, a1, b0, b1) for (b0, b1) in lane):
                    lane_idx = i
                    lane.append((a0, a1))
                    break
            if lane_idx is None:
                lane_idx = len(lanes)
                lanes.append([(a0, a1)])
            offsets[tid] = (lane_idx + 1) * lane_spacing

        return offsets

    def _add_topological_station_markers(self) -> None:
        self._station_rect_items = {}
        if not self._topo_station_layout:
            return

        pen = QPen(Qt.GlobalColor.lightGray)
        pen.setWidthF(1.0)
        pen.setStyle(Qt.PenStyle.DashLine)

        for name, x0, x1, _ in self._topo_station_layout:
            rep_node_id = self._station_rep_node_id.get(name)
            w = max(1.0, x1 - x0)
            rect = QGraphicsRectItem(QRectF(x0, -95.0, w, 190.0))
            rect.setPen(pen)
            rect.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            rect.setZValue(-10)
            rect.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            if rep_node_id:
                rect.setData(1, rep_node_id)
                rect.setData(2, "stationRect")
            self._scene.addItem(rect)
            self._station_rect_items[name] = rect

            # Clickable marker dot on the baseline
            if rep_node_id:
                dot = QGraphicsEllipseItem(-6.0, -6.0, 12.0, 12.0)
                dot.setPos(QPointF(x0 + w / 2.0, 0.0))
                dot.setBrush(QBrush(Qt.GlobalColor.red))
                dot_pen = QPen(Qt.GlobalColor.black)
                dot_pen.setWidthF(1.0)
                dot.setPen(dot_pen)
                dot.setZValue(15)
                dot.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
                dot.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                dot.setData(1, rep_node_id)
                dot.setData(2, "station")
                self._scene.addItem(dot)

            label_text = name
            if len(label_text) > 28:
                label_text = label_text[:25].rstrip() + "..."
            label = QGraphicsSimpleTextItem(label_text)
            label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            if rep_node_id:
                label.setData(1, rep_node_id)
                label.setData(2, "station")
            br = label.boundingRect()
            label.setPos(QPointF(x0 + w / 2.0 - br.width() / 2.0, -118.0))
            label.setZValue(50)
            self._scene.addItem(label)

    def _add_topological_skeleton_edges(self) -> None:
        if not self._topo_station_layout:
            return

        by_comp: Dict[int, List[float]] = {}
        for _, x0, x1, comp_idx in self._topo_station_layout:
            by_comp.setdefault(comp_idx, []).append((x0 + x1) / 2.0)

        for comp_idx, centers in by_comp.items():
            centers.sort()
            for i, (a, b) in enumerate(zip(centers[:-1], centers[1:])):
                pts = [QPointF(a, 0.0), QPointF(b, 0.0)]
                pts = self._axis_polyline_with_45deg_corners(pts, bevel=24.0)
                path = self._path_from_points(pts)
                item = TrackItem(f"__topo_skeleton__:{comp_idx}:{i}", path)
                item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                item.inner_overlay().setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                self._scene.addItem(item)
                self._scene.addItem(item.inner_overlay())

    def _node_sort_key(self, node_id: str) -> Tuple[float, str]:
        node = self._nodes.get(node_id)
        numeric = float(node.numeric_id) if node and node.numeric_id is not None else math.inf
        return numeric, node_id

    # --------------
    # View fitting
    # --------------

    def _fit_to_scene(self) -> None:
        """Fit the view so the whole infrastructure is visible.

        We call this after the widget has a real size (QTimer.singleShot(0, ...)).
        """
        if self._view.viewport().width() <= 2 or self._view.viewport().height() <= 2:
            return

        items_rect = self._scene.itemsBoundingRect()
        if items_rect.isNull():
            return

        if self._layout_mode in {"topological", "plan"}:
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_overlay_widgets()
        # Do the initial fit once, when the widget first gets a meaningful size.
        if not getattr(self, "_initial_fit_done", False):
            QTimer.singleShot(0, self._fit_to_scene)

    # -----------
    # Interaction / event filter
    # -----------

    def _can_start_background_pan(self, scene_pos: QPointF) -> bool:
        if self._layout_mode in {"topological", "plan"}:
            for cand in self._scene.items(scene_pos):
                if cand.data(2) == "station":
                    return False
                top = cand.topLevelItem()
                if isinstance(top, NodeItem):
                    return False
            return True

        for cand in self._scene.items(scene_pos):
            top = cand.topLevelItem()
            if isinstance(top, (TimingPointItem, NodeItem)):
                return False

        return self._pick_track_id_near(scene_pos) is None

    def _scene_distance_for_view_pixels(self, px: float) -> float:
        t = self._view.transform()
        sx = abs(float(t.m11()))
        sy = abs(float(t.m22()))
        s = (sx + sy) / 2.0 if sx > 1e-9 and sy > 1e-9 else max(sx, sy, 1.0)
        if s <= 1e-9:
            return float(px)
        return float(px) / s

    def _dist_sq_point_to_segment(self, p: QPointF, a: QPointF, b: QPointF) -> float:
        ax = float(a.x())
        ay = float(a.y())
        bx = float(b.x())
        by = float(b.y())
        px = float(p.x())
        py = float(p.y())

        abx = bx - ax
        aby = by - ay
        apx = px - ax
        apy = py - ay
        ab_len_sq = abx * abx + aby * aby
        if ab_len_sq <= 1e-12:
            dx = px - ax
            dy = py - ay
            return dx * dx + dy * dy

        t = (apx * abx + apy * aby) / ab_len_sq
        if t <= 0.0:
            cx, cy = ax, ay
        elif t >= 1.0:
            cx, cy = bx, by
        else:
            cx = ax + t * abx
            cy = ay + t * aby
        dx = px - cx
        dy = py - cy
        return dx * dx + dy * dy

    def _min_dist_sq_to_polyline(self, p: QPointF, pts: List[QPointF]) -> float:
        if len(pts) < 2:
            dx = float(p.x() - pts[0].x())
            dy = float(p.y() - pts[0].y())
            return dx * dx + dy * dy

        best = float("inf")
        for a, b in zip(pts[:-1], pts[1:]):
            d = self._dist_sq_point_to_segment(p, a, b)
            if d < best:
                best = d
        return best

    def _pick_track_id_near(self, scene_pos: QPointF, tolerance_px: float = 8.0) -> Optional[str]:
        tol_scene = self._scene_distance_for_view_pixels(tolerance_px)
        tol_sq = tol_scene * tol_scene

        best_id: Optional[str] = None
        best_d = float("inf")
        for tr in self._tracks.values():
            pts = self._polyline_points_for_track(tr)
            if not pts:
                continue
            d = self._min_dist_sq_to_polyline(scene_pos, pts)
            if d <= tol_sq and d < best_d:
                best_d = d
                best_id = tr.id
        return best_id

    def _track_id_from_item(self, item: Optional[QGraphicsItem]) -> Optional[str]:
        if item is None:
            return None
        if isinstance(item, TrackItem):
            return item.track_id
        data = item.data(0)
        if isinstance(data, str) and data in self._tracks:
            return data
        return None

    def _toggle_track_timing_points(self, track_id: str) -> None:
        if not self._keep_selection and track_id not in self._visible_tp_tracks:
            # If not keeping selection and clicking a new track, clear others.
            # But we must be careful: if we just clear, we lose the toggle logic.
            # The user said: "You click on another track and the timing points that were previously selected on another track will disappear."
            # This implies if I select A, then select B, A should deselect.
            # If I select A, then select A again, A should deselect.
            old_visible = list(self._visible_tp_tracks)
            self._visible_tp_tracks.clear()
            for old_id in old_visible:
                self._apply_track_tp_visibility(old_id, False)

        visible = track_id not in self._visible_tp_tracks
        if visible:
            self._visible_tp_tracks.add(track_id)
        else:
            self._visible_tp_tracks.discard(track_id)
        self._apply_track_tp_visibility(track_id, visible)

    def _apply_track_tp_visibility(self, track_id: str, visible: bool) -> None:
        for tpi in self._tp_track_map.get(track_id, []):
            # Check for STOP constraint
            has_stop = False
            if tpi.tp.id in self._timing_constraints:
                c = self._timing_constraints[tpi.tp.id]
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
            if event.type() == QEvent.Type.GraphicsSceneMousePress:
                if self._layout_mode in {"topological", "plan"} and event.button() == Qt.MouseButton.LeftButton:
                    for cand in self._scene.items(event.scenePos()):
                        if cand.data(2) != "station":
                            continue
                        rep = cand.data(1)
                        if isinstance(rep, str):
                            self._handle_planning_station_click(rep, modifiers=event.modifiers())
                            return True

                item: Optional[QGraphicsItem] = None
                for cand in self._scene.items(event.scenePos()):
                    top = cand.topLevelItem()
                    if isinstance(top, (TimingPointItem, NodeItem)):
                        item = top
                        break

                # Timing point interactions
                if isinstance(item, TimingPointItem):
                    if event.button() == Qt.MouseButton.LeftButton:
                        self._edit_timing_constraint(item.tp.id)
                        return True
                    if event.button() == Qt.MouseButton.RightButton:
                        self._remove_timing_constraint(item.tp.id)
                        return True

                # Route selection
                if isinstance(item, NodeItem):
                    if event.button() == Qt.MouseButton.LeftButton:
                        # In plan/topological mode we plan station-to-station via click targets.
                        if self._layout_mode in {"topological", "plan"}:
                            return False
                        self._extend_route_with_node(item.node.id)
                        return True

                if event.button() == Qt.MouseButton.LeftButton:
                    track_id = self._pick_track_id_near(event.scenePos())
                else:
                    track_id = None

                if self._layout_mode not in {"topological", "plan"} and track_id and event.button() == Qt.MouseButton.LeftButton:
                    self._toggle_track_timing_points(track_id)
                    return True

                # Clicking empty space does nothing special.

        return super().eventFilter(obj, event)

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

    # -----------
    # Route selection
    # -----------

    def clear_route(self) -> None:
        self._route_node_ids = []
        self._route_track_ids = []
        self._route_plan_start = None
        self._route_plan_goal = None
        self._route_plan_waypoints = []
        self._update_route_highlights()
        self._update_planning_status_labels()
        self.routeChanged.emit(list(self._route_node_ids))

    def _station_label_for_node(self, node_id: str) -> str:
        name = self._node_to_station.get(node_id)
        if name:
            return name
        node = self._nodes.get(node_id)
        if node and node.numeric_id is not None:
            return f"Node {node.numeric_id}"
        return "Node"

    def _update_planning_status_labels(self) -> None:
        if not hasattr(self, "_start_status"):
            return
        if self._route_plan_start:
            self._start_status.setText(f"Start: {self._station_label_for_node(self._route_plan_start)}")
        else:
            self._start_status.setText("Start: -")
        if self._route_plan_goal:
            self._goal_status.setText(f"Ziel: {self._station_label_for_node(self._route_plan_goal)}")
        else:
            self._goal_status.setText("Ziel: -")

    def _update_legend_text(self) -> None:
        if getattr(self, "_legend", None) is None:
            return
        if self._layout_mode in {"topological", "plan"}:
            self._legend.setText(
                "<b>Legende</b><br>"
                "<span style='color:#000'>■</span> Gleis&nbsp;&nbsp;"
                "<span style='color:#00BCD4'>■</span> Route<br>"
                "<span style='color:#D32F2F'>●</span> Bahnhof<br><br>"
                "<b>Routenplanung</b><br>"
                "Klick: Start → Ziel (berechnet Route)<br>"
                "Shift+Klick: Zwischenhalt (Waypoint)<br>"
                "Klick nach fertiger Route: neue Route"
            )
        else:
            self._legend.setText(
                "<b>Legende</b><br>"
                "<span style='color:#606060'>■</span> Gleis&nbsp;&nbsp;"
                "<span style='color:#00008B'>■</span> Gleis (TPs an)&nbsp;&nbsp;"
                "<span style='color:#00BCD4'>■</span> Route<br>"
                "<span style='color:#1E90FF'>■</span> Hover&nbsp;&nbsp;"
                "<span style='color:#D32F2F'>●</span> Bahnhof/Node&nbsp;&nbsp;"
                "<span style='color:#1976D2'>●</span> Timing point&nbsp;&nbsp;"
                "<span style='color:#8B0000'>●</span> Halt"
            )
        self._position_overlay_widgets()

    def _set_planned_route_points(self, *, start: Optional[str], goal: Optional[str], waypoints: List[str]) -> None:
        self._route_plan_start = start
        self._route_plan_goal = goal
        self._route_plan_waypoints = list(waypoints or [])
        self._update_planning_status_labels()

    def _compute_planned_route(self) -> None:
        start = self._route_plan_start
        if not start or start not in self._nodes:
            self._route_node_ids = []
            self._route_track_ids = []
            self._update_route_highlights()
            self.routeChanged.emit(list(self._route_node_ids))
            return

        points: List[str] = [start]
        points += [p for p in self._route_plan_waypoints if p in self._nodes and p != points[-1]]
        if self._route_plan_goal and self._route_plan_goal in self._nodes and self._route_plan_goal != points[-1]:
            points.append(self._route_plan_goal)

        if len(points) == 1:
            self._route_node_ids = [start]
            self._route_track_ids = []
            self._update_route_highlights()
            self.routeChanged.emit(list(self._route_node_ids))
            return

        route_nodes: List[str] = []
        route_tracks: List[str] = []
        for a, b in zip(points[:-1], points[1:]):
            node_path, track_path = self._shortest_path(a, b)
            if len(node_path) <= 1:
                continue
            if not route_nodes:
                route_nodes.extend(node_path)
            else:
                route_nodes.extend(node_path[1:])
            route_tracks.extend(track_path)

        self._route_node_ids = route_nodes
        self._route_track_ids = route_tracks
        self._update_route_highlights()
        self.routeChanged.emit(list(self._route_node_ids))

    def _handle_planning_station_click(self, node_id: str, *, modifiers: Qt.KeyboardModifier) -> None:
        if node_id not in self._nodes:
            return

        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

        # Shift-click adds waypoints (Zwischenhalte).
        if shift:
            if not self._route_plan_start:
                self._set_planned_route_points(start=node_id, goal=None, waypoints=[])
            elif self._route_plan_goal:
                wps = [w for w in self._route_plan_waypoints if w != node_id]
                wps.append(node_id)
                self._set_planned_route_points(start=self._route_plan_start, goal=self._route_plan_goal, waypoints=wps)
            else:
                wps = [w for w in self._route_plan_waypoints if w != node_id]
                wps.append(node_id)
                self._set_planned_route_points(start=self._route_plan_start, goal=None, waypoints=wps)
            self._compute_planned_route()
            return

        # Normal click: start -> goal, then reset to new start after route is done.
        if not self._route_plan_start or (self._route_plan_start and self._route_plan_goal):
            self._set_planned_route_points(start=node_id, goal=None, waypoints=[])
            self._compute_planned_route()
            return

        if self._route_plan_start and not self._route_plan_goal:
            self._set_planned_route_points(start=self._route_plan_start, goal=node_id, waypoints=self._route_plan_waypoints)
            self._compute_planned_route()
            return

    def _extend_route_with_node(self, node_id: str) -> None:
        if node_id not in self._nodes:
            return

        if not self._route_node_ids:
            self._route_node_ids = [node_id]
            self._route_track_ids = []
        else:
            last = self._route_node_ids[-1]
            node_path, track_path = self._shortest_path(last, node_id)
            if len(node_path) <= 1:
                return
            # append, skipping the first because it's last
            self._route_node_ids.extend(node_path[1:])
            self._route_track_ids.extend(track_path)

        self._update_route_highlights()
        self.routeChanged.emit(list(self._route_node_ids))

    def _update_route_highlights(self) -> None:
        route_nodes = set(self._route_node_ids)
        route_tracks = set(self._route_track_ids)

        for nid, item in self._node_items.items():
            item.set_highlight(nid in route_nodes)

        for tid, item in self._track_items.items():
            if self._layout_mode in {"topological", "plan"}:
                seg = self._schem_segments.get(tid)
                enabled = bool(seg) and any(orig_tid in route_tracks for orig_tid in seg.track_ids)
            else:
                enabled = tid in route_tracks
            item.set_route_highlight(enabled)

    def _update_topological_route_overlay(self) -> None:
        default_pen = QPen(Qt.GlobalColor.lightGray)
        default_pen.setWidthF(1.0)
        default_pen.setStyle(Qt.PenStyle.DashLine)
        highlight_pen = QPen(Qt.GlobalColor.darkCyan)
        highlight_pen.setWidthF(2.0)
        highlight_pen.setStyle(Qt.PenStyle.SolidLine)

        for rect in self._station_rect_items.values():
            rect.setPen(default_pen)

        route_stations: List[str] = []
        for nid in self._route_node_ids:
            s = self._node_to_station.get(nid)
            if not s:
                continue
            if not route_stations or route_stations[-1] != s:
                route_stations.append(s)

        for s in route_stations:
            rect = self._station_rect_items.get(s)
            if rect:
                rect.setPen(highlight_pen)

        if self._topo_route_item is None:
            return

        centers = {name: (x0 + x1) / 2.0 for (name, x0, x1, _) in self._topo_station_layout}
        pts = [QPointF(centers[s], 0.0) for s in route_stations if s in centers]
        if len(pts) < 2:
            self._topo_route_item.setPath(QPainterPath())
            return

        pts = self._axis_polyline_with_45deg_corners(pts, bevel=24.0)
        path = self._path_from_points(pts)
        self._topo_route_item.setPath(path)

    def _restore_timing_point_markers(self) -> None:
        for tp_id, constraint in self._timing_constraints.items():
            item = self._tp_items.get(tp_id)
            if item:
                item.set_constraint_point_type(constraint.get("pointType"))
                item.setVisible(True)

    # -----------
    # Timing constraints
    # -----------

    def _edit_timing_constraint(self, tp_id: int) -> None:
        tp = self._timing_points.get(tp_id)
        if tp is None:
            return

        existing = self._timing_constraints.get(tp_id)
        dlg = TimingConstraintDialog(self, tp_id, existing=existing)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        c = dlg.result_constraint()
        # Treat "PASS with no times" as default (i.e. no constraint).
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
        self._timing_constraints[tp_id] = constraint

        item = self._tp_items.get(tp_id)
        if item:
            item.set_constraint_point_type(c["pointType"])
            # Re-apply visibility logic because changing STOP <-> PASS affects visibility
            # when the track is hidden.
            # We know the track ID is tp.track_id.
            is_track_visible = tp.track_id in self._visible_tp_tracks
            self._apply_track_tp_visibility(tp.track_id, is_track_visible)

        self.timingConstraintsChanged.emit(self.timing_constraints())

    def _remove_timing_constraint(self, tp_id: int) -> None:
        if tp_id not in self._timing_constraints:
            return
        
        # Capture track ID before deleting
        track_id = self._timing_constraints[tp_id]["trackId"]
        
        del self._timing_constraints[tp_id]
        item = self._tp_items.get(tp_id)
        if item:
            item.set_constraint_point_type(None)
            # Re-apply visibility
            is_track_visible = track_id in self._visible_tp_tracks
            self._apply_track_tp_visibility(track_id, is_track_visible)
            
        self.timingConstraintsChanged.emit(self.timing_constraints())

    def timing_constraints(self) -> List[dict]:
        return [self._timing_constraints[k] for k in sorted(self._timing_constraints.keys())]

    # -----------
    # Export
    # -----------

    def export_state(self) -> dict:
        return {
            "infrastructureJsonPath": self._infrastructure_json_path,
            "parameters": dict(self._parameters),
            "routeNodeIds": list(self._route_node_ids),
            "timingConstraints": self.timing_constraints(),
        }


# --------------------------
# Standalone demo
# --------------------------

if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # Adjust path as needed:
    default_json = "data_examples/ebd_v7_3_stations-infrastructure-description.json"
    # fallback for local quick test:
    if not Path(default_json).exists():
        # Try current directory
        if Path("ebd_v7_3_stations-infrastructure-description.json").exists():
            default_json = "ebd_v7_3_stations-infrastructure-description.json"

    w = InfrastructureView(json_path=default_json)
    w.resize(1200, 800)
    w.show()

    sys.exit(app.exec())
