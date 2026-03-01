# Controllers (Logic & Input)

Controllers serve as the vital middle layer in the application's Model-View-Controller (MVC) architecture. They are responsible for listening to user inputs and interactions from the graphical interface (Views), interpreting those actions, executing the necessary underlying business logic, and subsequently updating the state of the data structures (Models). By decoupling the user interface from the raw data, the controllers ensure that the application remains modular, maintainable, and highly responsive to user commands.

## `infra_view_interaction.py`

### Overview/Description
Captures user interactions such as mouse clicks (left/right), hover events, and keyboard shortcuts within the graphics view. It delegates actions to the appropriate managers and handles UI states like panning, zooming, and track highlighting.

### Core Functions
*   **`eventFilter(self, obj, event)`**: The core event handler that intercepts Qt events on the graphics scene. It identifies which infrastructure items (Timing Points, Tracks, etc.) are interacted with and triggers selection, routing, or context menus.
*   **`update_route_highlights_ui(self)`**: Responsible for updating the visual representation of the selected route, communicating state changes (like start, end, and waypoints) to the view layer.
*   **`_can_start_background_pan(self, scene_pos)`**: Determines if a drag operation should initiate a canvas pan based on the clicked item.

## `infra_view_routing.py`

### Overview/Description
The central logic component for route building. It calculates the shortest paths between selected timing points, manages the sequence of the route, and resolves complex routing scenarios like necessary train reversals.

### Core Functions
*   **`_shortest_path(self, start, goal, ...)`**: Implements Dijkstra's algorithm over `(node, incomingTrack)` states to find the shortest path between a start and goal node while strictly adhering to track transition restrictions.
*   **`_find_nearest_reversal_tp_after_node(...)`**: A complex pathfinding extension used when the route requires the train to reverse direction. It searches for the most suitable Timing Point to use as an auto-reversal point beyond a specific node.
*   **`_replay_tp_sequence(...)`**: Rebuilds the entire internal route sequence from a list of Timing Points. Crucial for undo/redo actions and when loading an existing journey profile.

## `infra_view_scene.py`

### Overview/Description
Controls the visual lifecycle and layout of the scene. It rebuilds the items on the canvas based on the underlying infrastructure models and the active layout mode (e.g., geographic vs. schematic).

### Core Functions
*   **`_rebuild_scene(self)`**: The main orchestration function. It clears the current canvas and triggers the scene builder to place nodes, tracks, and timing points according to the most up-to-date model data.
*   **`_rebuild_schematic_scene(self)`**: A variant of scene building focused on a simplified, abstract representation rather than true geographic coordinates.

## `infra_model_ui_connector.py`

### Overview/Description
Bridges the application state by connecting Qt signals emitted by the `infra_backend` to updates in the UI views. Ensures that the view strictly reflects the current data state.

### Core Functions
*This module focuses entirely on wiring up Qt signals to their respective UI updates. Since its logic is straightforward and handled primarily during initialization, it does not contain large or complex core functions that require detailed documentation.*
