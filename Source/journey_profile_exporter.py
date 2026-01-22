from __future__ import annotations
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
from Source.infra_backend import InfrastructureBackend
from Source.dynamics import TrainState, simulate_travel
from Source.infra_models import TimingPoint

class JourneyProfileExporter:
    """
    Exports the current state (route, timing constraints, parameters)
    to a Journey Profile JSON file matching story3-initial-journeyprofile1.json style.
    """
    def __init__(self, backend: InfrastructureBackend):
        self._backend = backend

    def export_journey_profile(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        selection = self._backend.selection
        model = self._backend.model
        
        if not selection.current_tracks:
            return {}

        # Pre-group timing points by track for efficiency
        tps_by_track: Dict[str, List[TimingPoint]] = {}
        for tp in model.timing_points.values():
            tps_by_track.setdefault(tp.track_id, []).append(tp)

        # 1. Gather all events (TPs and Reversals) along the route
        events = [] # List of (type, data, abs_pos, track_dir)
        curr_route_pos = 0.0
        last_track_dir = None
        reversal_tp_ids = set()

        for i, tid in enumerate(selection.current_tracks):
            track = model.tracks.get(tid)
            if not track:
                continue
            u = selection.current_route[i]
            v = selection.current_route[i+1]
            
            # Absolute direction on this track relative to its definition
            # Swapped as per user request: if track.target == v, it was NOMINAL, now REVERSE
            curr_track_dir = "REVERSE" if track.target == v else "NOMINAL"
            
            if last_track_dir is not None and last_track_dir != curr_track_dir:
                # REVERSAL at node u
                # Check if last TP was exactly at this node
                found_tp_at_u = False
                if events:
                    # Search backwards for the last TP event
                    for j in range(len(events) - 1, -1, -1):
                        if events[j][0] == "TP":
                            etype_last, tp_last, pos_last, dir_last = events[j]
                            # If the last TP was at the reversal node, mark it as a stop
                            if abs(pos_last - curr_route_pos) < 1.0: # Increased tolerance
                                reversal_tp_ids.add(tp_last.id)
                                found_tp_at_u = True
                            break
                
                if not found_tp_at_u:
                    events.append(("REVERSAL", u, curr_route_pos, curr_track_dir))
            
            # TPs on this track moving towards v
            track_tps = []
            for tp in tps_by_track.get(tid, []):
                # Timing point is relevant if its target node is the one we are moving towards
                if tp.target_node_id == v:
                    local_pos = track.length_m - tp.distance_to_target_m
                    track_tps.append(("TP", tp, curr_route_pos + local_pos, curr_track_dir))
            
            track_tps.sort(key=lambda x: x[2])
            events.extend(track_tps)
            
            curr_route_pos += track.length_m
            last_track_dir = curr_track_dir

        # Ensure we simulate until the very end of the route
        if not events or events[-1][2] < curr_route_pos - 0.1:
            events.append(("END", None, curr_route_pos, last_track_dir))

        # 2. Physics Simulation
        start_time_str = parameters.get("startTime", datetime.now(timezone.utc).isoformat())
        try:
            current_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
        except ValueError:
            current_time = datetime.now(timezone.utc)

        train_type = parameters.get("trainType", "S1")
        dwell_time_s = float(parameters.get("dwellTime", 20.0))
        train_state = TrainState()
        
        profile_segments: List[Dict[str, Any]] = []
        last_pos = 0.0
        
        # Identify the index of the last TP for endOfJourney flag
        last_tp_index = -1
        for j in range(len(events) - 1, -1, -1):
            if events[j][0] == "TP":
                last_tp_index = j
                break

        # Identify all stop positions for look-ahead braking
        stop_positions = []
        for i, (etype, edata, abs_pos, edir) in enumerate(events):
            is_stop = False
            if etype == "REVERSAL" or etype == "END":
                is_stop = True
            else:
                tp = edata
                user_c = selection.timing_constraints.get(tp.id)
                if user_c:
                    is_stop = (user_c.get("pointType") == "STOP")
                else:
                    is_stop = bool(tp.stopping_location_id) or (tp.id in reversal_tp_ids)
            
            if is_stop:
                stop_positions.append(abs_pos)

        for i, (etype, edata, abs_pos, edir) in enumerate(events):
            distance_delta = abs_pos - last_pos
            if distance_delta < 0:
                distance_delta = 0.0
            
            is_stop = False
            tp = None
            if etype == "REVERSAL" or etype == "END":
                is_stop = True
            else:
                tp = edata
                user_c = selection.timing_constraints.get(tp.id)
                if user_c:
                    is_stop = (user_c.get("pointType") == "STOP")
                else:
                    is_stop = bool(tp.stopping_location_id) or (tp.id in reversal_tp_ids)
            
            # Find distance to next stop for look-ahead
            next_stop_pos = float('inf')
            for sp in stop_positions:
                if sp >= abs_pos - 0.001: # Use small epsilon
                    next_stop_pos = sp
                    break
            
            distance_to_stop = next_stop_pos - last_pos

            travel_time = simulate_travel(train_type, distance_delta, train_state, mode="accel", distance_to_stop=distance_to_stop)
            current_time += timedelta(seconds=travel_time)
            
            if etype == "TP":
                # If user provided a specific arrival time, use it to override/align the simulation
                user_c = selection.timing_constraints.get(tp.id)
                if user_c and user_c.get("arrivalTime"):
                    try:
                        user_time_str = user_c["arrivalTime"]
                        fmt = "%H:%M:%S" if user_time_str.count(":") == 2 else "%H:%M"
                        user_t = datetime.strptime(user_time_str, fmt).time()
                        current_time = datetime.combine(current_time.date(), user_t).replace(tzinfo=current_time.tzinfo)
                    except ValueError:
                        pass
                
                arrival_ts_str = current_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

                tp_constraint = {
                    "tpType": "STOP" if is_stop else "PASS",
                    "timingPointId": tp.id,
                    "latestArrivalTimestamp": arrival_ts_str,
                    "arrivalWindow": 0,
                    "alignment": "FRONT",
                    "endOfJourney": i == last_tp_index,
                    "daylightSaving": True
                }
                
                if is_stop:
                    # Handle departure/dwell
                    dep_ts_str = None
                    if user_c and user_c.get("departureTime"):
                        try:
                            user_time_str = user_c["departureTime"]
                            fmt = "%H:%M:%S" if user_time_str.count(":") == 2 else "%H:%M"
                            user_t = datetime.strptime(user_time_str, fmt).time()
                            current_time = datetime.combine(current_time.date(), user_t).replace(tzinfo=current_time.tzinfo)
                            dep_ts_str = current_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                        except ValueError:
                            pass

                    if not dep_ts_str:
                        current_time += timedelta(seconds=dwell_time_s)
                        dep_ts_str = current_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

                    # After a stop, we reset indices to start accelerating from 0 again
                    train_state.accel_idx = 0
                    train_state.decel_idx = 0
                    train_state.velocity = 0.0
                    train_state.braking_triggered = False
                    
                    tp_constraint["openingDoorSide"] = "NONE"
                    tp_constraint["centralisedOpening"] = False
                    tp_constraint["relaxedCoupler"] = False
                    tp_constraint["stoppingPointDepartureDetails"] = {
                        "trainHold": False,
                        "departureTimestamp": dep_ts_str,
                        "minimumDwellTime": int(dwell_time_s),
                        "automaticDoorClosing": False
                    }
                
                if not profile_segments or \
                   profile_segments[-1]["segmentProfileId"] != tp.segment_profile_id or \
                   profile_segments[-1]["direction"] != edir:
                    profile_segments.append({
                        "countryId": 0,
                        "segmentProfileId": tp.segment_profile_id,
                        "version": 0,
                        "direction": edir,
                        "timingPointConstraints": []
                    })
                
                profile_segments[-1]["timingPointConstraints"].append(tp_constraint)
            
            elif etype == "REVERSAL":
                # For a reversal without a TP, we still dwell and reset state
                current_time += timedelta(seconds=dwell_time_s)
                train_state.accel_idx = 0
                train_state.decel_idx = 0
                train_state.velocity = 0.0
                train_state.braking_triggered = False
            
            last_pos = abs_pos

        # 3. Build full JSON structure
        profile = {
            "meta": {
                "eventId": f"JP.{uuid.uuid4()}",
                "eventType": "JourneyProfile",
                "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                "createdBy": "JourneyProfileGenerator-CLI",
                "correlation": [str(uuid.uuid4()), str(uuid.uuid4())]
            },
            "tmsHeader": {
                "tmsId": 0,
                "countryId": 96,
                "timezoneOffset": "+00:00"
            },
            "atoTracksideDestination": {"atoTsId": 1},
            "atoOnboardDestination": {"nidOperational": "FFFFFFF1"},
            "status": "VALID",
            "dataId": f"FFFFFFF1.{datetime.now().strftime('%Y-%m-%d')}",
            "operatingDay": datetime.now().strftime("%Y-%m-%d"),
            "segmentProfileReferences": profile_segments
        }
        
        return profile

    def export_to_file(self, file_path: str, parameters: Dict[str, Any]):
        data = self.export_journey_profile(parameters)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
