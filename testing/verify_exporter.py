import sys
import os
import unittest
import json
from unittest.mock import MagicMock

# Inject Mock Numpy first
class MockNumpy:
    inf = float('inf')
    @staticmethod
    def array(data): return list(data)
    @staticmethod
    def searchsorted(a, v): import bisect; return bisect.bisect_left(a, v)
    @staticmethod
    def sum(a): return sum(a)
sys.modules['numpy'] = MockNumpy

# --- MOCK PYQT6 START ---
class MockPyQt6:
    class QtCore:
        class QObject:
            def __init__(self, *args, **kwargs): pass
        
        @staticmethod
        def pyqtSignal(*args):
            class Signal:
                def emit(self, *args): pass
                def connect(self, slot): pass
            return Signal()

sys.modules['PyQt6'] = MockPyQt6
sys.modules['PyQt6.QtCore'] = MockPyQt6.QtCore
# --- MOCK PYQT6 END ---

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Source.journey_profile_exporter import JourneyProfileExporter
from Source.infra_models import Track, TimingPoint
from Source.infra_data_manager import InfrastructureModel
from Source.infra_selection_model import InfrastructureSelectionModel

class TestJourneyProfileExporter(unittest.TestCase):
    
    def setUp(self):
        # Mock Backend and Model
        self.backend = MagicMock()
        self.model = InfrastructureModel()
        self.selection = InfrastructureSelectionModel()
        
        self.backend.model = self.model
        self.backend.selection = self.selection
        
        self.exporter = JourneyProfileExporter(self.backend)

    def test_simple_A_to_B_journey(self):
        """
        Suite B.1: Simple 1-track journey profile generation.
        """
        print("\n[Test] Exporting Simple A->B Journey...")
        
        # Setup Infrastructure
        # Nodes: A -> B
        # Track: T1 (Length 1000m)
        track1 = Track(id="T1", source="NodeA", target="NodeB", shaping_points=[], length_m=1000.0)
        self.model.tracks["T1"] = track1
        
        # Timing Points
        # TP1 at Start (NodeA) - Implicitly handled or explicitly placed?
        # Typically TPs are on tracks. Let's put one at 0m (near A) and one at 1000m (near B)
        tp_start = TimingPoint(id=1, track_id="T1", target_node_id="NodeA", distance_to_target_m=0.0, stopping_location_id=None, segment_profile_id=10)
        tp_end = TimingPoint(id=2, track_id="T1", target_node_id="NodeB", distance_to_target_m=0.0, stopping_location_id="Stop1", segment_profile_id=10)
        
        # Note: logic in exporter: 
        # if tp.target_node_id == v (NodeB): local_pos = track.length - tp.distance
        # if tp.target_node_id == u (NodeA): local_pos = tp.distance
        
        # So for T1 (A->B):
        # tp_start (Target A, dist 0) -> pos = 0
        # tp_end (Target B, dist 0) -> pos = 1000 - 0 = 1000
        
        self.model.timing_points = {1: tp_start, 2: tp_end}
        
        # Setup Selection
        self.selection.set_route(["NodeA", "NodeB"], ["T1"])
        # tp_end is a stop
        self.selection._timing_constraints = {
            2: {"pointType": "STOP", "arrivalTime": "12:00:00"}
        }
        
        # Export
        params = {
            "startTime": "2025-01-01T10:00:00Z",
            "trainType": "S1",
            "dwellTime": 30.0
        }
        
        profile = self.exporter.export_journey_profile(params)
        
        # Verification
        # Check basic keys
        self.assertIn("meta", profile)
        self.assertIn("segmentProfileReferences", profile)
        
        segments = profile["segmentProfileReferences"]
        self.assertEqual(len(segments), 1)
        
        constraints = segments[0]["timingPointConstraints"]
        self.assertEqual(len(constraints), 2, "Should have 2 TPs")
        
        # Check TP1 (Start)
        self.assertEqual(constraints[0]["timingPointId"], 1)
        self.assertEqual(constraints[0]["tpType"], "PASS") # Default
        
        # Check TP2 (End)
        self.assertEqual(constraints[1]["timingPointId"], 2)
        self.assertEqual(constraints[1]["tpType"], "STOP")
        self.assertTrue(constraints[1]["endOfJourney"])
        
        # Check Timing Consistency
        t1 = constraints[0]["latestArrivalTimestamp"]
        t2 = constraints[1]["latestArrivalTimestamp"]
        print(f"  > Start: {t1} | End: {t2}")
        self.assertLess(t1, t2)

    def test_reversal_logic(self):
        """
        Suite B.3 / C.4: Route with Reversal A->B->A
        """
        print("\n[Test] Exporting Reversal Journey A->B->A...")
        
        # Track T1: A -> B (1000m)
        track1 = Track(id="T1", source="NodeA", target="NodeB", shaping_points=[], length_m=1000.0)
        self.model.tracks["T1"] = track1
        
        # TPs: 
        # 1 at A
        # 2 at B (Stop/Reversal)
        tp1 = TimingPoint(id=1, track_id="T1", target_node_id="NodeA", distance_to_target_m=0.0, stopping_location_id=None, segment_profile_id=10)
        tp2 = TimingPoint(id=2, track_id="T1", target_node_id="NodeB", distance_to_target_m=0.0, stopping_location_id="StopB", segment_profile_id=10)
        
        self.model.timing_points = {1: tp1, 2: tp2}
        
        # Route: A -> B -> A
        # Tracks: T1, T1 (traversed twice)
        self.selection.set_route(["NodeA", "NodeB", "NodeA"], ["T1", "T1"])
        
        # Constraints
        # Explicitly mark TP2 as STOP? 
        # Reversal logic in exporter automatically detects direction change.
        
        params = {"startTime": "2025-01-01T10:00:00Z"}
        
        profile = self.exporter.export_journey_profile(params)
        
        segments = profile["segmentProfileReferences"]
        # Expecting 2 segments: 
        # 1. A->B (Source->Target). Project convention: REVERSE.
        # 2. B->A (Target->Source). Project convention: NOMINAL.
        self.assertEqual(len(segments), 2)
        
        self.assertEqual(segments[0]["direction"], "REVERSE")
        self.assertEqual(segments[1]["direction"], "NOMINAL")
        
        # Check TPs
        # Seg 1: TP1 -> TP2
        # Seg 2: TP2 -> TP1
        
        c1 = segments[0]["timingPointConstraints"]
        c2 = segments[1]["timingPointConstraints"]
        
        self.assertEqual(c1[-1]["timingPointId"], 2)
        self.assertEqual(c2[0]["timingPointId"], 2) # Should verify if exporter includes start TP of new segment? 
        # Exporter logic: "if not profile_segments or ... != forced_seg_id ... append"
        # It adds TP constraint.
        
        # Verify timestamps increase across segments
        t_mid = c1[-1]["latestArrivalTimestamp"]
        t_return = c2[0]["latestArrivalTimestamp"]
        print(f"  > Arrival at Reversal: {t_mid}")
        print(f"  > Departure/Arrival Return: {t_return}")
        self.assertLess(t_mid, t_return)

if __name__ == '__main__':
    unittest.main()
