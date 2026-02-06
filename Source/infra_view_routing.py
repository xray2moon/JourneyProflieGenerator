from __future__ import annotations

import heapq
from typing import Dict, List, Optional, Tuple

from PyQt6.QtWidgets import QMessageBox


class InfrastructureViewRoutingMixin:
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
        if not res:
            print(f"DEBUG: Transition NOT allowed at {node_id}: {incoming_track_id} -> {outgoing_track_id}", flush=True)
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
                    self,
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

        if start_tp_id is None:
            print(f"DEBUG: No start TP set. Setting start TP to {tp_id}", flush=True)
            selection.clear_selection()
            selection.set_start_tp(tp_id)
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

            # Combination 2: Exit vB, Enter g_u
            path2_nodes, path2_tracks, dist2 = self._shortest_path(vB, g_u, start_incoming_track_id=s_tr.id)
            cost2 = dB + dist2 + (e_tr.length_m - tp.distance_to_target_m)

            # Combination 3: Exit vA, Enter g_v
            path3_nodes, path3_tracks, dist3 = self._shortest_path(vA, g_v, start_incoming_track_id=s_tr.id)
            cost3 = dA + dist3 + tp.distance_to_target_m

            # Combination 4: Exit vB, Enter g_v
            path4_nodes, path4_tracks, dist4 = self._shortest_path(vB, g_v, start_incoming_track_id=s_tr.id)
            cost4 = dB + dist4 + tp.distance_to_target_m

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
            selection.set_route(best_nodes, best_tracks)
            selection.set_end_tp(tp_id)
        else:
            if current_tracks and tp.track_id == current_tracks[-1]:
                selection.set_end_tp(tp_id)
                return

            e_tr = model.tracks.get(tp.track_id)
            if not e_tr: return
            
            last_node = current_route[-1]
            last_track = current_tracks[-1] if current_tracks else None

            g_v = tp.target_node_id
            g_u = e_tr.source if g_v == e_tr.target else e_tr.target

            # Option A: Enter via g_u
            pathA_nodes, pathA_tracks, distA = self._shortest_path(last_node, g_u, start_incoming_track_id=last_track)
            costA = distA + (e_tr.length_m - tp.distance_to_target_m)

            # Option B: Enter via g_v
            pathB_nodes, pathB_tracks, distB = self._shortest_path(last_node, g_v, start_incoming_track_id=last_track)
            costB = distB + tp.distance_to_target_m

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
            
            selection.set_route(new_nodes, new_tracks)
            selection.set_end_tp(tp_id)