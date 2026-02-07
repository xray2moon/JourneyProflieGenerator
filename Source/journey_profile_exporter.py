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

    def _tp_pct_from_source(self, tp_id: Optional[int]) -> Optional[float]:
        if tp_id is None:
            return None
        model = self._backend.model
        tp = model.timing_points.get(tp_id)
        if tp is None:
            return None
        track = model.tracks.get(tp.track_id)
        if track is None or track.length_m <= 0:
            return None
        pos = (
            track.length_m - tp.distance_to_target_m
            if tp.target_node_id == track.target
            else tp.distance_to_target_m
        )
        pct = pos / track.length_m
        return max(0.0, min(1.0, pct))

    def _compute_traversal_ranges(self, selection, model) -> List[tuple[float, float]]:
        ranges: List[tuple[float, float]] = []
        directions: List[str] = []
        route_tracks = selection.current_tracks
        route_nodes = selection.current_route

        for i, tid in enumerate(route_tracks):
            track = model.tracks.get(tid)
            if not track or i + 1 >= len(route_nodes):
                directions.append("forward")
                ranges.append((0.0, 1.0))
                continue
            u = route_nodes[i]
            v = route_nodes[i + 1]
            direction = "forward" if (u == track.source and v == track.target) else "backward"
            directions.append(direction)
            ranges.append((0.0, 1.0) if direction == "forward" else (1.0, 0.0))

        start_tp_id = selection.start_tp_id
        end_tp_id = selection.end_tp_id

        if route_tracks and start_tp_id is not None:
            start_tp = model.timing_points.get(start_tp_id)
            if start_tp and start_tp.track_id == route_tracks[0]:
                start_pct = self._tp_pct_from_source(start_tp_id)
                if start_pct is not None:
                    _, e0 = ranges[0]
                    ranges[0] = (start_pct, e0)

        if route_tracks and end_tp_id is not None:
            end_tp = model.timing_points.get(end_tp_id)
            if end_tp and end_tp.track_id == route_tracks[-1]:
                end_pct = self._tp_pct_from_source(end_tp_id)
                if end_pct is not None:
                    s_last, _ = ranges[-1]
                    ranges[-1] = (s_last, end_pct)

        ordered_tp_ids: List[int] = []
        if start_tp_id is not None:
            ordered_tp_ids.append(start_tp_id)
        for w in selection.waypoint_tp_ids:
            if w not in ordered_tp_ids:
                ordered_tp_ids.append(w)
        if end_tp_id is not None and end_tp_id not in ordered_tp_ids:
            ordered_tp_ids.append(end_tp_id)

        search_from = 0
        for tp_a_id, tp_b_id in zip(ordered_tp_ids, ordered_tp_ids[1:]):
            tp_a = model.timing_points.get(tp_a_id)
            tp_b = model.timing_points.get(tp_b_id)
            if not tp_a or not tp_b or tp_a.track_id != tp_b.track_id:
                continue

            pct_a = self._tp_pct_from_source(tp_a_id)
            pct_b = self._tp_pct_from_source(tp_b_id)
            if pct_a is None or pct_b is None:
                continue

            reversal_pair: Optional[tuple[int, int]] = None
            for idx in range(search_from, len(route_tracks) - 1):
                if route_tracks[idx] != tp_a.track_id or route_tracks[idx + 1] != tp_a.track_id:
                    continue
                if directions[idx] == directions[idx + 1]:
                    continue
                reversal_pair = (idx, idx + 1)
                break

            if reversal_pair is None:
                continue

            i_prev, i_next = reversal_pair
            s_prev, _ = ranges[i_prev]
            ranges[i_prev] = (s_prev, pct_a)

            _, e_next = ranges[i_next]
            ranges[i_next] = (pct_a, pct_b if route_tracks[i_next] == tp_b.track_id else e_next)
            search_from = i_next

        return ranges

    def export_journey_profile(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        selection = self._backend.selection
        model = self._backend.model
        
        if not selection.current_tracks:
            return {}

        # Pre-group timing points by track for efficiency.
        # Sort for deterministic tie-breaking when multiple TPs share a position.
        tps_by_track: Dict[str, List[TimingPoint]] = {}
        for tp in model.timing_points.values():
            tps_by_track.setdefault(tp.track_id, []).append(tp)
        for tp_list in tps_by_track.values():
            tp_list.sort(key=lambda tp: (tp.distance_to_target_m, tp.id))

        # 1. Gather all events (TPs and Reversals) along the route
        events = [] # List of (type, data, abs_pos, track_dir)
        curr_route_pos = 0.0
        last_track_dir = None
        reversal_tp_ids = set()

        start_tp_id = selection.start_tp_id
        end_tp_id = selection.end_tp_id
        traversal_ranges = self._compute_traversal_ranges(selection, model)
        selected_tp_ids_ordered: List[int] = []
        if start_tp_id is not None:
            selected_tp_ids_ordered.append(start_tp_id)
        for wid in selection.waypoint_tp_ids:
            if wid not in selected_tp_ids_ordered:
                selected_tp_ids_ordered.append(wid)
        if end_tp_id is not None and end_tp_id not in selected_tp_ids_ordered:
            selected_tp_ids_ordered.append(end_tp_id)
        selected_tp_rank = {tp_id: idx for idx, tp_id in enumerate(selected_tp_ids_ordered)}

        for i, tid in enumerate(selection.current_tracks):
            track = model.tracks.get(tid)
            if not track:
                continue
            u = selection.current_route[i]
            v = selection.current_route[i+1]
            s_pct, e_pct = traversal_ranges[i] if i < len(traversal_ranges) else (0.0, 1.0)
            
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
                            # Unpack (check len for robustness if mixed)
                            if len(events[j]) == 5:
                                etype_last, tp_last, pos_last, dir_last, seg_last = events[j]
                            else:
                                etype_last, tp_last, pos_last, dir_last = events[j]

                            # If the last TP was at the reversal node, mark it as a stop
                            if abs(pos_last - curr_route_pos) < 1.0: # Increased tolerance
                                reversal_tp_ids.add(tp_last.id)
                                found_tp_at_u = True
                            break
                
                if not found_tp_at_u:
                    events.append(("REVERSAL", u, curr_route_pos, curr_track_dir, 0))
            
            # TPs on this track (Deduplication Logic)
            # 1. Collect all candidates
            candidates = []

            for tp in tps_by_track.get(tid, []):
                if track.length_m <= 0:
                    continue
                if tp.target_node_id == track.target:
                    pct_from_source = (track.length_m - tp.distance_to_target_m) / track.length_m
                else:
                    pct_from_source = tp.distance_to_target_m / track.length_m

                lo = min(s_pct, e_pct) - 1e-6
                hi = max(s_pct, e_pct) + 1e-6
                if pct_from_source < lo or pct_from_source > hi:
                    continue

                local_pos = abs(pct_from_source - s_pct) * track.length_m
                candidates.append((local_pos, tp))

            # 2. Group by position (epsilon 0.1m)
            candidates.sort(key=lambda x: (x[0], x[1].id))
            grouped_candidates = []
            if candidates:
                current_group = [candidates[0]]
                for i in range(1, len(candidates)):
                    pos, tp = candidates[i]
                    last_pos, last_tp = current_group[-1]
                    if abs(pos - last_pos) < 0.1:
                        current_group.append((pos, tp))
                    else:
                        grouped_candidates.append(current_group)
                        current_group = [(pos, tp)]
                grouped_candidates.append(current_group)
            
            # 3. Select representative for each group
            track_tps = []
            for group in grouped_candidates:
                selected_tp = None
                selected_pos = group[0][0] # Use position of first element

                # Keep user-selected route TPs stable when multiple IDs share a position.
                selected_members = [
                    (selected_tp_rank[tp.id], pos, tp)
                    for pos, tp in group
                    if tp.id in selected_tp_rank
                ]
                if selected_members:
                    selected_members.sort(key=lambda x: x[0])
                    _rank, selected_pos, selected_tp = selected_members[0]
                    track_tps.append(("TP", selected_tp, curr_route_pos + selected_pos, curr_track_dir))
                    continue
                
                # Priority: target == track.target, with deterministic TP-ID tie-break.
                preferred = [(pos, tp) for pos, tp in group if tp.target_node_id == track.target]
                if preferred:
                    preferred.sort(key=lambda x: x[1].id)
                    selected_pos, selected_tp = preferred[0]
                
                if selected_tp is None:
                    # Fallback: deterministic lowest TP ID in the co-located group.
                    fallback = sorted(group, key=lambda x: x[1].id)[0]
                    selected_pos, selected_tp = fallback
                
                track_tps.append(("TP", selected_tp, curr_route_pos + selected_pos, curr_track_dir))

            track_tps.sort(key=lambda x: x[2])
            # Carry each TP's own segment profile id.
            # Event shape: ("TP", tp, abs_pos, track_dir, segment_profile_id)
            track_tps_aug = [t + (t[1].segment_profile_id,) for t in track_tps]

            if events and track_tps_aug and events[-1][0] == "TP":
                prev_tp = events[-1][1]
                prev_pos = events[-1][2]
                first_tp = track_tps_aug[0][1]
                first_pos = track_tps_aug[0][2]
                if first_tp.id == prev_tp.id and abs(first_pos - prev_pos) < 0.1:
                    track_tps_aug = track_tps_aug[1:]
            
            events.extend(track_tps_aug)
            
            curr_route_pos += abs(e_pct - s_pct) * track.length_m
            
            last_track_dir = curr_track_dir

        # Ensure we simulate until the very end of the route
        if not events or events[-1][2] < curr_route_pos - 0.1:
            events.append(("END", None, curr_route_pos, last_track_dir, 0))

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
        
        # Start simulation at the first event's position
        last_pos = events[0][2] if events else 0.0
        
        # Identify the index of the last TP for endOfJourney flag
        last_tp_index = -1
        for j in range(len(events) - 1, -1, -1):
            if events[j][0] == "TP":
                last_tp_index = j
                break

        # Identify all stop positions for look-ahead braking
        stop_positions = []
        for i, event in enumerate(events):
            # Unpack event (handle potential 4 or 5 items for robustness, though we aim for 5)
            if len(event) == 5:
                etype, edata, abs_pos, edir, forced_seg_id = event
            else:
                etype, edata, abs_pos, edir = event
                forced_seg_id = 0

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

        for i, event in enumerate(events):
            if len(event) == 5:
                etype, edata, abs_pos, edir, forced_seg_id = event
            else:
                etype, edata, abs_pos, edir = event
                forced_seg_id = 0

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
                
                # Start a new profile segment whenever segment id or direction changes.
                if not profile_segments or \
                   profile_segments[-1]["segmentProfileId"] != forced_seg_id or \
                   profile_segments[-1]["direction"] != edir:
                    profile_segments.append({
                        "countryId": 0,
                        "segmentProfileId": forced_seg_id,
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
            "generatorRouteSelection": {
                "startTimingPointId": selection.start_tp_id,
                "endTimingPointId": selection.end_tp_id,
                "waypointTimingPointIds": list(selection.waypoint_tp_ids),
            },
            "generatorTimingConstraints": [
                {
                    "timingPointId": int(tp_id),
                    "pointType": str(constraint.get("pointType", "STOP")),
                    "arrivalTime": str(constraint.get("arrivalTime", "") or ""),
                    "departureTime": str(constraint.get("departureTime", "") or ""),
                }
                for tp_id, constraint in sorted(selection.timing_constraints.items(), key=lambda x: int(x[0]))
                if isinstance(constraint, dict)
            ],
            "segmentProfileReferences": profile_segments
        }
        
        return profile

    def export_to_file(self, file_path: str, parameters: Dict[str, Any]):
        data = self.export_journey_profile(parameters)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
