# Architecture Overview

## 1. System-Level Mental Model

At the highest level, the application has one central orchestrator and two major sides:

1. **Orchestrator**: `InfrastructureView.py`
2. **Frontend side**: user interface, rendering, and interaction handling
3. **Backend side**: infrastructure/planning state and export generation

In short:

`InfrastructureView` coordinates `Frontend` and `Backend`, while signals keep both in sync.

## 2. Coarse Component Breakdown

### 2.1 Orchestrator

`InfrastructureView.py` is the composition root and system coordinator.
It wires together backend state, scene rendering, interaction logic, settings, and import/export actions.

### 2.2 Frontend (UI + Rendering + Input)

The frontend defines how infrastructure is presented and how user actions enter the system.

`InfrastructureView.py` composes the main window and its three tabs: Infrastructure, Parameters, and Settings.

The UI building blocks (the contents in the Parameters tab, the contents in the Settings tab, popup dialogs, and the widget that contains the map) are defined in `infra_ui.py`.

The map contains visual infrastructure elements (tracks, timing points, nodes, and stopping locations) defined in `infra_items.py`. Their geometric positions are computed in `infra_view_layouts.py`, and the corresponding graphics items are instantiated and added to the scene in `infra_scene_builder.py`.

The interactions with the route are handled in `infra_view_interaction.py`, while the navigation within the map (zoom and navigation) is handled in the map widget in `infra_ui.py`.

Specific pages:

- [Views](views.md)
- [Controllers](controllers.md)

### 2.3 Backend (State + Business Logic)

The backend defines and maintains the application state and route logic.

`infra_backend.py` acts as the central backend container and brings together the loaded infrastructure model and the current planning/selection state.

`infra_selection_model.py` holds the mutable planning state (route, traversed tracks, start/end timing points, waypoints, and timing constraints).

Infrastructure data is parsed and represented through `infra_data_manager.py` and `infra_models.py`.

Route computation and validity rules (shortest-path behavior, connection constraints, and reversal safeguards) are handled in `infra_view_routing.py`.

Specific pages:

- [Models](models.md)
- [Controllers](controllers.md)

### 2.4 Boundary Services (Input/Output)

Boundary services define how data enters and leaves the application.

`infra_data_manager.py` handles infrastructure file input and converts JSON data into the in-memory infrastructure model.

`journey_profile_importer.py` loads an existing Journey Profile and extracts the route/constraint information used to reconstruct planning state.

`journey_profile_exporter.py` builds the final Journey Profile output from the current route and constraints.

`dynamics.py` provides the train acceleration/braking simulation used during export-time timing calculations.

Specific page:

- [Services](services.md)

## 3. Synchronization Model

The synchronization mechanism is signal-driven.

- Backend and selection emit state-change signals.
- `infra_model_ui_connector.py` bridges these signals to view updates.
- Frontend refreshes highlights, visibility, and scene state accordingly.

This is the key reason the UI stays consistent with route/state changes.

## 4. Runtime Behavior

Detailed end-to-end interaction flows are documented in  [Runtime Flows](runtime_flows.md)
