from __future__ import annotations

import math
from typing import List, Optional, Sequence, Set, Tuple

from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QBrush, QColor, QPainterPath, QPen, QTransform
from PyQt6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsSimpleTextItem,
)

from Source.infra_models import Node, TimingPoint
from Source.modern_theme import ModernColors


class NodeItem(QGraphicsEllipseItem):
    """
    Infrastructure nodes (switches, handover gates, etc.).
    Used for route selection.
    """

    def __init__(
        self,
        node: Node,
        *,
        radius: float = 6.0,
        brush: str = ModernColors.NODE_DEFAULT,
    ):
        super().__init__(-radius, -radius, 2 * radius, 2 * radius)
        self.node = node
        self.setPos(QPointF(node.x, node.y))
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsScenePositionChanges, True)

        self._default_pen = QPen(QColor(ModernColors.L_TEXT))
        self._default_pen.setWidthF(1.0)
        self._default_brush = QBrush(QColor(brush))
        self._route_selected = False
        self._route_role: Optional[str] = None
        self._route_pen = QPen(QColor(ModernColors.L_TEXT))
        self._route_pen.setWidthF(2.5)
        self._start_pen = QPen(QColor(ModernColors.NODE_START))
        self._start_pen.setWidthF(3.0)
        self._end_pen = QPen(QColor(ModernColors.NODE_END))
        self._end_pen.setWidthF(3.0)
        self.setPen(self._default_pen)
        self.setBrush(self._default_brush)
        self.setZValue(10)

    def hoverEnterEvent(self, event):
        name = f"Node {self.node.numeric_id}" if self.node.numeric_id is not None else "Node"
        self.setToolTip(f"{name}\n{self.node.id}")
        super().hoverEnterEvent(event)

    def set_highlight(self, enabled: bool) -> None:
        self._route_selected = bool(enabled)
        self._apply_route_style()

    def set_route_role(self, role: Optional[str]) -> None:
        if role not in {None, "start", "end"}:
            role = None
        self._route_role = role
        self._apply_route_style()

    def set_theme(self, theme: str) -> None:
        if theme == "dark":
            self._default_pen.setColor(QColor(ModernColors.D_TEXT))
        else:
            self._default_pen.setColor(QColor(ModernColors.L_TEXT))
        self._default_pen.setWidthF(1.0)
        self._apply_route_style()

    def _apply_route_style(self) -> None:
        if self._route_role == "start":
            self.setPen(self._start_pen)
        elif self._route_role == "end":
            self.setPen(self._end_pen)
        elif self._route_selected:
            self.setPen(self._route_pen)
        else:
            self.setPen(self._default_pen)


