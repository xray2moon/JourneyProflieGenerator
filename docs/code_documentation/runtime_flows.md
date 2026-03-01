# Runtime Flows

This page captures key end-to-end runtime flows across UI, orchestration, routing logic, and import/export boundaries.

## 1. Flow A: Load Infrastructure

1. `ParameterView` emits `infrastructureLoadRequested`.
2. `InfrastructureView.load_infrastructure(...)` calls `backend.load_infrastructure(...)`.
3. `InfrastructureParser.parse_file(...)` creates a new `InfrastructureModel`.
4. Backend emits `infrastructureLoaded`.
5. `ModelUIConnector` calls `view.on_model_updated()`.
6. Graph and scene are rebuilt, and the infrastructure summary is updated.

## 2. Flow B: Build Route via Timing Point Clicks

1. Click is captured in `infra_view_interaction.py` (`eventFilter`).
2. Interaction delegates to `infra_view_routing.py::_extend_route_with_tp(...)`.
3. Routing evaluates shortest paths (`_shortest_path(...)`) on the track graph.
4. Connection constraints and reversal safeguards are applied.
5. Selection state updates and emits route and constraint signals.
6. Frontend refreshes highlights, timing point visibility, and route labels.

## 3. Flow C: Load Journey Profile / Route

1. `ParameterView` emits `journeyProfileLoadRequested`.
2. `InfrastructureView._on_journey_profile_load_requested(...)` validates that infrastructure is already loaded.
3. `JourneyProfileImporter.load_file(...)` parses the JSON and returns:
   - replay timing point ids for route reconstruction
   - selected start/end/waypoint timing point ids
   - imported timing constraints
4. `InfrastructureView` pushes an undo snapshot and reconstructs the route via `_replay_tp_sequence(...)`.
5. Selection is updated with start/end/waypoints and imported constraints.
6. UI route highlights are refreshed and the app switches back to the Infrastructure tab.
7. A success or error dialog is shown.

## 4. Flow D: Export Journey Profile

1. `ParameterView` emits `journeyProfileGenerationRequested`.
2. `InfrastructureView` validates that a route exists and calls `backend.generate_journey_profile(...)`.
3. Backend delegates to `JourneyProfileExporter.export_to_file(...)`.
4. Exporter computes traversal ranges and timing-point/reversal event stream.
5. `dynamics.simulate_travel(...)` computes timing progression.
6. Exporter writes the final Journey Profile JSON.
