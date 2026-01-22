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
        
        # 1. Get ordered timing points along the route with their absolute positions
        ordered_tps_with_pos = self._get_ordered_tps_with_route_pos()
        
        # 2. Physics Simulation
        start_time_str = parameters.get("startTime", datetime.now(timezone.utc).isoformat())
        try:
            current_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
        except ValueError:
            current_time = datetime.now(timezone.utc)

        train_type = parameters.get("trainType", "S1")
        dwell_time_s = float(parameters.get("dwellTime", 20.0))
        
        # Persistent state for physics
        train_state = TrainState()
        
        # Group by segmentProfileId
        segments: Dict[int, List[Dict[str, Any]]] = {}
        segment_order: List[int] = []
        
        last_pos = 0.0
        
        for i, (tp, route_pos) in enumerate(ordered_tps_with_pos):
            distance_delta = route_pos - last_pos
            
            # 2a. Check for user-defined constraints
            user_c = selection.timing_constraints.get(tp.id)
            if user_c:
                is_stop = (user_c.get("pointType") == "STOP")
            else:
                is_stop = bool(tp.stopping_location_id)
            
            # Determine if we should decelerate
            # Simple heuristic: if this TP or one soon after is a STOP, consider deceleration
            mode = "accel"
            if is_stop or i == len(ordered_tps_with_pos) - 1:
                mode = "decel" if i > 0 else "accel" 

            travel_time = simulate_travel(train_type, distance_delta, train_state, mode=mode)
            current_time += timedelta(seconds=travel_time)
            
            # If user provided a specific arrival time, use it to override/align the simulation
            arrival_ts_str = None
            if user_c and user_c.get("arrivalTime"):
                try:
                    # Expecting HH:MM:SS or HH:MM
                    user_time_str = user_c["arrivalTime"]
                    fmt = "%H:%M:%S" if user_time_str.count(":") == 2 else "%H:%M"
                    user_t = datetime.strptime(user_time_str, fmt).time()
                    current_time = datetime.combine(current_time.date(), user_t).replace(tzinfo=current_time.tzinfo)
                except ValueError:
                    pass # Fallback to simulated time
            
            arrival_ts_str = current_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

            tp_constraint = {
                "tpType": "STOP" if is_stop else "PASS",
                "timingPointId": tp.id,
                "latestArrivalTimestamp": arrival_ts_str,
                "arrivalWindow": 0,
                "alignment": "FRONT",
                "endOfJourney": i == len(ordered_tps_with_pos) - 1,
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
                
                tp_constraint["openingDoorSide"] = "NONE"
                tp_constraint["centralisedOpening"] = False
                tp_constraint["relaxedCoupler"] = False
                tp_constraint["stoppingPointDepartureDetails"] = {
                    "trainHold": False,
                    "departureTimestamp": dep_ts_str,
                    "minimumDwellTime": int(dwell_time_s),
                    "automaticDoorClosing": False
                }
            
            if tp.segment_profile_id not in segments:
                segments[tp.segment_profile_id] = []
                segment_order.append(tp.segment_profile_id)
            
            segments[tp.segment_profile_id].append(tp_constraint)
            last_pos = route_pos

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
            "segmentProfileReferences": []
        }
        
        for seg_id in segment_order:
            profile["segmentProfileReferences"].append({
                "countryId": 0,
                "segmentProfileId": seg_id,
                "version": 0,
                "direction": "NOMINAL",
                "timingPointConstraints": segments[seg_id]
            })
            
        return profile

    def _get_ordered_tps_with_route_pos(self) -> List[tuple[TimingPoint, float]]:
        """
        Finds timing points on the selected route and calculates their absolute distance
        from the start of the route.
        """
        model = self._backend.model
        selection = self._backend.selection
        
        if not selection.current_tracks:
            return []
            
        # 1. Map tracks to their absolute start distance in route
        track_start_pos = {}
        curr_pos = 0.0
        for tid in selection.current_tracks:
            track = model.tracks.get(tid)
            if not track: continue
            track_start_pos[tid] = curr_pos
            curr_pos += track.length_m
            
        # 2. Collect TPs on these tracks
        route_tps = []
        for tp in model.timing_points.values():
            if tp.track_id in track_start_pos:
                # Calculate TP position within the route
                # tp.distance_to_target_m is distance FROM tp TO track.target_node
                track = model.tracks[tp.track_id]
                
                # We need to check the route direction.
                # If the route uses this track from source to target:
                # route_pos = track_start + (track_length - tp.distance_to_target)
                # If reverse (target to source):
                # route_pos = track_start + tp.distance_to_target
                
                # Check route direction for this track
                # Find where this track appears in selection.current_route
                try:
                    t_idx = selection.current_tracks.index(tp.track_id)
                    u = selection.current_route[t_idx]
                    v = selection.current_route[t_idx+1]
                    
                    if track.source == u: # Nominal direction
                        if tp.target_node_id != track.target: continue
                        local_pos = track.length_m - tp.distance_to_target_m
                    else: # Reverse direction
                        if tp.target_node_id != track.source: continue
                        local_pos = tp.distance_to_target_m
                        
                    route_pos = track_start_pos[tp.track_id] + local_pos
                    route_tps.append((tp, route_pos))
                except (ValueError, IndexError):
                    continue
        
        # 3. Sort by route position
        route_tps.sort(key=lambda x: x[1])
        return route_tps

    def export_to_file(self, file_path: str, parameters: Dict[str, Any]):
        data = self.export_journey_profile(parameters)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
