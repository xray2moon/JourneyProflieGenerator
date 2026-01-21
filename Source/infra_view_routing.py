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
        self, start: str, goal: str, *, start_incoming_track_id: Optional[str] = None
    ) -> Tuple[List[str], List[str]]:
        """
        Dijkstra over (node, incomingTrack) states, returning (node_path, track_path).
        node_path includes both endpoints.
        """
        print(f"DEBUG: Shortest path from {start} to {goal} (incoming={start_incoming_track_id})", flush=True)
        if start == goal:
            return [start], []

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
            return [start], []

        # reconstruct
        nodes: List[str] = [goal]
        tracks: List[str] = []
        cur = end_state
        while cur != start_state:
            pstate, tr_id = prev[cur]
            tracks.append(tr_id)
            nodes.append(pstate[0])
            cur = pstate
        nodes.reverse()
        tracks.reverse()
        return nodes, tracks

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
            node_path, track_path = self._shortest_path(last, node_id, start_incoming_track_id=incoming)
            
            if len(node_path) <= 1:
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