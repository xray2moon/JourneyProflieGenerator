from __future__ import annotations

import math
from typing import Dict, List, Optional

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QPainterPath

from Source.infra_models import Track, TimingPoint, StoppingLocation


class InfrastructureViewLayouts:
    def __init__(self, view):
        self._host = view
        self._view = view._view

    def __getattr__(self, name):
        return getattr(self._host, name)
    def _path_from_points(self, pts: List[QPointF]) -> QPainterPath:
        path = QPainterPath(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        return path

    # -----------------
    # Geographic layout
    # -----------------

    def _compute_node_positions(self) -> Dict[str, QPointF]:
        model = self._backend.model
        return {node_id: QPointF(node.x, node.y) for node_id, node in model.nodes.items()}

    def _geographic_polyline_points_for_track(self, tr: Track) -> Optional[List[QPointF]]:
        model = self._backend.model
        if tr.source not in model.nodes or tr.target not in model.nodes:
            return None
        src = self._node_positions.get(tr.source)
        tgt = self._node_positions.get(tr.target)
        if src is None or tgt is None:
            return None
        pts = [QPointF(src)]
        pts += [QPointF(x, y) for (x, y) in tr.shaping_points]
        pts.append(QPointF(tgt))
        return pts

    def _track_to_path(self, tr: Track) -> Optional[QPainterPath]:
        pts = self._geographic_polyline_points_for_track(tr)
        return self._path_from_points(pts) if pts else None

    def _polyline_points_for_track(self, tr: Track) -> Optional[List[QPointF]]:
        return self._geographic_polyline_points_for_track(tr)

    # -----------------
    # Marker positioning
    # -----------------

    def _point_along_polyline(self, pts: List[QPointF], fraction: float) -> QPointF:
        """
        Return point at 'fraction' of total polyline length (0..1),
        using Euclidean length of drawn geometry.
        """
        fraction = max(0.0, min(1.0, fraction))
        seglens: List[float] = []
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
        model = self._backend.model
        tr = model.tracks.get(tp.track_id)
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
            frac = 0.5
        return self._point_along_polyline(pts, frac)

    def _stopping_location_position(self, sl: StoppingLocation) -> Optional[QPointF]:
        model = self._backend.model
        tr = model.tracks.get(sl.track_id)
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
    # Hit-testing
    # --------------

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
        model = self._backend.model
        for tr in model.tracks.values():
            pts = self._polyline_points_for_track(tr)
            if not pts:
                continue
            d = self._min_dist_sq_to_polyline(scene_pos, pts)
            if d <= tol_sq and d < best_d:
                best_d = d
                best_id = tr.id
        return best_id
