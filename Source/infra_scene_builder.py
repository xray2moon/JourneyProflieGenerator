from __future__ import annotations
from typing import Dict, List, Optional, Tuple, Set
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtWidgets import QGraphicsScene

from Source.infra_models import Node, Track, TimingPoint, StoppingLocation
from Source.infra_items import NodeItem, TrackItem, TimingPointItem, StoppingLocationItem

class InfrastructureSceneBuilder:
    """
    Handles the creation and placement of QGraphicsItems on the scene.
    Separates the 'Building' logic from the View/Mixin logic.
    """
    def __init__(self, scene: QGraphicsScene):
        self._scene = scene
        self._current_theme = "light" # Default

    def set_theme(self, theme: str):
        self._current_theme = theme

    def clear(self):
        self._scene.clear()

    def build_geographic(
        self,
        nodes: Dict[str, Node],
        tracks: Dict[str, Track],
        timing_points: Dict[int, TimingPoint],
        stopping_locations: Dict[str, StoppingLocation],
        node_positions: Dict[str, QPointF],
        track_paths: Dict[str, any], # Painter paths
        tp_positions: Dict[int, QPointF],
        sl_positions: Dict[str, QPointF],
        sl_to_group: Dict[str, str],
        show_all_tp: bool,
        visible_tp_tracks: Set[str],
        timing_constraints: Dict[int, dict]
    ) -> Dict[str, any]:
        """
        Builds the geographic representation.
        Returns a dictionary of created items for the View to keep track of.
        """
        results = {
            "node_items": {},
            "track_items": {},
            "tp_items": {},
            "sl_items": {},
            "tp_track_map": {}
        }

        # Tracks first
        for tr_id, path in track_paths.items():
            tr = tracks[tr_id]
            item = TrackItem(tr.id, path)
            item.set_theme(self._current_theme)
            item.setAcceptHoverEvents(True)
            label = f"Track {tr.numeric_id}" if tr.numeric_id is not None else "Track"
            tip = f"{label}\nlen={tr.length_m:.0f} m\n{tr.id}"
            item.setToolTip(tip)
            item.inner_overlay().setToolTip(tip)
            item.route_overlay().setToolTip(tip)
            item.inner_overlay().setAcceptHoverEvents(False)
            item.route_overlay().setAcceptHoverEvents(False)
            item.set_timing_points_visible(show_all_tp or tr.id in visible_tp_tracks)
            
            self._scene.addItem(item)
            self._scene.addItem(item.inner_overlay())
            self._scene.addItem(item.route_overlay())
            results["track_items"][tr.id] = item
            results["tp_track_map"].setdefault(tr.id, [])

        # Nodes
        for node_id, node in nodes.items():
            pos = node_positions.get(node_id, QPointF(node.x, node.y))
            ni = NodeItem(node)
            ni.set_theme(self._current_theme)
            ni.setPos(pos)
            self._scene.addItem(ni)
            results["node_items"][node_id] = ni

        # Timing points
        for tp_id, tp in timing_points.items():
            pos = tp_positions.get(tp_id)
            if pos is None: continue
            
            tpi = TimingPointItem(tp, pos)
            tpi.set_theme(self._current_theme)
            
            has_stop = False
            if tp.id in timing_constraints:
                c = timing_constraints[tp.id]
                if c.get("pointType") == "STOP":
                    has_stop = True

            is_visible = (show_all_tp or (tp.track_id in visible_tp_tracks) or has_stop)
            tpi.setVisible(is_visible)
            self._scene.addItem(tpi)
            results["tp_items"][tp.id] = tpi
            results["tp_track_map"].setdefault(tp.track_id, []).append(tpi)

        # Stopping locations
        for sl_id, sl in stopping_locations.items():
            pos = sl_positions.get(sl_id)
            if pos is None: continue

            group = sl_to_group.get(sl_id, "")
            suffix = ""
            if "-SL-" in sl_id:
                suffix = sl_id.split("-SL-")[-1].strip()
            label = group if group else sl_id
            if group and suffix:
                label = f"{group} {suffix}"

            sli = StoppingLocationItem(sl.id, pos, label)
            sli.set_theme(self._current_theme)
            self._scene.addItem(sli)
            self._scene.addItem(sli.label_item())
            results["sl_items"][sl_id] = sli

        return results
