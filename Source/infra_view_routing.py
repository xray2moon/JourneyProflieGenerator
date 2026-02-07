from __future__ import annotations

import heapq
from typing import Dict, List, Optional, Tuple

from PyQt6.QtWidgets import QMessageBox


class InfrastructureViewRouting:
    MIN_REVERSAL_TP_CLEARANCE_M = 50.0

    def __init__(self, view):
        self._view = view

    def __getattr__(self, name):
        return getattr(self._view, name)

    def _is_transition_allowed(self, node_id: str, incoming_track_id: Optional[str], outgoing_track_id: str) -> bool:
        """
        Returns whether we may switch from incoming_track_id to outgoing_track_id at node_id.
        """
        model = self._backend.model
        if incoming_track_id is None:
            return True
        allowed = model.simple_point_connections.get(node_id)
        if not allowed:
            return True
        if incoming_track_id == outgoing_track_id:
            return True
        res = frozenset((incoming_track_id, outgoing_track_id)) in allowed
        return res

    def _build_graph(self) -> None:
        """
        Undirected graph (physical tracks) with edge weight = track length.
        """
        model = self._backend.model
        self._graph = {nid: [] for nid in model.nodes.keys()}
        edge_count = 0
        for tr in model.tracks.values():
            if tr.source not in model.nodes or tr.target not in model.nodes:
                continue
            w = tr.length_m if tr.length_m > 0 else 1.0
            self._graph[tr.source].append((tr.target, tr.id, w))
            self._graph[tr.target].append((tr.source, tr.id, w))
            edge_count += 1
        print(f"DEBUG: Graph built with {len(self._graph)} nodes and {edge_count} edges.", flush=True)

    def _shortest_path(
        self,
        start: str,
        goal: str,
        *, 
        start_incoming_track_id: Optional[str] = None
    ) -> Tuple[List[str], List[str], float]:
        """
        Dijkstra over (node, incomingTrack) states, returning (node_path, track_path, distance).
        node_path includes both endpoints.
        """
        if start == goal:
            return [start], [], 0.0

        start_state = (start, start_incoming_track_id)  # (nodeId, incomingTrackId)
        dist: Dict[Tuple[str, Optional[str]], float] = {start_state: 0.0}
        prev: Dict[Tuple[str, Optional[str]], Tuple[Tuple[str, Optional[str]], str]] = {}
        pq = [(0.0, start_state)]
        seen = set()
        end_state: Optional[Tuple[str, Optional[str]]] = None

        while pq:
            d, state = heapq.heappop(pq)
            if state in seen:
                continue
            seen.add(state)
            u, incoming_track_id = state
            if u == goal:
                end_state = state
                break
            for v, track_id, w in self._graph.get(u, []):
                if not self._is_transition_allowed(u, incoming_track_id, track_id):
                    continue
                nd = d + w
                nxt = (v, track_id)
                if nd < dist.get(nxt, float("inf")):
                    dist[nxt] = nd
                    prev[nxt] = (state, track_id)
                    heapq.heappush(pq, (nd, nxt))

        if end_state is None:
            return [start], [], float("inf")

        # reconstruct
        nodes: List[str] = [goal]
        tracks: List[str] = []
        cur = end_state
        total_dist = dist[end_state]
        while cur != start_state:
            pstate, tr_id = prev[cur]
            tracks.append(tr_id)
            nodes.append(pstate[0])
            cur = pstate
        nodes.reverse()
        tracks.reverse()
        return nodes, tracks, total_dist

    def _tp_position_from_source(self, tp, track) -> float:
        if tp.target_node_id == track.target:
            return track.length_m - tp.distance_to_target_m
        return tp.distance_to_target_m

    def _is_tp_suitable_reversal_point(self, tp, track) -> bool:
        if track.length_m <= 0:
            return False
        pos = self._tp_position_from_source(tp, track)
        clearance = min(pos, track.length_m - pos)
        return clearance >= self.MIN_REVERSAL_TP_CLEARANCE_M

    def _can_reach_goal_tp_after_reversal(
        self,
        turn_node_id: str,
        *,
        incoming_track_id: Optional[str],
        goal_tp_id: Optional[int],
    ) -> bool:
        """
        Validate that, after returning to turn_node_id from a reversal TP, the route
        can still continue to goal_tp_id while respecting point connections.
        """
        if goal_tp_id is None:
            return True

        model = self._backend.model
        goal_tp = model.timing_points.get(goal_tp_id)
        if goal_tp is None:
            return False

        e_tr = model.tracks.get(goal_tp.track_id)
        if e_tr is None:
            return False

        g_v = goal_tp.target_node_id
        g_u = e_tr.source if g_v == e_tr.target else e_tr.target

        path_a_nodes, path_a_tracks, dist_a = self._shortest_path(
            turn_node_id,
            g_u,
            start_incoming_track_id=incoming_track_id,
        )
        if (
            dist_a != float("inf")
            and self._entry_transition_ok(g_u, path_a_tracks, incoming_track_id, e_tr.id)
            and path_a_nodes
        ):
            return True

        path_b_nodes, path_b_tracks, dist_b = self._shortest_path(
            turn_node_id,
            g_v,
            start_incoming_track_id=incoming_track_id,
        )
        return (
            dist_b != float("inf")
            and self._entry_transition_ok(g_v, path_b_tracks, incoming_track_id, e_tr.id)
            and bool(path_b_nodes)
        )

    def _find_nearest_reversal_tp_after_node(
        self,
        node_id: str,
        *,
        incoming_track_id: Optional[str],
        goal_tp_id: Optional[int] = None,
        turn_anchor_node_id: Optional[str] = None,
        excluded_tp_ids: set[int],
    ) -> Optional[int]:
        """
        Find the nearest TP where we can reverse safely after passing node_id.
        Candidate constraints:
        - TP clearance must be >= MIN_REVERSAL_TP_CLEARANCE_M from both segment ends.
        - Candidate must be reachable from node_id with current incoming_track_id.
        - Candidate path must depart node_id on a track different from incoming_track_id.
        - Reversing at the candidate must still allow reaching goal_tp_id.
        """
        model = self._backend.model
        if node_id not in model.nodes:
            return None

        tps_by_track: Dict[str, List[object]] = {}
        for tp in model.timing_points.values():
            if tp.id in excluded_tp_ids:
                continue
            tr = model.tracks.get(tp.track_id)
            if tr is None:
                continue
            if not self._is_tp_suitable_reversal_point(tp, tr):
                continue
            tps_by_track.setdefault(tp.track_id, []).append(tp)

        if not tps_by_track:
            return None

        # Prefer reversal points on the turn segment first when they remain valid
        # for reaching the requested goal TP.
        if incoming_track_id is not None:
            tr_in = model.tracks.get(incoming_track_id)
            if tr_in is not None:
                anchor_node_id = node_id
                if turn_anchor_node_id in {tr_in.source, tr_in.target}:
                    anchor_node_id = turn_anchor_node_id

                local_goal_ok = self._can_reach_goal_tp_after_reversal(
                    node_id,
                    incoming_track_id=incoming_track_id,
                    goal_tp_id=goal_tp_id,
                )
                if local_goal_ok:
                    local_candidates: List[Tuple[float, int, int]] = []
                    for tp in tps_by_track.get(incoming_track_id, []):
                        pos = self._tp_position_from_source(tp, tr_in)
                        if anchor_node_id == tr_in.source:
                            dist_to_tp = pos
                        elif anchor_node_id == tr_in.target:
                            dist_to_tp = tr_in.length_m - pos
                        else:
                            continue
                        if dist_to_tp < 0 or dist_to_tp > tr_in.length_m:
                            continue
                        prefer_anchor_facing = 0 if tp.target_node_id == anchor_node_id else 1
                        local_candidates.append((dist_to_tp, prefer_anchor_facing, tp.id))
                    if local_candidates:
                        local_candidates.sort(key=lambda x: (x[0], x[1], x[2]))
                        return local_candidates[0][2]

        # Explore outward from turn node and score TP distance along reachable track geometry.
        # We keep first_departure_track_id so we can validate post-reversal reachability to goal.
        start_state = (node_id, incoming_track_id, None)
        pq: List[Tuple[float, str, Optional[str], Optional[str]]] = [
            (0.0, node_id, incoming_track_id, None)
        ]
        dist: Dict[Tuple[str, Optional[str], Optional[str]], float] = {start_state: 0.0}
        seen: set[Tuple[str, Optional[str], Optional[str]]] = set()
        can_reach_goal_cache: Dict[Optional[str], bool] = {}
        best: Tuple[float, int] | None = None

        while pq:
            d, u, incoming, first_departure_track_id = heapq.heappop(pq)
            state = (u, incoming, first_departure_track_id)
            if state in seen:
                continue
            seen.add(state)

            if best is not None and d >= best[0]:
                continue

            for v, track_id, w in self._graph.get(u, []):
                if not self._is_transition_allowed(u, incoming, track_id):
                    continue

                tr = model.tracks.get(track_id)
                first_out_track_id = first_departure_track_id or track_id
                if incoming_track_id is not None and first_out_track_id == incoming_track_id:
                    # Prevent "reversal points" that still require turning on the same
                    # segment at node_id.
                    continue

                if tr is not None:
                    for tp in tps_by_track.get(track_id, []):
                        pos = self._tp_position_from_source(tp, tr)
                        if u == tr.source:
                            dist_to_tp = pos
                        elif u == tr.target:
                            dist_to_tp = tr.length_m - pos
                        else:
                            continue
                        if dist_to_tp < 0 or dist_to_tp > w:
                            continue

                        can_reach_goal = can_reach_goal_cache.get(first_out_track_id)
                        if can_reach_goal is None:
                            can_reach_goal = self._can_reach_goal_tp_after_reversal(
                                node_id,
                                incoming_track_id=first_out_track_id,
                                goal_tp_id=goal_tp_id,
                            )
                            can_reach_goal_cache[first_out_track_id] = can_reach_goal
                        if not can_reach_goal:
                            continue

                        cand = d + dist_to_tp
                        if best is None or cand < best[0]:
                            best = (cand, tp.id)

                nd = d + w
                nxt_state = (v, track_id, first_out_track_id)
                if nd < dist.get(nxt_state, float("inf")):
                    dist[nxt_state] = nd
                    heapq.heappush(pq, (nd, v, track_id, first_out_track_id))

        return best[1] if best else None

    def _ordered_selected_targets(self) -> List[int]:
        selection = self._backend.selection
        start_tp_id = selection.start_tp_id
        end_tp_id = selection.end_tp_id
        ordered: List[int] = []
        for w in selection.waypoint_tp_ids:
            if start_tp_id is not None and w == start_tp_id:
                continue
            if w not in ordered:
                ordered.append(w)
        if end_tp_id is not None and (start_tp_id is None or end_tp_id != start_tp_id):
            if end_tp_id not in ordered:
                ordered.append(end_tp_id)
        return ordered

    def _mark_tp_as_stop_constraint(self, tp_id: int) -> None:
        model = self._backend.model
        selection = self._backend.selection
        tp = model.timing_points.get(tp_id)
        if tp is None:
            return

        existing = selection.timing_constraints.get(tp_id, {})
        constraint = {
            "timingPointId": tp_id,
            "trackId": tp.track_id,
            "targetNodeId": tp.target_node_id,
            "distanceToTargetNodeInMeters": tp.distance_to_target_m,
            "pointType": "STOP",
            "arrivalTime": existing.get("arrivalTime"),
            "departureTime": existing.get("departureTime"),
        }
        selection.set_timing_constraint(tp_id, constraint)

    def _find_node_uturn(self, route_nodes: List[str], route_tracks: List[str]) -> Optional[Tuple[str, str]]:
        """
        Detect immediate backtrack over same track: n[i] -> n[i+1] -> n[i] on identical track ids.
        Returns (turn_node_id, incoming_track_id) for first occurrence.
        """
        if len(route_tracks) < 2 or len(route_nodes) < 3:
            return None
        for i in range(len(route_tracks) - 1):
            if route_tracks[i] != route_tracks[i + 1]:
                continue
            if i + 2 >= len(route_nodes):
                continue
            if route_nodes[i] == route_nodes[i + 2]:
                return route_nodes[i + 1], route_tracks[i]
        return None

    def _entry_transition_ok(
        self,
        entry_node_id: str,
        entry_path_tracks: List[str],
        fallback_incoming_track_id: Optional[str],
        desired_outgoing_track_id: str,
    ) -> bool:
        incoming = entry_path_tracks[-1] if entry_path_tracks else fallback_incoming_track_id
        return self._is_transition_allowed(entry_node_id, incoming, desired_outgoing_track_id)

    def _extend_route_with_node(self, node_id: str) -> None:
        model = self._backend.model
        selection = self._backend.selection
        if node_id not in model.nodes:
            return

        current_route = list(selection.current_route)
        current_tracks = list(selection.current_tracks)

        if not current_route:
            selection.set_route([node_id], [])
        else:
            last = current_route[-1]
            incoming = current_tracks[-1] if current_tracks else None
            node_path, track_path, dist = self._shortest_path(last, node_id, start_incoming_track_id=incoming)
            
            if dist == float("inf"):
                res = QMessageBox.question(
                    self._view,
                    "Node not reachable",
                    "The selected node is not reachable from the current route end "
                    "(considering simple point connections).\n\n"
                    "Start a new route at the selected node?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if res == QMessageBox.StandardButton.Yes:
                    selection.set_route([node_id], [])
                return
            
            # append, skipping the first because it's last
            new_nodes = current_route + node_path[1:]
            new_tracks = current_tracks + track_path
            selection.set_route(new_nodes, new_tracks)

    def _replay_tp_sequence(self, start_tp_id: int, ordered_targets: List[int]) -> bool:
        selection = self._backend.selection
        old_route = list(selection.current_route)
        old_tracks = list(selection.current_tracks)
        old_start = selection.start_tp_id
        old_end = selection.end_tp_id
        old_waypoints = list(selection.waypoint_tp_ids)

        setattr(self, "_replaying_tp_sequence", True)
        try:
            selection.clear_selection()
            selection.set_start_tp(start_tp_id)
            for target_tp_id in ordered_targets:
                self._extend_route_with_tp(target_tp_id)
                if selection.end_tp_id != target_tp_id:
                    selection.set_route(old_route, old_tracks)
                    selection.set_start_tp(old_start)
                    selection.set_end_tp(old_end)
                    selection.set_waypoint_tp_ids(old_waypoints)
                    QMessageBox.warning(
                        self._view,
                        "Waypoint not reachable",
                        f"Could not insert timing point {target_tp_id} into the current route order.",
                    )
                    return False
            final_end = ordered_targets[-1] if ordered_targets else None
            waypoint_ids: List[int] = []
            for tp_id in ordered_targets[:-1]:
                if tp_id in {start_tp_id, final_end}:
                    continue
                if tp_id not in waypoint_ids:
                    waypoint_ids.append(tp_id)
            selection.set_waypoint_tp_ids(waypoint_ids)
            return True
        finally:
            setattr(self, "_replaying_tp_sequence", False)

    def _extend_route_with_tp(self, tp_id: int) -> None:
        model = self._backend.model
        selection = self._backend.selection
        tp = model.timing_points.get(tp_id)
        if not tp:
            return

        print(f"DEBUG: _extend_route_with_tp called for TP {tp_id}", flush=True)
        current_route = list(selection.current_route)
        current_tracks = list(selection.current_tracks)
        start_tp_id = selection.start_tp_id
        end_tp_id = selection.end_tp_id
        replay_mode = bool(getattr(self, "_replaying_tp_sequence", False))

        if start_tp_id is None:
            print(f"DEBUG: No start TP set. Setting start TP to {tp_id}", flush=True)
            selection.clear_selection()
            selection.set_start_tp(tp_id)
            selection.set_waypoint_tp_ids([])
            return

        if not current_route:
            if tp_id == start_tp_id:
                return
            
            start_tp = model.timing_points.get(start_tp_id)
            if not start_tp: 
                selection.set_start_tp(tp_id)
                return
            
            s_tr = model.tracks.get(start_tp.track_id)
            e_tr = model.tracks.get(tp.track_id)
            if not s_tr or not e_tr: return

            # Evaluate both directions from start TP
            vA = start_tp.target_node_id
            uA = s_tr.source if vA == s_tr.target else s_tr.target
            dA = start_tp.distance_to_target_m
            
            vB = uA
            uB = vA
            dB = s_tr.length_m - dA

            g_v = tp.target_node_id
            g_u = e_tr.source if g_v == e_tr.target else e_tr.target
            
            # Goal Entry Options: Enter via g_u or g_v
            # Combination 1: Exit vA, Enter g_u
            path1_nodes, path1_tracks, dist1 = self._shortest_path(vA, g_u, start_incoming_track_id=s_tr.id)
            cost1 = dA + dist1 + (e_tr.length_m - tp.distance_to_target_m)
            if dist1 == float("inf") or not self._entry_transition_ok(g_u, path1_tracks, s_tr.id, e_tr.id):
                cost1 = float("inf")

            # Combination 2: Exit vB, Enter g_u
            path2_nodes, path2_tracks, dist2 = self._shortest_path(vB, g_u, start_incoming_track_id=s_tr.id)
            cost2 = dB + dist2 + (e_tr.length_m - tp.distance_to_target_m)
            if dist2 == float("inf") or not self._entry_transition_ok(g_u, path2_tracks, s_tr.id, e_tr.id):
                cost2 = float("inf")

            # Combination 3: Exit vA, Enter g_v
            path3_nodes, path3_tracks, dist3 = self._shortest_path(vA, g_v, start_incoming_track_id=s_tr.id)
            cost3 = dA + dist3 + tp.distance_to_target_m
            if dist3 == float("inf") or not self._entry_transition_ok(g_v, path3_tracks, s_tr.id, e_tr.id):
                cost3 = float("inf")

            # Combination 4: Exit vB, Enter g_v
            path4_nodes, path4_tracks, dist4 = self._shortest_path(vB, g_v, start_incoming_track_id=s_tr.id)
            cost4 = dB + dist4 + tp.distance_to_target_m
            if dist4 == float("inf") or not self._entry_transition_ok(g_v, path4_tracks, s_tr.id, e_tr.id):
                cost4 = float("inf")

            options = [
                (cost1, [uA, vA] + path1_nodes[1:] + [g_v], [s_tr.id] + path1_tracks + [e_tr.id]),
                (cost2, [uB, vB] + path2_nodes[1:] + [g_v], [s_tr.id] + path2_tracks + [e_tr.id]),
                (cost3, [uA, vA] + path3_nodes[1:] + [g_u], [s_tr.id] + path3_tracks + [e_tr.id]),
                (cost4, [uB, vB] + path4_nodes[1:] + [g_u], [s_tr.id] + path4_tracks + [e_tr.id]),
            ]
            
            reachable = [opt for opt in options if opt[0] < float("inf")]

            # Special case same track
            if s_tr.id == e_tr.id:
                pos_start = (s_tr.length_m - start_tp.distance_to_target_m) if start_tp.target_node_id == s_tr.target else start_tp.distance_to_target_m
                pos_end_fwd = (e_tr.length_m - tp.distance_to_target_m) if tp.target_node_id == e_tr.target else tp.distance_to_target_m
                pos_end_bwd = tp.distance_to_target_m if tp.target_node_id == e_tr.target else (e_tr.length_m - tp.distance_to_target_m)
                
                if pos_end_fwd >= pos_start:
                    reachable.append((pos_end_fwd - pos_start, [s_tr.source, s_tr.target], [s_tr.id]))
                
                pos_start_inv = s_tr.length_m - pos_start
                if pos_end_bwd >= pos_start_inv:
                    reachable.append((pos_end_bwd - pos_start_inv, [s_tr.target, s_tr.source], [s_tr.id]))

            if not reachable:
                selection.clear_selection()
                selection.set_start_tp(tp_id)
                return

            best_cost, best_nodes, best_tracks = min(reachable, key=lambda x: x[0])

            # First TP extension can also create a node U-turn; enforce reversal TP rule here too.
            uturn = self._find_node_uturn(best_nodes, best_tracks)
            if uturn is not None and not replay_mode and start_tp_id is not None:
                turn_node, incoming_track = uturn
                reversal_tp_id = self._find_nearest_reversal_tp_after_node(
                    turn_node,
                    incoming_track_id=incoming_track,
                    goal_tp_id=tp_id,
                    turn_anchor_node_id=tp.target_node_id,
                    excluded_tp_ids={tp_id, start_tp_id},
                )
                if reversal_tp_id is not None:
                    print(
                        f"DEBUG: inserting reversal TP {reversal_tp_id} before TP {tp_id} (turn node {turn_node})",
                        flush=True,
                    )
                    if self._replay_tp_sequence(start_tp_id, [reversal_tp_id, tp_id]):
                        self._mark_tp_as_stop_constraint(reversal_tp_id)
                        return
                else:
                    print(
                        f"DEBUG: no suitable reversal TP found after node {turn_node}; keeping direct route",
                        flush=True,
                    )

            selection.set_route(best_nodes, best_tracks)
            selection.set_end_tp(tp_id)
            if not replay_mode:
                selection.set_waypoint_tp_ids([])
        else:
            if tp_id == end_tp_id:
                return

            previous_end_tp_id = end_tp_id

            e_tr = model.tracks.get(tp.track_id)
            if not e_tr: return

            previous_end_tp = model.timing_points.get(previous_end_tp_id) if previous_end_tp_id is not None else None
            can_continue_on_last_traversal = False
            if (
                previous_end_tp is not None
                and previous_end_tp.track_id == tp.track_id
                and current_tracks
                and current_tracks[-1] == tp.track_id
                and len(current_route) >= 2
            ):
                prev_pos = self._tp_position_from_source(previous_end_tp, e_tr)
                next_pos = self._tp_position_from_source(tp, e_tr)
                last_u = current_route[-2]
                last_v = current_route[-1]
                if last_u == e_tr.source and last_v == e_tr.target:
                    can_continue_on_last_traversal = next_pos >= prev_pos
                elif last_u == e_tr.target and last_v == e_tr.source:
                    can_continue_on_last_traversal = next_pos <= prev_pos

            if can_continue_on_last_traversal:
                selection.set_end_tp(tp_id)
                if not replay_mode:
                    waypoint_tp_ids = [
                        w for w in selection.waypoint_tp_ids
                        if w not in {start_tp_id, tp_id}
                    ]
                    if previous_end_tp_id is not None and previous_end_tp_id not in {start_tp_id, tp_id}:
                        if previous_end_tp_id not in waypoint_tp_ids:
                            waypoint_tp_ids.append(previous_end_tp_id)
                    selection.set_waypoint_tp_ids(waypoint_tp_ids)
                return
            
            last_node = current_route[-1]
            last_track = current_tracks[-1] if current_tracks else None

            g_v = tp.target_node_id
            g_u = e_tr.source if g_v == e_tr.target else e_tr.target

            # Option A: Enter via g_u
            pathA_nodes, pathA_tracks, distA = self._shortest_path(last_node, g_u, start_incoming_track_id=last_track)
            costA = distA + (e_tr.length_m - tp.distance_to_target_m)
            if distA == float("inf") or not self._entry_transition_ok(g_u, pathA_tracks, last_track, e_tr.id):
                costA = float("inf")

            # Option B: Enter via g_v
            pathB_nodes, pathB_tracks, distB = self._shortest_path(last_node, g_v, start_incoming_track_id=last_track)
            costB = distB + tp.distance_to_target_m
            if distB == float("inf") or not self._entry_transition_ok(g_v, pathB_tracks, last_track, e_tr.id):
                costB = float("inf")

            if costA <= costB and distA != float("inf"):
                new_nodes = current_route + pathA_nodes[1:] + [g_v]
                new_tracks = current_tracks + pathA_tracks + [e_tr.id]
            elif distB != float("inf"):
                new_nodes = current_route + pathB_nodes[1:] + [g_u]
                new_tracks = current_tracks + pathB_tracks + [e_tr.id]
            else:
                selection.clear_selection()
                selection.set_start_tp(tp_id)
                return

            # Avoid reversing direction exactly on a node (same track traversed back-to-back).
            # Insert a valid reversal TP (>=50 m from both nodes) past that node and replay.
            extension_nodes = new_nodes[len(current_route) - 1:] if current_route else new_nodes
            extension_tracks = new_tracks[len(current_tracks):]
            uturn = self._find_node_uturn(extension_nodes, extension_tracks)
            if uturn is not None and not replay_mode and start_tp_id is not None:
                turn_node, incoming_track = uturn
                reversal_tp_id = self._find_nearest_reversal_tp_after_node(
                    turn_node,
                    incoming_track_id=incoming_track,
                    goal_tp_id=tp_id,
                    turn_anchor_node_id=tp.target_node_id,
                    excluded_tp_ids={tp_id, start_tp_id, *(selection.waypoint_tp_ids or [])},
                )
                if reversal_tp_id is not None:
                    print(
                        f"DEBUG: inserting reversal TP {reversal_tp_id} before TP {tp_id} (turn node {turn_node})",
                        flush=True,
                    )
                    ordered_targets = [t for t in self._ordered_selected_targets() if t != tp_id]
                    if reversal_tp_id not in ordered_targets:
                        ordered_targets.append(reversal_tp_id)
                    ordered_targets.append(tp_id)
                    if self._replay_tp_sequence(start_tp_id, ordered_targets):
                        self._mark_tp_as_stop_constraint(reversal_tp_id)
                        return
                else:
                    print(
                        f"DEBUG: no suitable reversal TP found after node {turn_node}; keeping direct route",
                        flush=True,
                    )
            
            selection.set_route(new_nodes, new_tracks)
            selection.set_end_tp(tp_id)
            if not replay_mode:
                waypoint_tp_ids = [
                    w for w in selection.waypoint_tp_ids
                    if w not in {start_tp_id, tp_id}
                ]
                if previous_end_tp_id is not None and previous_end_tp_id not in {start_tp_id, tp_id}:
                    if previous_end_tp_id not in waypoint_tp_ids:
                        waypoint_tp_ids.append(previous_end_tp_id)
                selection.set_waypoint_tp_ids(waypoint_tp_ids)