class TimingPointItem(QGraphicsEllipseItem):
    """
    Timing points live on tracks, not necessarily at infrastructure nodes.
    Used for timing constraints input.
    """

    def __init__(
        self,
        tp: TimingPoint,
        pos: QPointF,
        radius: float = 5.0,
        variants: Optional[Sequence[TimingPoint]] = None,
        track_source_node_id: str = "",
        track_target_node_id: str = "",
        track_length_m: float = 0.0,
    ):
        super().__init__(-radius, -radius, 2 * radius, 2 * radius)
        ordered_variants = sorted(
            list(variants) if variants else [tp],
            key=lambda t: int(t.id),
        )
        self.tp = ordered_variants[0]
        self._variants: Tuple[TimingPoint, ...] = tuple(ordered_variants)
        self._tp_id_set = {int(v.id) for v in self._variants}
        self._track_source_node_id = track_source_node_id
        self._track_target_node_id = track_target_node_id
        self._track_length_m = float(track_length_m or 0.0)
        self.setPos(pos)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

        self._base_pen = QPen(QColor(ModernColors.L_TEXT))
        self._base_pen.setWidthF(1.0)
        self._base_brush = QBrush(QColor(ModernColors.TP_DEFAULT))
        
        self._route_selected = False
        self._route_role: Optional[str] = None
        self._route_pen = QPen(QColor(ModernColors.L_TEXT))
        self._route_pen.setWidthF(2.5)
        self._start_pen = QPen(QColor(ModernColors.NODE_START))
        self._start_pen.setWidthF(3.0)
        self._end_pen = QPen(QColor(ModernColors.NODE_END))
        self._end_pen.setWidthF(3.0)
        
        self.setPen(self._base_pen)
        self.setBrush(self._base_brush)
        self.setZValue(20)

        self._has_constraint = False
        self._point_type: Optional[str] = None

    def tp_ids(self) -> Tuple[int, ...]:
        return tuple(int(tp.id) for tp in self._variants)

    def tp_variants(self) -> Tuple[TimingPoint, ...]:
        return self._variants

    def contains_tp_id(self, tp_id: int) -> bool:
        return int(tp_id) in self._tp_id_set

    def _tooltip_text(self) -> str:
        lines = [
            "{",
            '  "track": {',
            f'    "id": "{self.tp.track_id}",',
            f'    "sourceNodeId": "{self._track_source_node_id}",',
            f'    "targetNodeId": "{self._track_target_node_id}",',
            f'    "lengthMeter": {float(self._track_length_m):.3f}',
            "  },",
            '  "timingPoints": [',
        ]

        for idx, var in enumerate(self._variants):
            comma = "," if idx < len(self._variants) - 1 else ""
            stopping_location_id = str(var.stopping_location_id or "")
            lines.extend(
                [
                    "    {",
                    f'      "id": {int(var.id)},',
                    f'      "trackId": "{var.track_id}",',
                    f'      "targetNodeId": "{var.target_node_id}",',
                    f'      "distanceToTargetNodeInMeters": {float(var.distance_to_target_m):.3f},',
                    f'      "stoppingLocationId": "{stopping_location_id}",',
                    f'      "segmentProfileId": {int(var.segment_profile_id)}',
                    f"    }}{comma}",
                ]
            )

        lines.extend(
            [
                "  ]",
                "}",
            ]
        )
        return "\n".join(lines)

    def hoverEnterEvent(self, event):
        self.setToolTip(self._tooltip_text())
        super().hoverEnterEvent(event)

    def set_highlight(self, enabled: bool) -> None:
        self._route_selected = bool(enabled)
        self._apply_route_style()

    def set_route_role(self, role: Optional[str]) -> None:
        if role not in {None, "start", "end"}:
            role = None
        self._route_role = role
        self._apply_route_style()

    def _apply_route_style(self) -> None:
        if self._route_role == "start":
            self.setPen(self._start_pen)
        elif self._route_role == "end":
            self.setPen(self._end_pen)
        elif self._route_selected:
            self.setPen(self._route_pen)
        else:
            pen = QPen(self._base_pen)
            if self._point_type == "STOP":
                pen.setColor(Qt.GlobalColor.black)
                pen.setWidthF(2.5)
            self.setPen(pen)

    def set_constraint_point_type(self, point_type: Optional[str]) -> None:
        self._point_type = point_type
        self._has_constraint = point_type is not None
        self._apply_route_style()

    def set_theme(self, theme: str) -> None:
        if theme == "dark":
            self._base_pen.setColor(QColor(ModernColors.D_TEXT))
        else:
            self._base_pen.setColor(QColor(ModernColors.L_TEXT))
        self._base_pen.setWidthF(1.0)
        self._apply_route_style()


class StoppingLocationItem(QGraphicsEllipseItem):
    def __init__(self, sl_id: str, pos: QPointF, label: str, radius: float = 4.0):
        super().__init__(-radius, -radius, 2 * radius, 2 * radius)
        self.sl_id = sl_id
        self.setPos(pos)
        self.setAcceptHoverEvents(True)

        self._route_selected = False
        self._route_role: Optional[str] = None

        self._default_pen = QPen(Qt.GlobalColor.black)
        self._default_pen.setWidthF(1.0)
        self._route_pen = QPen(QColor(ModernColors.L_TEXT))
        self._route_pen.setWidthF(2.5)
        self._end_pen = QPen(QColor(ModernColors.NODE_END))
        self._end_pen.setWidthF(3.0)

        self.setPen(self._default_pen)
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

    def set_highlight(self, enabled: bool) -> None:
        self._route_selected = bool(enabled)
        self._apply_route_style()

    def set_route_role(self, role: Optional[str]) -> None:
        self._route_role = role
        self._apply_route_style()

    def _apply_route_style(self) -> None:
        if self._route_role == "end":
            self.setPen(self._end_pen)
        elif self._route_selected:
            self.setPen(self._route_pen)
        else:
            self.setPen(self._default_pen)

    def set_theme(self, theme: str) -> None:
        if theme == "dark":
            self._default_pen.setColor(QColor(ModernColors.D_TEXT))
            self._route_pen.setColor(QColor(ModernColors.D_TEXT))
            self._label_item.setBrush(QBrush(QColor(ModernColors.D_TEXT)))
        else:
            self._default_pen.setColor(QColor(ModernColors.L_TEXT)) # Or black? Existing was black. L_TEXT is usually dark gray/black.
            self._route_pen.setColor(QColor(ModernColors.L_TEXT))
            self._label_item.setBrush(QBrush(QColor(ModernColors.L_TEXT)))
        
        # Restore width 1.0 for default from set_theme logic if needed, or just rely on _default_pen config
        self._default_pen.setWidthF(1.0)
        self._apply_route_style()


