from __future__ import annotations

from typing import List, Optional, Set

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

    def __init__(self, tp: TimingPoint, pos: QPointF, radius: float = 5.0):
        super().__init__(-radius, -radius, 2 * radius, 2 * radius)
        self.tp = tp
        self.setPos(pos)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

        self._base_pen = QPen(QColor(ModernColors.L_TEXT))
        self._base_pen.setWidthF(1.0)
        self._base_brush = QBrush(QColor(ModernColors.TP_DEFAULT))
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

    def set_constraint_point_type(self, point_type: Optional[str]) -> None:
        self._has_constraint = point_type is not None
        pen = QPen(Qt.GlobalColor.black)
        pen.setWidthF(2.5 if point_type == "STOP" else 1.0)
        self.setPen(pen)

    def set_theme(self, theme: str) -> None:
        if theme == "dark":
            self._base_pen.setColor(QColor(ModernColors.D_TEXT))
        else:
            self._base_pen.setColor(QColor(ModernColors.L_TEXT))
        self._base_pen.setWidthF(1.0)
        if not self._has_constraint:
            self.setPen(self._base_pen)


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

    def set_theme(self, theme: str) -> None:
        if theme == "dark":
            self.setPen(QPen(QColor(ModernColors.D_TEXT)))
            self._label_item.setBrush(QBrush(QColor(ModernColors.D_TEXT)))
        else:
            self.setPen(QPen(QColor(ModernColors.L_TEXT)))
            self._label_item.setBrush(QBrush(QColor(ModernColors.L_TEXT)))
        self.pen().setWidthF(1.0)


class TrackItem(QGraphicsPathItem):
    """
    Draws a track as a 'double line' by painting a thicker dark path and then a thinner
    white path on top (gives two rails at the edges on a white background).
    """

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
        directions: Optional[Set[str]] = None
    ) -> None:
        self._route_overlay.setVisible(enabled)
        pen = self._route_overlay.pen()
        color = QColor("purple") if is_double else QColor(ModernColors.TRACK_ROUTE)
        pen.setColor(color)
        self._route_overlay.setPen(pen)

        # Remove old arrows
        for arrow in self._arrows:
            if arrow.scene():
                arrow.scene().removeItem(arrow)
        self._arrows.clear()

        if enabled and directions:
            path = self.path()
            l = path.length()
            if l < 1e-3:
                return

            percents = [0.5] if l < 150 else [0.3, 0.7]
            
            is_both = "forward" in directions and "backward" in directions

            for p in percents:
                pos = path.pointAtPercent(p)
                angle = path.angleAtPercent(p)
                
                if is_both:
                    # Single bidirectional indicator
                    self._create_bidirectional_arrow(pos, angle, color)
                else:
                    if "forward" in directions:
                        self._create_arrow(pos, angle, color)
                    if "backward" in directions:
                        self._create_arrow(pos, angle + 180, color)

    def _create_arrow(self, pos: QPointF, angle_deg: float, color: QColor) -> None:
        arrow_path = QPainterPath()
        # Slightly larger triangle: 10 units long, 8 units wide
        arrow_path.moveTo(-5, -4)
        arrow_path.lineTo(5, 0)
        arrow_path.lineTo(-5, 4)
        arrow_path.closeSubpath()

        trans = QTransform()
        trans.translate(pos.x(), pos.y())
        trans.rotate(-angle_deg) 
        
        arrow_item = QGraphicsPathItem(trans.map(arrow_path), self)
        # Black outline for better visibility when zoomed out
        outline_pen = QPen(Qt.GlobalColor.black)
        outline_pen.setWidthF(1.0)
        outline_pen.setCosmetic(True) # Keeps pen width constant regardless of zoom
        arrow_item.setPen(outline_pen)
        arrow_item.setBrush(QBrush(color))
        arrow_item.setZValue(4)
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
        
        arrow_item = QGraphicsPathItem(trans.map(arrow_path), self)
        outline_pen = QPen(Qt.GlobalColor.black)
        outline_pen.setWidthF(1.0)
        outline_pen.setCosmetic(True)
        arrow_item.setPen(outline_pen)
        arrow_item.setBrush(QBrush(color))
        arrow_item.setZValue(4)
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
