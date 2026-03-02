# Models (State & Data)

Models hold the application's runtime state, infrastructure data structures, and physical simulation logic. They are UI-agnostic and expose state changes through signals or return values used by controllers and services.

## `infra_backend.py`

### Overview/Description
Acts as the central model container for the application. It owns the currently loaded infrastructure model and the mutable selection/planning state, and exposes lifecycle operations for loading infrastructure and generating journey profiles.

### Core Functions
*   **`load_infrastructure(self, json_path: str)`**: Parses an infrastructure JSON file through `InfrastructureParser`, resets selection state, and emits `infrastructureLoaded` so the UI can rebuild from the new model.
*   **`generate_journey_profile(self, file_path: str, parameters: dict)`**: Creates an exporter instance and triggers serialization of the current planned route and constraints into a Journey Profile JSON file.
*   **`model` / `selection` properties**: Provide controlled access to the immutable infrastructure data (`model`) and mutable planning state (`selection`).

## `infra_models.py`

### Overview/Description
Defines the immutable core data structures representing railway infrastructure entities and derived schematic segments. These dataclasses form the shared domain representation used across parsing, routing, rendering, and export.

### Core Components
*   **`Node`**: Infrastructure graph node with logical ID, coordinates, and optional numeric identifier.
*   **`Track`**: Directed connection between two nodes, including shaping points and physical length.
*   **`TimingPoint`**: Operational point on a track, defined relative to a target node and linked to a segment profile.
*   **`StoppingLocation`**: Platform/stopping metadata anchored to a track and directional reference.
*   **`SchematicSegment`**: Contracted representation used in schematic/topological view modes, preserving original node/track paths.

## `infra_selection_model.py`

### Overview/Description
Stores the complete mutable planning state: route nodes/tracks, start/end/waypoint timing points, timing constraints, and timing-point visibility selection. It is signal-driven and acts as the synchronization source for UI updates.

### Core Functions
*   **`set_route(self, nodes: List[str], tracks: List[str])`**: Updates current route/tracks and emits `routeChanged` and `tracksChanged`.
*   **`set_start_tp(...)`, `set_end_tp(...)`, `set_waypoint_tp_ids(...)`**: Manage route anchor timing points and emit dedicated change signals.
*   **`set_timing_constraint(self, tp_id: int, constraint: Optional[dict])`**: Adds, updates, or removes a timing constraint and emits `timingConstraintsChanged`.
*   **`set_visible_tp_tracks(self, tracks: Set[str])`**: Controls which track timing points are currently visible in the scene.
*   **`clear_selection(self)`**: Resets route and selection-related fields to defaults and emits corresponding reset signals.
*   **`snapshot_state(self)` / `restore_state(self, state)`**: Serialize and restore full selection state for undo/redo workflows.

## `dynamics.py`

### Overview/Description
Contains the train motion simulation logic used during export to calculate realistic time progression along the route. It combines train-specific acceleration/deceleration curves with speed limits and stop-aware braking behavior.

### Core Functions
*   **`simulate_travel(...)`**: Main step-based simulation routine that advances `TrainState` over distance, switching between acceleration and deceleration based on braking requirements.
*   **`get_braking_distance(train_type: str, velocity: float)`**: Estimates required stopping distance from the deceleration curve of the selected train type.
*   **`travel_time_for_distance(...)`**: Compatibility helper that computes travel time for a fresh state over a single distance segment.
*   **`time_till_end_node(...)`**: Alias-style wrapper around `travel_time_for_distance(...)` for legacy call sites.
