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
    QAction,
)
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTabWidget,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsEllipseItem,
    QGraphicsPathItem,
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

        self._outer_pen = QPen(Qt.GlobalColor.darkGray)
        self._outer_pen.setWidthF(6.0)
        self._outer_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._outer_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        self._inner_pen = QPen(Qt.GlobalColor.white)
        self._inner_pen.setWidthF(2.0)
        self._inner_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._inner_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        # We draw outer by default; inner is drawn as a separate overlay item
        self.setPen(self._outer_pen)

        self._inner_overlay = QGraphicsPathItem(path)
        self._inner_overlay.setPen(self._inner_pen)
        self._inner_overlay.setZValue(2)

        # Route highlight overlay (optional)
        self._route_overlay = QGraphicsPathItem(path)
        pen = QPen(Qt.GlobalColor.cyan)
        pen.setWidthF(3.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self._route_overlay.setPen(pen)
        self._route_overlay.setZValue(3)
        self._route_overlay.setVisible(False)

    def inner_overlay(self) -> QGraphicsPathItem:
        return self._inner_overlay

    def route_overlay(self) -> QGraphicsPathItem:
        return self._route_overlay

    def set_route_highlight(self, enabled: bool) -> None:
        self._route_overlay.setVisible(enabled)


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
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning_middle and self._last_mouse_pos is not None:
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
        toolbar = QHBoxLayout()
        toolbar.addWidget(self._clear_route_btn)
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
        self._initial_fit_done = False
        QTimer.singleShot(0, self._fit_to_scene)

    def _parse_raw(self, raw: dict) -> None:
        self._nodes.clear()
        self._tracks.clear()
        self._timing_points.clear()
        self._stopping_locations.clear()
        self._sl_to_group.clear()

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

        # Tracks first
        for tr in self._tracks.values():
            path = self._track_to_path(tr)
            if path is None:
                continue
            item = TrackItem(tr.id, path)
            self._scene.addItem(item)
            self._scene.addItem(item.inner_overlay())
            self._scene.addItem(item.route_overlay())
            self._track_items[tr.id] = item

        # Nodes
        for node in self._nodes.values():
            ni = NodeItem(node)
            self._scene.addItem(ni)
            self._node_items[node.id] = ni

        # Timing points (blue)
        for tp in self._timing_points.values():
            pos = self._timing_point_position(tp)
            if pos is None:
                continue
            tpi = TimingPointItem(tp, pos)
            self._scene.addItem(tpi)
            self._tp_items[tp.id] = tpi

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
            self._scene.addItem(sli)
            self._scene.addItem(sli.label_item())
            self._sl_items[sl.id] = sli

        # Hook mouse events by installing a scene event filter
        # (We route clicks based on item types.)
        self._scene.installEventFilter(self)

        # Reset state
        self.clear_route()

    def _track_to_path(self, tr: Track) -> Optional[QPainterPath]:
        if tr.source not in self._nodes or tr.target not in self._nodes:
            return None
        pts = [QPointF(self._nodes[tr.source].x, self._nodes[tr.source].y)]
        pts += [QPointF(x, y) for (x, y) in tr.shaping_points]
        pts += [QPointF(self._nodes[tr.target].x, self._nodes[tr.target].y)]

        path = QPainterPath(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        return path

    def _polyline_points_for_track(self, tr: Track) -> Optional[List[QPointF]]:
        if tr.source not in self._nodes or tr.target not in self._nodes:
            return None
        pts = [QPointF(self._nodes[tr.source].x, self._nodes[tr.source].y)]
        pts += [QPointF(x, y) for (x, y) in tr.shaping_points]
        pts += [QPointF(self._nodes[tr.target].x, self._nodes[tr.target].y)]
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

    def eventFilter(self, obj, event):
        if obj is self._scene:
            if event.type() == QEvent.Type.GraphicsSceneMousePress:
                item = self._scene.itemAt(event.scenePos(), QTransform())

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
        route_nodes = set(self._route_node_ids)
        route_tracks = set(self._route_track_ids)

        for nid, item in self._node_items.items():
            item.set_highlight(nid in route_nodes)

        for tid, item in self._track_items.items():
            item.set_route_highlight(tid in route_tracks)

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
