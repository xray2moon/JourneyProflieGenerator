"""
InfrastructureView.py

PyQt6 widget that loads an EBD infrastructure JSON (nodes/tracks/timingPoints/stoppingLocations),
renders it with a QGraphicsScene, and supports:
- zoom (mouse wheel) + pan (middle mouse drag or space+left drag)
- route selection by clicking infrastructure nodes (red)
- timing constraints by clicking timing points (blue markers along tracks)

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
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QTimer, QEvent
from PyQt6.QtGui import (
    QBrush,
    QPainterPath,
    QPen,
    QTransform,
)
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTabWidget,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsEllipseItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
    QGraphicsItem,
    QDialog,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QDialogButtonBox,
    QMessageBox,
    QHBoxLayout,
    QPushButton,
    QLabel,
)


# --------------------------
# Data helpers
# --------------------------

@dataclass(frozen=True)
class Node:
    id: str
    x: float
    y: float
    numeric_id: Optional[int] = None


@dataclass(frozen=True)
class Track:
    id: str
    source: str
    target: str
    shaping_points: List[Tuple[float, float]]
    length_m: float
    numeric_id: Optional[int] = None


@dataclass(frozen=True)
class TimingPoint:
    id: int  # integer ID
    track_id: str
    target_node_id: str
    distance_to_target_m: float
    stopping_location_id: str
    segment_profile_id: int


@dataclass(frozen=True)
class StoppingLocation:
    id: str
    track_id: str
    reference_node_id: str
    distance_from_ref_m: float
    target_direction_node_id: str
    platform_id: str


# --------------------------
# Graphics items
# --------------------------

class NodeItem(QGraphicsEllipseItem):
    """
    Infrastructure nodes (switches, handover gates, etc.).
    Used for route selection.
    """
    def __init__(self, node: Node, radius: float = 6.0):
        super().__init__(-radius, -radius, 2 * radius, 2 * radius)
        self.node = node
        self.setPos(QPointF(node.x, node.y))
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsScenePositionChanges, True)

        self._default_pen = QPen(Qt.GlobalColor.black)
        self._default_pen.setWidthF(1.0)
        self._default_brush = QBrush(Qt.GlobalColor.red)
        self.setPen(self._default_pen)
        self.setBrush(self._default_brush)
        self.setZValue(10)

    def hoverEnterEvent(self, event):
        name = f"Node {self.node.numeric_id}" if self.node.numeric_id is not None else "Node"
        self.setToolTip(f"{name}\n{self.node.id}")
        super().hoverEnterEvent(event)

    def set_highlight(self, enabled: bool) -> None:
        if enabled:
            pen = QPen(Qt.GlobalColor.black)
            pen.setWidthF(2.5)
            self.setPen(pen)
        else:
            self.setPen(self._default_pen)


class TimingPointItem(QGraphicsEllipseItem):
    """
    Timing points live on tracks, not necessarily at infrastructure nodes.
    Used for timing constraints input.
    """
    def __init__(self, tp: TimingPoint, pos: QPointF, radius: float = 5.0):
        super().__init__(-radius, -radius, 2 * radius, 2 * radius)
        self.tp = tp
        self.setPos(pos)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

        self._base_pen = QPen(Qt.GlobalColor.black)
        self._base_pen.setWidthF(1.0)
        self._base_brush = QBrush(Qt.GlobalColor.blue)
        self.setPen(self._base_pen)
        self.setBrush(self._base_brush)
        self.setZValue(20)

        self._has_constraint = False

    def hoverEnterEvent(self, event):
        self.setToolTip(
            f"TimingPoint {self.tp.id}\ntrack={self.tp.track_id}\n"
            f"targetNode={self.tp.target_node_id}\ndistToTarget(m)={self.tp.distance_to_target_m:.3f}"
        )
        super().hoverEnterEvent(event)

    def set_has_constraint(self, enabled: bool) -> None:
        self._has_constraint = enabled
        pen = QPen(Qt.GlobalColor.black)
        pen.setWidthF(2.5 if enabled else 1.0)
        self.setPen(pen)


class StoppingLocationItem(QGraphicsEllipseItem):
    def __init__(self, sl_id: str, pos: QPointF, label: str, radius: float = 4.0):
        super().__init__(-radius, -radius, 2 * radius, 2 * radius)
        self.sl_id = sl_id
        self.setPos(pos)
        self.setAcceptHoverEvents(True)

        pen = QPen(Qt.GlobalColor.black)
        pen.setWidthF(1.0)
        self.setPen(pen)
        self.setBrush(QBrush(Qt.GlobalColor.darkRed))
        self.setZValue(15)

        self._label_item = QGraphicsSimpleTextItem(label)
        self._label_item.setPos(pos + QPointF(6.0, -14.0))
        self._label_item.setZValue(16)

    def label_item(self) -> QGraphicsSimpleTextItem:
        return self._label_item

    def hoverEnterEvent(self, event):
        self.setToolTip(f"StoppingLocation\n{self.sl_id}")
        super().hoverEnterEvent(event)


class TrackItem(QGraphicsPathItem):
    """
    Draws a track as a 'double line' by painting a thicker dark path and then a thinner
    white path on top (gives two rails at the edges on a white background).
    """
    def __init__(self, track_id: str, path: QPainterPath):
        super().__init__(path)
        self.track_id = track_id
        self.setZValue(1)

        self._outer_pen_default = QPen(Qt.GlobalColor.darkGray)
        self._outer_pen_default.setWidthF(6.0)
        self._outer_pen_default.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._outer_pen_default.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        self._outer_pen_visible = QPen(Qt.GlobalColor.darkBlue)
        self._outer_pen_visible.setWidthF(6.0)
        self._outer_pen_visible.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._outer_pen_visible.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        self._inner_pen = QPen(Qt.GlobalColor.white)
        self._inner_pen.setWidthF(2.0)
        self._inner_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._inner_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        # We draw outer by default; inner is drawn as a separate overlay item
        self.setPen(self._outer_pen_default)
        self.setData(0, track_id)

        self._inner_overlay = QGraphicsPathItem(path)
        self._inner_overlay.setPen(self._inner_pen)
        self._inner_overlay.setZValue(2)
        self._inner_overlay.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._inner_overlay.setData(0, track_id)

        # Route highlight overlay (optional)
        self._route_overlay = QGraphicsPathItem(path)
        pen = QPen(Qt.GlobalColor.cyan)
        pen.setWidthF(3.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self._route_overlay.setPen(pen)
        self._route_overlay.setZValue(3)
        self._route_overlay.setVisible(False)
        self._route_overlay.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._route_overlay.setData(0, track_id)

    def inner_overlay(self) -> QGraphicsPathItem:
        return self._inner_overlay

    def route_overlay(self) -> QGraphicsPathItem:
        return self._route_overlay

    def set_route_highlight(self, enabled: bool) -> None:
        self._route_overlay.setVisible(enabled)

    def set_timing_points_visible(self, enabled: bool) -> None:
        self.setPen(self._outer_pen_visible if enabled else self._outer_pen_default)


# --------------------------
# Dialog for constraints
# --------------------------

class TimingConstraintDialog(QDialog):
    """
    Minimal dialog: arrival/departure time and point type.
    Times are free-form strings (e.g., '12:34:56').
    """
    def __init__(self, parent: QWidget, tp_id: int, existing: Optional[dict] = None):
        super().__init__(parent)
        self.setWindowTitle(f"Timing constraint for TP {tp_id}")

        self._arrival = QLineEdit()
        self._departure = QLineEdit()
        self._ptype = QComboBox()
        self._ptype.addItems(["STOP", "PASS"])

        if existing:
            self._arrival.setText(existing.get("arrivalTime", ""))
            self._departure.setText(existing.get("departureTime", ""))
            self._ptype.setCurrentText(existing.get("pointType", "STOP"))

        form = QFormLayout()
        form.addRow("Point type", self._ptype)
        form.addRow("Arrival time", self._arrival)
        form.addRow("Departure time", self._departure)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

        self._initial_fit_done = False

    def result_constraint(self) -> dict:
        return {
            "pointType": self._ptype.currentText(),
            "arrivalTime": self._arrival.text().strip(),
            "departureTime": self._departure.text().strip(),
        }


# --------------------------
# Graphics view with pan/zoom
# --------------------------


class PanZoomGraphicsView(QGraphicsView):
    """QGraphicsView with mouse-wheel zoom and two pan modes:
    - Middle mouse button drag
    - Hold Space and drag with left mouse (hand tool)
    - Left mouse drag on empty background
    """

    def __init__(self, scene: QGraphicsScene, parent: Optional[QWidget] = None):
        super().__init__(scene, parent)

        # Professional look
        self.setBackgroundBrush(QBrush(Qt.GlobalColor.white))

        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

        # Nicer zoom behavior
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        # Middle-button panning state
        self._panning_middle = False
        self._panning_left_background = False
        self._last_mouse_pos = None

        # Space-to-pan state (Space is NOT a Qt "modifier", we track it ourselves)
        self._space_pressed = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        angle = event.angleDelta().y()
        if angle == 0:
            return
        factor = 1.0015 ** angle
        self.scale(factor, factor)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not self._space_pressed:
            self._space_pressed = True
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and self._space_pressed:
            self._space_pressed = False
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning_middle = True
            self._last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self._space_pressed
            and self.itemAt(event.pos()) is None
        ):
            self._panning_left_background = True
            self._last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._panning_middle or self._panning_left_background) and self._last_mouse_pos is not None:
            delta = event.pos() - self._last_mouse_pos
            self._last_mouse_pos = event.pos()
            self.translate(-delta.x(), -delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning_middle and event.button() == Qt.MouseButton.MiddleButton:
            self._panning_middle = False
            self._last_mouse_pos = None
            # If space is currently held, go back to open hand; otherwise arrow.
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._space_pressed else Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if self._panning_left_background and event.button() == Qt.MouseButton.LeftButton:
            self._panning_left_background = False
            self._last_mouse_pos = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

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

        # Small toolbar area (optional but useful)
        self._clear_route_btn = QPushButton("Clear route")
        self._clear_route_btn.clicked.connect(self.clear_route)
        self._layout_combo = QComboBox()
        self._layout_combo.addItems(["Geographic", "Topological"])
        self._layout_combo.currentTextChanged.connect(self._on_layout_mode_changed)
        layout_label = QLabel("Layout:")
        layout_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._clear_route_btn)
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
        self._tabs.addTab(QWidget(), "Parameter view")
        self._tabs.addTab(QWidget(), "confirm")

        layout = QVBoxLayout(self)
        layout.addWidget(self._tabs)
        self.setLayout(layout)

        self._initial_fit_done = False
        self._layout_mode = "geographic"
        self._node_positions: Dict[str, QPointF] = {}
        # Topological rendering helpers (populated on demand / rebuild)
        self._topo_node_index: Dict[str, int] = {}
        self._topo_track_offset_y: Dict[str, float] = {}
        self._track_render_paths: Dict[str, QPainterPath] = {}
        self._track_render_polylines: Dict[str, List[QPointF]] = {}
        self._topo_station_layout: List[Tuple[str, float, float, int]] = []  # (stationName, x0, x1, component)
        self._node_to_station: Dict[str, str] = {}  # nodeId -> stationName
        self._station_rep_node_id: Dict[str, str] = {}  # stationName -> nodeId (for routing)
        self._station_rect_items: Dict[str, QGraphicsRectItem] = {}
        self._topo_route_item: Optional[QGraphicsPathItem] = None

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
        # timingPointId -> constraint dict
        self._timing_constraints: Dict[int, dict] = {}

        # Scene interaction
        self._scene.selectionChanged.connect(self._on_selection_changed)

        if json_path:
            self.load_infrastructure(json_path)

    def _on_layout_mode_changed(self, mode_text: str) -> None:
        mode = "topological" if mode_text.lower().startswith("topo") else "geographic"
        if mode == self._layout_mode:
            return
        self._layout_mode = mode
        self._rebuild_scene()
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
        self._node_positions = self._compute_node_positions()
        self._track_render_paths.clear()
        self._track_render_polylines.clear()
        self._topo_track_offset_y = {}

        if self._layout_mode == "topological":
            self._add_topological_station_markers()
            self._add_topological_skeleton_edges()

            # Route overlay (station-to-station) for topo mode
            self._topo_route_item = QGraphicsPathItem()
            pen = QPen(Qt.GlobalColor.cyan)
            pen.setWidthF(6.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            self._topo_route_item.setPen(pen)
            self._topo_route_item.setZValue(40)
            self._topo_route_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._scene.addItem(self._topo_route_item)

            # Hook mouse events by installing a scene event filter
            self._scene.installEventFilter(self)
            self._update_route_highlights()
            return

        self._topo_route_item = None

        # Tracks first
        for tr in self._tracks.values():
            path = self._track_to_path(tr)
            if path is None:
                continue
            item = TrackItem(tr.id, path)
            item.set_timing_points_visible(tr.id in self._visible_tp_tracks)
            self._scene.addItem(item)
            self._scene.addItem(item.inner_overlay())
            self._scene.addItem(item.route_overlay())
            self._track_items[tr.id] = item
            self._tp_track_map.setdefault(tr.id, [])

        # Nodes
        for node in self._nodes.values():
            pos = self._node_positions.get(node.id, QPointF(node.x, node.y))
            ni = NodeItem(node)
            ni.setPos(pos)
            self._scene.addItem(ni)
            self._node_items[node.id] = ni

        # Timing points (blue)
        for tp in self._timing_points.values():
            pos = self._timing_point_position(tp)
            if pos is None:
                continue
            tpi = TimingPointItem(tp, pos)
            tpi.setVisible(tp.track_id in self._visible_tp_tracks)
            self._scene.addItem(tpi)
            self._tp_items[tp.id] = tpi
            self._tp_track_map.setdefault(tp.track_id, []).append(tpi)

        # Stopping locations + labels
        # In topological mode, station/group markers are rendered instead (see _add_topological_station_markers()).
        if self._layout_mode != "topological":
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
                self._scene.addItem(sli)
                self._scene.addItem(sli.label_item())
                self._sl_items[sl.id] = sli

        # Hook mouse events by installing a scene event filter
        # (We route clicks based on item types.)
        self._scene.installEventFilter(self)

        self._restore_timing_point_markers()
        self._update_route_highlights()

    def _path_from_points(self, pts: List[QPointF]) -> QPainterPath:
        path = QPainterPath(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        return path

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
                rect.setData(2, "station")
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
                path = QPainterPath(QPointF(a, 0.0))
                path.lineTo(QPointF(b, 0.0))
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

        rect = self._scene.itemsBoundingRect()
        if rect.isNull():
            return

        pad = max(rect.width(), rect.height()) * 0.02  # 2%
        pad = max(pad, 20.0)
        rect = rect.adjusted(-pad, -pad, pad, pad)

        self._view.resetTransform()
        self._view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._initial_fit_done = True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Do the initial fit once, when the widget first gets a meaningful size.
        if not getattr(self, "_initial_fit_done", False):
            QTimer.singleShot(0, self._fit_to_scene)

    # -----------
    # Interaction / event filter
    # -----------

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
        if track_id not in self._tp_track_map:
            return
        visible = track_id not in self._visible_tp_tracks
        if visible:
            self._visible_tp_tracks.add(track_id)
        else:
            self._visible_tp_tracks.discard(track_id)
        self._apply_track_tp_visibility(track_id, visible)

    def _apply_track_tp_visibility(self, track_id: str, visible: bool) -> None:
        for tpi in self._tp_track_map.get(track_id, []):
            tpi.setVisible(visible)
            if not visible:
                tpi.setSelected(False)
        track_item = self._track_items.get(track_id)
        if track_item:
            track_item.set_timing_points_visible(visible)

    def eventFilter(self, obj, event):
        if obj is self._scene:
            if event.type() == QEvent.Type.GraphicsSceneMousePress:
                if self._layout_mode == "topological":
                    if event.button() == Qt.MouseButton.LeftButton:
                        for cand in self._scene.items(event.scenePos()):
                            if cand.data(2) != "station":
                                continue
                            rep = cand.data(1)
                            if isinstance(rep, str):
                                self._extend_route_with_node(rep)
                                return True
                    return super().eventFilter(obj, event)

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
                        self._extend_route_with_node(item.node.id)
                        return True

                if event.button() == Qt.MouseButton.LeftButton:
                    track_id = self._pick_track_id_near(event.scenePos())
                else:
                    track_id = None

                if track_id and event.button() == Qt.MouseButton.LeftButton:
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
        self._update_route_highlights()
        self.routeChanged.emit(list(self._route_node_ids))

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
        if self._layout_mode == "topological":
            self._update_topological_route_overlay()
            return

        route_nodes = set(self._route_node_ids)
        route_tracks = set(self._route_track_ids)

        for nid, item in self._node_items.items():
            item.set_highlight(nid in route_nodes)

        for tid, item in self._track_items.items():
            item.set_route_highlight(tid in route_tracks)

    def _update_topological_route_overlay(self) -> None:
        if self._topo_route_item is None:
            return

        default_pen = QPen(Qt.GlobalColor.lightGray)
        default_pen.setWidthF(1.0)
        default_pen.setStyle(Qt.PenStyle.DashLine)
        highlight_pen = QPen(Qt.GlobalColor.darkCyan)
        highlight_pen.setWidthF(2.0)
        highlight_pen.setStyle(Qt.PenStyle.SolidLine)

        for rect in self._station_rect_items.values():
            rect.setPen(default_pen)

        if len(self._route_node_ids) < 2:
            self._topo_route_item.setPath(QPainterPath())
            return

        centers = {name: (x0 + x1) / 2.0 for (name, x0, x1, _) in self._topo_station_layout}

        route_stations: List[str] = []
        for nid in self._route_node_ids:
            s = self._node_to_station.get(nid)
            if not s:
                continue
            if not route_stations or route_stations[-1] != s:
                route_stations.append(s)

        pts = [QPointF(centers[s], 0.0) for s in route_stations if s in centers]
        if len(pts) < 2:
            self._topo_route_item.setPath(QPainterPath())
            return

        for s in route_stations:
            rect = self._station_rect_items.get(s)
            if rect:
                rect.setPen(highlight_pen)

        path = QPainterPath(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        self._topo_route_item.setPath(path)

    def _restore_timing_point_markers(self) -> None:
        for tp_id in self._timing_constraints.keys():
            item = self._tp_items.get(tp_id)
            if item:
                item.set_has_constraint(True)

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
            item.set_has_constraint(True)

        self.timingConstraintsChanged.emit(self.timing_constraints())

    def _remove_timing_constraint(self, tp_id: int) -> None:
        if tp_id not in self._timing_constraints:
            return
        del self._timing_constraints[tp_id]
        item = self._tp_items.get(tp_id)
        if item:
            item.set_has_constraint(False)
        self.timingConstraintsChanged.emit(self.timing_constraints())

    def timing_constraints(self) -> List[dict]:
        return [self._timing_constraints[k] for k in sorted(self._timing_constraints.keys())]

    # -----------
    # Export
    # -----------

    def export_state(self) -> dict:
        return {
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
