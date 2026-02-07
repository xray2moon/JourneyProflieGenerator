import os
import sys
import unittest
from pathlib import Path


# --- MOCK PYQT6 (routing imports QMessageBox) ---
class _MockQMessageBox:
    class StandardButton:
        Yes = 1
        No = 0

    @staticmethod
    def question(*args, **kwargs):
        return _MockQMessageBox.StandardButton.No

    @staticmethod
    def warning(*args, **kwargs):
        return None

    @staticmethod
    def critical(*args, **kwargs):
        return None

    @staticmethod
    def information(*args, **kwargs):
        return None


class _MockQtWidgets:
    QMessageBox = _MockQMessageBox


class _MockPyQt6:
    QtWidgets = _MockQtWidgets


sys.modules.setdefault("PyQt6", _MockPyQt6)
sys.modules.setdefault("PyQt6.QtWidgets", _MockQtWidgets)


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from Source.infra_data_manager import InfrastructureParser
from Source.infra_view_routing import InfrastructureViewRouting


TURN_NODE_1878 = "187829d0-3391-4937-a89f-e6e37b0dc5e7"
TURN_NODE_5032 = "50320a8d-ed4a-46d3-9484-5862d6531de2"
TURN_NODE_75 = "ff6aaf01-c29d-4d42-94b8-59447117ebc0"

TRACK_855 = "855163d1-1ff1-483d-810f-4b723fbc9bff"
TRACK_1DE = "1de36527-ff9a-4a65-bc93-76c19dd6457d"
TRACK_75_44 = "e95ec1f3-b0a2-499a-8f97-8bcdb3ff2fd1"

TP_740 = 740
TP_2251 = 2251
TP_4171 = 4171
TP_2585 = 2585


class _SelectionStub:
    def __init__(self):
        self.current_route = []
        self.current_tracks = []
        self.timing_constraints = {}
        self.start_tp_id = None
        self.end_tp_id = None
        self.waypoint_tp_ids = []

    def set_route(self, nodes, tracks):
        self.current_route = list(nodes)
        self.current_tracks = list(tracks)

    def set_start_tp(self, tp_id):
        self.start_tp_id = tp_id

    def set_end_tp(self, tp_id):
        self.end_tp_id = tp_id

    def set_waypoint_tp_ids(self, tp_ids):
        self.waypoint_tp_ids = list(tp_ids)

    def set_timing_constraint(self, tp_id, constraint):
        if constraint is None:
            self.timing_constraints.pop(tp_id, None)
        else:
            self.timing_constraints[tp_id] = constraint

    def clear_selection(self):
        self.current_route = []
        self.current_tracks = []
        self.start_tp_id = None
        self.end_tp_id = None
        self.waypoint_tp_ids = []


class _BackendStub:
    def __init__(self, model):
        self.model = model
        self.selection = _SelectionStub()


class _ViewStub:
    def __init__(self, model):
        self._backend = _BackendStub(model)
        self._view = None
        self._graph = {}


def _immediate_uturns(route_nodes, route_tracks):
    out = []
    for i in range(len(route_tracks) - 1):
        if route_tracks[i] != route_tracks[i + 1]:
            continue
        if i + 2 >= len(route_nodes):
            continue
        if route_nodes[i] == route_nodes[i + 2]:
            out.append((route_nodes[i + 1], route_tracks[i]))
    return out


class TestRoutingReversals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        json_path = (
            Path(__file__).resolve().parents[1]
            / "data_examples"
            / "ebd_v7_3_stations-infrastructure-description.json"
        )
        cls.model = InfrastructureParser.parse_file(str(json_path))

    def _run_sequence(self, seq):
        view = _ViewStub(self.model)
        routing = InfrastructureViewRouting(view)
        routing._build_graph()
        for tp_id in seq:
            routing._extend_route_with_tp(tp_id)
        return view._backend.selection

    def test_prefers_turn_segment_reversal_when_valid(self):
        sel = self._run_sequence([3237, 3847])
        self.assertEqual(sel.start_tp_id, 3237)
        self.assertEqual(sel.end_tp_id, 3847)
        self.assertIn(TP_740, sel.waypoint_tp_ids)
        self.assertNotIn(TP_2585, sel.waypoint_tp_ids)

    def test_falls_back_when_turn_segment_is_too_short(self):
        sel = self._run_sequence([3237, 3846, 286])
        self.assertEqual(sel.end_tp_id, 286)
        self.assertIn(TP_2251, sel.waypoint_tp_ids)

        # Regression: avoid raw node turn on the 22.5m segment at node 50320...
        uturns = _immediate_uturns(sel.current_route, sel.current_tracks)
        self.assertNotIn((TURN_NODE_5032, TRACK_1DE), uturns)

    def test_no_extra_reversal_added_when_not_needed(self):
        sel = self._run_sequence([3236, 3848, 281, 1039])
        self.assertEqual(sel.waypoint_tp_ids, [740, 3848, 2251, 281, 3147])

    def test_adds_additional_reversal_for_late_turn_node_75(self):
        sel = self._run_sequence([3235, 3849, 317, 3539])
        self.assertEqual(sel.end_tp_id, 3539)
        self.assertIn(TP_4171, sel.waypoint_tp_ids)

        # Ensure the late U-turn (node 75 on track 75<->44) is protected by TP 4171.
        uturns = _immediate_uturns(sel.current_route, sel.current_tracks)
        self.assertIn((TURN_NODE_75, TRACK_75_44), uturns)


if __name__ == "__main__":
    unittest.main()