class TrackItem(QGraphicsPathItem):
    """
    Draws a track as a 'double line' by painting a thicker dark path and then a thinner
    white path on top (gives two rails at the edges on a white background).
    """

    _ARROW_TARGET_SPACING = 120.0
    _ARROW_EDGE_PADDING = 14.0
    _ARROW_ENDPOINT_CLEARANCE = 26.0
    _ARROW_HALF_LENGTH = 5.0
    _MAX_ARROWS_PER_TRAVERSAL = 40

    def __init__(self, track_id: str, path: QPainterPath):
        super().__init__(path)
        self.track_id = track_id
        self.setZValue(1)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._hovered = False
        self._timing_points_visible = False

        self._outer_pen_default = QPen(QColor(ModernColors.TRACK_DEFAULT_L))
        self._outer_pen_default.setWidthF(4.0)
        self._outer_pen_default.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._outer_pen_default.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        self._outer_pen_visible = QPen(QColor(ModernColors.TRACK_TP_VISIBLE))
        self._outer_pen_visible.setWidthF(4.0)
        self._outer_pen_visible.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._outer_pen_visible.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        self._outer_pen_hover = QPen(QColor(ModernColors.TRACK_HOVER))
        self._outer_pen_hover.setWidthF(5.0)
        self._outer_pen_hover.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._outer_pen_hover.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        self._inner_pen = QPen(QColor(ModernColors.L_SURFACE))
        self._inner_pen.setWidthF(1.5)
        self._inner_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._inner_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        # We draw outer by default; inner is drawn as a separate overlay item
        self._update_outer_pen()
        self.setData(0, track_id)

        self._inner_overlay = QGraphicsPathItem(path)
        self._inner_overlay.setPen(self._inner_pen)
        self._inner_overlay.setZValue(2)
        self._inner_overlay.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._inner_overlay.setData(0, track_id)

        # Route highlight overlay (optional)
        self._route_overlay = QGraphicsPathItem(path)
        pen = QPen(QColor(ModernColors.TRACK_ROUTE))
        pen.setWidthF(2.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self._route_overlay.setPen(pen)
        self._route_overlay.setZValue(3)
        self._route_overlay.setVisible(False)
        self._route_overlay.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._route_overlay.setData(0, track_id)

        # Direction arrows
        self._arrows: List[QGraphicsPathItem] = []

    def inner_overlay(self) -> QGraphicsPathItem:
        return self._inner_overlay

    def route_overlay(self) -> QGraphicsPathItem:
        return self._route_overlay

    def set_route_highlight(
        self, 
        enabled: bool, 
        is_double: bool = False, 
        directions: Optional[Set[str]] = None,
        traversals: Optional[List[str]] = None,
        traversal_offsets: Optional[List[Tuple[float, float]]] = None,
        traversal_ranges: Optional[List[Tuple[float, float]]] = None
    ) -> None:
        """
        Highlight the track if it is part of the current route.
        If traversed multiple times, draw separate offset lines.
        traversal_offsets: List of (start_offset, end_offset) for each traversal.
        traversal_ranges: List of (start_pct, end_pct) for each traversal (0.0 to 1.0).
        """
        self._route_overlay.setVisible(enabled)
        
        # Remove old arrows
        for arrow in self._arrows:
            if arrow.scene():
                arrow.scene().removeItem(arrow)
        self._arrows.clear()

        if not enabled:
            return

        # If we have explicit traversals, use them; otherwise fallback to directions set
        if traversals is None:
            if directions:
                traversals = sorted(list(directions)) # stable order
            else:
                traversals = ["forward"] if not is_double else ["forward", "backward"]

        num = len(traversals)
        color = QColor("purple") if num > 1 else QColor(ModernColors.TRACK_ROUTE)
        
        pen = self._route_overlay.pen()
        pen.setColor(color)
        self._route_overlay.setPen(pen)

        # Build a composite path directly on top of the track centerline.
        path = self.path()
        pts: List[QPointF] = []
        for i in range(path.elementCount()):
            el = path.elementAt(i)
            pts.append(QPointF(el.x, el.y))
        composite_path = QPainterPath()

        spacing = 7.0

        # Count occurrences to handle multiple traversals of same direction.
        fwd_count = traversals.count("forward")
        bwd_count = traversals.count("backward")
        fwd_idx = 0
        bwd_idx = 0

        for i, direction in enumerate(traversals):
            rng = traversal_ranges[i] if (traversal_ranges and i < len(traversal_ranges)) else (0.0, 1.0)

            # Keep single-traversal tracks on centerline. For multi-traversal tracks,
            # apply side shifts so overlapping passes stay visually separated.
            if num <= 1:
                route_path = self._create_partial_path(path, range_pct=rng)
            else:
                if traversal_offsets and i < len(traversal_offsets):
                    s_off, e_off = traversal_offsets[i]
                    if direction == "backward":
                        s_off, e_off = e_off, s_off
                else:
                    if direction == "forward":
                        if fwd_count == 1:
                            s_off = e_off = spacing / 2.0
                        else:
                            s_off = e_off = spacing / 2.0 + (fwd_idx - (fwd_count - 1) / 2.0) * (spacing / 2.0)
                        fwd_idx += 1
                    else:
                        if bwd_count == 1:
                            s_off = e_off = -spacing / 2.0
                        else:
                            s_off = e_off = -spacing / 2.0 + (bwd_idx - (bwd_count - 1) / 2.0) * (spacing / 2.0)
                        bwd_idx += 1

                route_path = self._create_offset_path(pts, s_off, e_off, range_pct=rng)
            composite_path.addPath(route_path)
            
            # Arrows for this specific line
            l = route_path.length()
            if l > 1e-3:
                arrow_distances = self._arrow_distances_for_length(l)
                for dist in arrow_distances:
                    if hasattr(route_path, "percentAtLength"):
                        t = route_path.percentAtLength(dist)
                    else:
                        t = dist / l
                    t = min(1.0, max(0.0, t))
                    pos = route_path.pointAtPercent(t)
                    tangent = self._tangent_vector_at_distance(route_path, dist, l)
                    self._create_arrow(pos, tangent, color)

        self._route_overlay.setPath(composite_path)

    def _create_partial_path(self, base_path: QPainterPath, range_pct: Tuple[float, float] = (0.0, 1.0)) -> QPainterPath:
        total_len = base_path.length()
        if total_len <= 1e-6:
            return QPainterPath()

        s_pct, e_pct = range_pct
        s_pct = min(1.0, max(0.0, s_pct))
        e_pct = min(1.0, max(0.0, e_pct))

        if abs(s_pct - e_pct) <= 1e-6:
            # Tiny visible mark at the selected point.
            if hasattr(base_path, "percentAtLength"):
                t = base_path.percentAtLength(s_pct * total_len)
            else:
                t = s_pct
            p = base_path.pointAtPercent(min(1.0, max(0.0, t)))
            res = QPainterPath(p)
            res.lineTo(p + QPointF(1e-3, 0.0))
            return res

        s_dist = s_pct * total_len
        e_dist = e_pct * total_len

        steps = max(8, int(abs(e_dist - s_dist) / 10.0))
        res = QPainterPath()
        first = True
        for step in range(steps + 1):
            d = s_dist + (e_dist - s_dist) * (step / steps)
            if hasattr(base_path, "percentAtLength"):
                t = base_path.percentAtLength(d)
            else:
                t = d / total_len
            pt = base_path.pointAtPercent(min(1.0, max(0.0, t)))
            if first:
                res.moveTo(pt)
                first = False
            else:
                res.lineTo(pt)
        return res

    def _arrow_distances_for_length(self, length: float) -> List[float]:
        if length <= 1e-6:
            return []

        # Keep arrows inside the segment, but adapt on short segments so at least
        # one arrow is still shown near the middle.
        target_padding = max(self._ARROW_EDGE_PADDING, self._ARROW_ENDPOINT_CLEARANCE)
        max_padding_that_still_fits = max(0.0, length * 0.45 - self._ARROW_HALF_LENGTH)
        edge_padding = min(target_padding, max_padding_that_still_fits)

        usable_len = max(0.0, length - 2.0 * edge_padding)
        if usable_len <= (2.0 * self._ARROW_HALF_LENGTH + 1.0):
            return [length * 0.5]
        if usable_len <= self._ARROW_TARGET_SPACING * 0.8:
            return [edge_padding + usable_len * 0.5]

        arrow_count = int(round(usable_len / self._ARROW_TARGET_SPACING)) + 1
        arrow_count = max(2, min(arrow_count, self._MAX_ARROWS_PER_TRAVERSAL))
        spacing = usable_len / max(1, arrow_count - 1)

        distances: List[float] = []
        for i in range(arrow_count):
            dist = edge_padding + i * spacing
            distances.append(min(length - edge_padding, max(edge_padding, dist)))
        return distances

    def _tangent_vector_at_distance(self, path: QPainterPath, dist: float, total_len: float) -> QPointF:
        if total_len <= 1e-6:
            return QPointF(1.0, 0.0)
        eps = min(10.0, max(2.0, total_len * 0.02))
        d0 = min(total_len, max(0.0, dist))
        if d0 + eps <= total_len:
            d1, d2 = d0, d0 + eps
        elif d0 - eps >= 0.0:
            d1, d2 = d0 - eps, d0
        else:
            d1, d2 = 0.0, total_len

        if hasattr(path, "percentAtLength"):
            t1 = path.percentAtLength(d1)
            t2 = path.percentAtLength(d2)
        else:
            t1 = d1 / total_len
            t2 = d2 / total_len

        p1 = path.pointAtPercent(min(1.0, max(0.0, t1)))
        p2 = path.pointAtPercent(min(1.0, max(0.0, t2)))
        return p2 - p1

    def _create_offset_path(self, pts: List[QPointF], start_offset: float, end_offset: float, range_pct: Tuple[float, float] = (0.0, 1.0)) -> QPainterPath:
        if not pts:
            return QPainterPath()
        
        # Subdivide segments to allow for a smooth transition curve
        refined_pts = [pts[0]]
        max_step = 5.0 
        for i in range(len(pts) - 1):
            p1, p2 = pts[i], pts[i+1]
            dist = math.hypot(p2.x() - p1.x(), p2.y() - p1.y())
            if dist > max_step:
                steps = int(dist / max_step)
                for s in range(1, steps):
                    refined_pts.append(p1 + (p2 - p1) * (s / steps))
            refined_pts.append(p2)
        pts = refined_pts

        if len(pts) < 2:
            p = QPainterPath(pts[0])
            for pt in pts[1:]:
                p.lineTo(pt)
            return p

        # Calculate total length for interpolation
        total_len = 0.0
        segment_lengths = []
        for i in range(len(pts) - 1):
            seg_l = math.hypot(pts[i+1].x() - pts[i].x(), pts[i+1].y() - pts[i].y())
            segment_lengths.append(seg_l)
            total_len += seg_l

        new_pts = []
        curr_len = 0.0
        s_pct, e_pct = range_pct
        for i in range(len(pts)):
            p = curr_len / total_len if total_len > 1e-6 else 0.0
            
            # Check if this point is within the range
            if p < s_pct - 1e-6 or p > e_pct + 1e-6:
                # We need to handle points at the boundary to avoid gaps
                # But for now let's just collect all and trim the path later if needed,
                # or just use pointAtPercent on the final path.
                # Actually, better to interpolate here.
                pass

            # Interpolate offset
            if total_len > 1e-6:
                # Cubic interpolation for a "branching" look
                if start_offset == 0 and end_offset != 0:
                    t = p * p * p # Branches out late
                elif start_offset != 0 and end_offset == 0:
                    t = 1.0 - (1.0 - p)**3 # Branches in early
                else:
                    # Smoothstep for non-zero to non-zero
                    t = p * p * (3 - 2 * p)
                offset = start_offset + (end_offset - start_offset) * t
            else:
                offset = start_offset

            if i == 0:
                v = pts[1] - pts[0]
                mag = math.hypot(v.x(), v.y())
                n = QPointF(-v.y() / mag, v.x() / mag) if mag > 1e-6 else QPointF(0, 0)
            elif i == len(pts) - 1:
                v = pts[i] - pts[i-1]
                mag = math.hypot(v.x(), v.y())
                n = QPointF(-v.y() / mag, v.x() / mag) if mag > 1e-6 else QPointF(0, 0)
            else:
                v1 = pts[i] - pts[i-1]
                v2 = pts[i+1] - pts[i]
                mag1 = math.hypot(v1.x(), v1.y())
                mag2 = math.hypot(v2.x(), v2.y())
                if mag1 > 1e-6 and mag2 > 1e-6:
                    n1 = QPointF(-v1.y() / mag1, v1.x() / mag1)
                    n2 = QPointF(-v2.y() / mag2, v2.x() / mag2)
                    n = n1 + n2
                    mag = math.hypot(n.x(), n.y())
                    if mag > 1e-6:
                        n /= mag
                        cos_half_theta = n.x() * n1.x() + n.y() * n1.y()
                        # Clamp miter expansion at sharp bends to avoid local spikes/loops.
                        if cos_half_theta > 1e-3:
                            miter_scale = min(1.8, max(1.0, 1.0 / cos_half_theta))
                            n *= miter_scale
                else:
                    n = QPointF(0, 0)
            
            new_pts.append(pts[i] + n * offset)
            if i < len(segment_lengths):
                curr_len += segment_lengths[i]

        res_full = QPainterPath(new_pts[0])
        for pt in new_pts[1:]:
            res_full.lineTo(pt)

        if s_pct == 0.0 and e_pct == 1.0:
            return res_full

        # Create a partial path by clipping offset points using original-
        # track fractions.  Using percentAtLength on the offset path would
        # drift because its total length differs from the original track.
        if total_len < 1e-6:
            return QPainterPath()

        lo = min(s_pct, e_pct)
        hi = max(s_pct, e_pct)
        backward = s_pct > e_pct

        # Recompute original fractions for each refined point.
        cum = 0.0
        prev_f = 0.0
        clipped: List[QPointF] = []
        for i in range(len(new_pts)):
            f = cum / total_len if total_len > 1e-6 else 0.0
            in_range = lo - 1e-9 <= f <= hi + 1e-9

            if in_range:
                # Interpolate entry boundary when the previous point was
                # outside the range.
                if not clipped and i > 0 and prev_f < lo - 1e-9 and f > prev_f:
                    t = (lo - prev_f) / (f - prev_f)
                    clipped.append(new_pts[i - 1] + (new_pts[i] - new_pts[i - 1]) * t)
                clipped.append(new_pts[i])
            elif f > hi + 1e-9:
                # Past range – interpolate exit boundary.
                if i > 0 and f > prev_f:
                    t = (hi - prev_f) / (f - prev_f)
                    clipped.append(new_pts[i - 1] + (new_pts[i] - new_pts[i - 1]) * t)
                break

            prev_f = f
            if i < len(segment_lengths):
                cum += segment_lengths[i]

        if len(clipped) < 2:
            # Range falls between two consecutive points – interpolate both ends.
            cum2 = 0.0
            for i in range(1, len(new_pts)):
                f_prev = cum2 / total_len if total_len > 1e-6 else 0.0
                cum2 += segment_lengths[i - 1] if i - 1 < len(segment_lengths) else 0
                f_cur = cum2 / total_len if total_len > 1e-6 else 1.0
                if f_cur >= lo - 1e-9 and f_prev <= lo + 1e-9:
                    span = f_cur - f_prev if f_cur > f_prev else 1e-9
                    t_lo = max(0.0, min(1.0, (lo - f_prev) / span))
                    t_hi = max(0.0, min(1.0, (hi - f_prev) / span))
                    p1 = new_pts[i - 1] + (new_pts[i] - new_pts[i - 1]) * t_lo
                    p2 = new_pts[i - 1] + (new_pts[i] - new_pts[i - 1]) * t_hi
                    clipped = [p1, p2]
                    break
            if len(clipped) < 2:
                return res_full  # fallback

        if backward:
            clipped.reverse()

        res = QPainterPath(clipped[0])
        for pt in clipped[1:]:
            res.lineTo(pt)
        return res

    def _create_arrow(self, pos: QPointF, tangent: QPointF, color: QColor) -> None:
        mag = math.hypot(tangent.x(), tangent.y())
        if mag <= 1e-6:
            return
        ux = tangent.x() / mag
        uy = tangent.y() / mag
        nx = -uy
        ny = ux

        # Slightly larger triangle: 10 units long, 8 units wide.
        local_pts = [QPointF(-5.0, -4.0), QPointF(5.0, 0.0), QPointF(-5.0, 4.0)]
        world_pts = [
            QPointF(
                pos.x() + lp.x() * ux + lp.y() * nx,
                pos.y() + lp.x() * uy + lp.y() * ny,
            )
            for lp in local_pts
        ]
        arrow_path = QPainterPath(world_pts[0])
        arrow_path.lineTo(world_pts[1])
        arrow_path.lineTo(world_pts[2])
        arrow_path.closeSubpath()

        # Keep arrows above all infrastructure items to avoid being hidden by nodes/labels.
        arrow_item = QGraphicsPathItem(arrow_path)
        if self.scene() is not None:
            self.scene().addItem(arrow_item)
        # Black outline for better visibility when zoomed out
        outline_pen = QPen(Qt.GlobalColor.black)
        outline_pen.setWidthF(1.0)
        outline_pen.setCosmetic(True) # Keeps pen width constant regardless of zoom
        arrow_item.setPen(outline_pen)
        arrow_item.setBrush(QBrush(color))
        arrow_item.setZValue(50)
        arrow_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        
        self._arrows.append(arrow_item)

    def _create_bidirectional_arrow(self, pos: QPointF, angle_deg: float, color: QColor) -> None:
        # A diamond or double-headed arrow shape
        arrow_path = QPainterPath()
        # Head 1 (right)
        arrow_path.moveTo(1, -4)
        arrow_path.lineTo(7, 0)
        arrow_path.lineTo(1, 4)
        arrow_path.closeSubpath()
        # Head 2 (left)
        arrow_path.moveTo(-1, -4)
        arrow_path.lineTo(-7, 0)
        arrow_path.lineTo(-1, 4)
        arrow_path.closeSubpath()

        trans = QTransform()
        trans.translate(pos.x(), pos.y())
        trans.rotate(-angle_deg)
        
        # Keep arrows above all infrastructure items to avoid being hidden by nodes/labels.
        arrow_item = QGraphicsPathItem(trans.map(arrow_path))
        if self.scene() is not None:
            self.scene().addItem(arrow_item)
        outline_pen = QPen(Qt.GlobalColor.black)
        outline_pen.setWidthF(1.0)
        outline_pen.setCosmetic(True)
        arrow_item.setPen(outline_pen)
        arrow_item.setBrush(QBrush(color))
        arrow_item.setZValue(50)
        arrow_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        
        self._arrows.append(arrow_item)

    def set_timing_points_visible(self, enabled: bool) -> None:
        self._timing_points_visible = bool(enabled)
        self._update_outer_pen()

    def set_theme(self, theme: str) -> None:
        if theme == "dark":
            self._outer_pen_default.setColor(QColor(ModernColors.TRACK_DEFAULT_D))
            self._inner_pen.setColor(QColor(ModernColors.D_SURFACE))
        else:
            self._outer_pen_default.setColor(QColor(ModernColors.TRACK_DEFAULT_L))
            self._inner_pen.setColor(QColor(ModernColors.L_SURFACE))
        self._inner_overlay.setPen(self._inner_pen)
        self._update_outer_pen()

    def set_outer_pens(
        self,
        *,
        default: Optional[QPen] = None,
        visible: Optional[QPen] = None,
        hover: Optional[QPen] = None,
        inner: Optional[QPen] = None,
    ) -> None:
        if default is not None:
            self._outer_pen_default = QPen(default)
        if visible is not None:
            self._outer_pen_visible = QPen(visible)
        if hover is not None:
            self._outer_pen_hover = QPen(hover)
        if inner is not None:
            self._inner_pen = QPen(inner)
            self._inner_overlay.setPen(self._inner_pen)
        self._update_outer_pen()

    def set_hover_highlight(self, enabled: bool) -> None:
        self._hovered = bool(enabled)
        self._update_outer_pen()

    def _update_outer_pen(self) -> None:
        if self._hovered:
            self.setPen(self._outer_pen_hover)
        elif self._timing_points_visible:
            self.setPen(self._outer_pen_visible)
        else:
            self.setPen(self._outer_pen_default)

    def hoverEnterEvent(self, event):
        self.set_hover_highlight(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.set_hover_highlight(False)
        super().hoverLeaveEvent(event)
