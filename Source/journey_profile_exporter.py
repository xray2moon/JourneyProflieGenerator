from __future__ import annotations
import json
import uuid
from datetime import datetime, time, timedelta, timezone
from typing import Dict, List, Any, Optional
from Source.infra_backend import InfrastructureBackend
from Source.dynamics import TrainState, simulate_travel, train_data
from Source.infra_models import TimingPoint

class JourneyProfileExporter:
    """
    Exports the current state (route, timing constraints, parameters)
    to a Journey Profile JSON file matching story3-initial-journeyprofile1.json style.
    """
    ARRIVAL_TOLERANCE_S = 1.0

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
            # Anchor clipping at the reversal TP (tp_b), not tp_a.
            # This preserves both directional traversals around a same-track reversal
            # so mirrored TP IDs (e.g. 216/259) can both appear when physically passed.
            ranges[i_prev] = (s_prev, pct_b)

            _, e_next = ranges[i_next]
            ranges[i_next] = (pct_b, e_next)
            search_from = i_next

        return ranges

    def _is_tp_stop_event(
        self,
        *,
        tp: TimingPoint,
        event_index: int,
        last_tp_index: int,
        reversal_tp_ids: set[int],
    ) -> bool:
        selection = self._backend.selection
        if event_index == last_tp_index:
            return True
        if tp.id in reversal_tp_ids:
            return True
        user_c = selection.timing_constraints.get(tp.id)
        if isinstance(user_c, dict):
            return str(user_c.get("pointType", "")).upper() == "STOP"
        return False

    @staticmethod
    def _parse_constraint_clock_time(
        tp_id: int,
        field_name: str,
        raw_value: Any,
    ) -> Optional[time]:
        text = str(raw_value or "").strip()
        if not text:
            return None
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(text, fmt).time()
            except ValueError:
                continue
        raise ValueError(
            f"Invalid {field_name} for TP {tp_id}: '{text}'. Use HH:MM or HH:MM:SS."
        )

    @staticmethod
    def _apply_user_clock_time(
        *,
        baseline: datetime,
        user_clock_time: time,
        tp_id: int,
        field_name: str,
    ) -> datetime:
        candidate = datetime.combine(
            baseline.date(),
            user_clock_time,
        ).replace(tzinfo=baseline.tzinfo)
        if candidate < baseline:
            raise ValueError(
                "Invalid route time order: "
                f"{field_name} for TP {tp_id} ({candidate.strftime('%H:%M:%S')}) "
                f"is earlier than prior event time ({baseline.strftime('%H:%M:%S')})."
            )
        return candidate

    @staticmethod
    def _parse_start_time(raw_value: Any) -> datetime:
        text = str(raw_value or "").strip()
        if not text:
            return datetime.now(timezone.utc)

        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass

        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                t = datetime.strptime(text, fmt).time()
                now_utc = datetime.now(timezone.utc)
                return datetime.combine(now_utc.date(), t).replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        raise ValueError(
            "Invalid startTime format. Use ISO datetime "
            "(e.g. 2026-03-01T08:30:00Z) or HH:MM / HH:MM:SS."
        )

    @staticmethod
    def _clone_train_state(state: TrainState) -> TrainState:
        return TrainState(
            velocity=float(state.velocity),
            elapsed_time=float(state.elapsed_time),
            total_distance=float(state.total_distance),
            accel_idx=int(state.accel_idx),
            decel_idx=int(state.decel_idx),
            braking_triggered=bool(state.braking_triggered),
        )

    def _simulate_leg_time(
        self,
        *,
        train_type: str,
        distance: float,
        start_state: TrainState,
        distance_to_stop: float,
        speed_restriction: float,
    ) -> float:
        probe = self._clone_train_state(start_state)
        return simulate_travel(
            train_type,
            distance,
            probe,
            mode="accel",
            speed_restriction=speed_restriction,
            distance_to_stop=distance_to_stop,
        )

    def _find_speed_restriction_for_target_arrival(
        self,
        *,
        train_type: str,
        distance: float,
        start_state: TrainState,
        distance_to_stop: float,
        target_travel_s: float,
        tp_id: int,
        target_arrival: datetime,
        current_time: datetime,
    ) -> float:
        tolerance_s = self.ARRIVAL_TOLERANCE_S
        fastest_s = self._simulate_leg_time(
            train_type=train_type,
            distance=distance,
            start_state=start_state,
            distance_to_stop=distance_to_stop,
            speed_restriction=float("inf"),
        )
        slowest_s = self._simulate_leg_time(
            train_type=train_type,
            distance=distance,
            start_state=start_state,
            distance_to_stop=distance_to_stop,
            speed_restriction=0.0,
        )

        if target_travel_s < fastest_s - tolerance_s:
            earliest = current_time + timedelta(seconds=fastest_s)
            raise ValueError(
                f"Cannot reach TP {tp_id} by {target_arrival.strftime('%H:%M:%S')} by driving. "
                f"Earliest feasible arrival is {earliest.strftime('%H:%M:%S')}."
            )
        if target_travel_s > slowest_s + tolerance_s:
            latest = current_time + timedelta(seconds=slowest_s)
            raise ValueError(
                f"Cannot reach TP {tp_id} by driving as late as {target_arrival.strftime('%H:%M:%S')}. "
                f"Latest feasible arrival is {latest.strftime('%H:%M:%S')}."
            )

        if abs(target_travel_s - fastest_s) <= tolerance_s:
            return float("inf")
        if abs(target_travel_s - slowest_s) <= tolerance_s:
            return 0.0

        curve = train_data.get(train_type, train_data["S1"])
        max_restriction = float(max(curve["accel"])) if len(curve["accel"]) else 1.0
        low = 0.0
        high = max_restriction
        best_restriction = high
        best_error = abs(fastest_s - target_travel_s)

        for _ in range(40):
            mid = (low + high) / 2.0
            mid_time = self._simulate_leg_time(
                train_type=train_type,
                distance=distance,
                start_state=start_state,
                distance_to_stop=distance_to_stop,
                speed_restriction=mid,
            )
            mid_error = abs(mid_time - target_travel_s)
            if mid_error < best_error:
                best_error = mid_error
                best_restriction = mid
            if mid_error <= tolerance_s:
                return mid
            if mid_time > target_travel_s:
                low = mid
            else:
                high = mid

        if best_error <= tolerance_s:
            return best_restriction

        raise ValueError(
            f"Cannot match TP {tp_id} arrival {target_arrival.strftime('%H:%M:%S')} within "
            f"+/-{int(tolerance_s)} second by driving."
        )

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
            # Prefer TP identity that matches movement direction on this traversal.
            # On mirrored TP pairs (same physical point, opposite targetNodeId),
            # this keeps export consistent with route direction.
            preferred_target_node_id = None
            if v == track.target:
                preferred_target_node_id = track.target
            elif v == track.source:
                preferred_target_node_id = track.source
            
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
                    # Keep selected IDs only when they also match traversal direction.
                    if preferred_target_node_id is not None:
                        selected_members = [
                            item
                            for item in selected_members
                            if item[2].target_node_id == preferred_target_node_id
                        ]
                    if selected_members:
                        selected_members.sort(key=lambda x: x[0])
                        _rank, selected_pos, selected_tp = selected_members[0]
                        track_tps.append(("TP", selected_tp, curr_route_pos + selected_pos, curr_track_dir))
                        continue
                
                # Priority: target node that matches traversal direction.
                preferred = []
                if preferred_target_node_id is not None:
                    preferred = [
                        (pos, tp)
                        for pos, tp in group
                        if tp.target_node_id == preferred_target_node_id
                    ]
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
        current_time = self._parse_start_time(start_time_str)

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
                is_stop = self._is_tp_stop_event(
                    tp=tp,
                    event_index=i,
                    last_tp_index=last_tp_index,
                    reversal_tp_ids=reversal_tp_ids,
                )
            
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
                is_stop = self._is_tp_stop_event(
                    tp=tp,
                    event_index=i,
                    last_tp_index=last_tp_index,
                    reversal_tp_ids=reversal_tp_ids,
                )
            
            # Find distance to next stop for look-ahead
            next_stop_pos = float('inf')
            for sp in stop_positions:
                if sp >= abs_pos - 0.001: # Use small epsilon
                    next_stop_pos = sp
                    break
            
            distance_to_stop = next_stop_pos - last_pos

            leg_start_time = current_time
            current_user_arrival_time = None
            user_departure_time = None
            speed_restriction = float("inf")
            if etype == "TP" and tp is not None:
                user_c = selection.timing_constraints.get(tp.id)
                if isinstance(user_c, dict):
                    current_user_arrival_time = self._parse_constraint_clock_time(
                        tp.id,
                        "arrivalTime",
                        user_c.get("arrivalTime"),
                    )
                    user_departure_time = self._parse_constraint_clock_time(
                        tp.id,
                        "departureTime",
                        user_c.get("departureTime"),
                    )

            for j in range(i, len(events)):
                if len(events[j]) == 5:
                    e_j_type, e_j_data, e_j_abs_pos, _e_j_dir, _e_j_seg = events[j]
                else:
                    e_j_type, e_j_data, e_j_abs_pos, _e_j_dir = events[j]

                if e_j_type != "TP":
                    break

                tp_j = e_j_data
                target_is_stop = self._is_tp_stop_event(
                    tp=tp_j,
                    event_index=j,
                    last_tp_index=last_tp_index,
                    reversal_tp_ids=reversal_tp_ids,
                )

                user_c_j = selection.timing_constraints.get(tp_j.id)
                user_arrival_time_j = None
                if isinstance(user_c_j, dict):
                    user_arrival_time_j = self._parse_constraint_clock_time(
                        tp_j.id,
                        "arrivalTime",
                        user_c_j.get("arrivalTime"),
                    )

                if user_arrival_time_j is not None:
                    target_arrival_dt = self._apply_user_clock_time(
                        baseline=leg_start_time,
                        user_clock_time=user_arrival_time_j,
                        tp_id=tp_j.id,
                        field_name="arrivalTime",
                    )
                    target_travel_s = (target_arrival_dt - leg_start_time).total_seconds()
                    remaining_distance = max(0.0, e_j_abs_pos - last_pos)
                    target_distance_to_stop = remaining_distance if target_is_stop else float("inf")
                    speed_restriction = self._find_speed_restriction_for_target_arrival(
                        train_type=train_type,
                        distance=remaining_distance,
                        start_state=train_state,
                        distance_to_stop=target_distance_to_stop,
                        target_travel_s=target_travel_s,
                        tp_id=tp_j.id,
                        target_arrival=target_arrival_dt,
                        current_time=leg_start_time,
                    )
                    break

                if target_is_stop:
                    break

            travel_time = simulate_travel(
                train_type,
                distance_delta,
                train_state,
                mode="accel",
                speed_restriction=speed_restriction,
                distance_to_stop=distance_to_stop,
            )
            current_time += timedelta(seconds=travel_time)
            
            if etype == "TP":
                if current_user_arrival_time is not None:
                    required_arrival_dt = self._apply_user_clock_time(
                        baseline=leg_start_time,
                        user_clock_time=current_user_arrival_time,
                        tp_id=tp.id,
                        field_name="arrivalTime",
                    )
                    arrival_error = abs((current_time - required_arrival_dt).total_seconds())
                    if arrival_error > self.ARRIVAL_TOLERANCE_S:
                        raise ValueError(
                            f"TP {tp.id} arrival target {required_arrival_dt.strftime('%H:%M:%S')} "
                            f"cannot be met by driving within +/-{int(self.ARRIVAL_TOLERANCE_S)} second."
                        )

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
                    if user_departure_time is not None:
                        current_time = self._apply_user_clock_time(
                            baseline=current_time,
                            user_clock_time=user_departure_time,
                            tp_id=tp.id,
                            field_name="departureTime",
                        )
                        dep_ts_str = current_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

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
                "createdBy": "JourneyProfileGenerator",
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
