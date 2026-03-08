# Views (UI & Rendering)

Views form the visual layer of the application, responsible for everything the user interacts with and sees on the screen. Following the MVC paradigm, Views do not hold core business logic or raw state. Instead, they consume data provided by the Models (typically mediated via the Controllers) and render it into a comprehensive graphical interface. This layer includes the main application windows, interactive canvases, custom-drawn infrastructure items, and styling definitions, all working together to provide an intuitive and responsive user experience.

## `InfrastructureView.py`

### Overview/Description
The main GUI window of the application. It acts as the central hub that sets up the layout, docks all other visual components (like toolbars and sidebars), and initializes the core application backend.

### Core Functions
*   **`load_infrastructure(self, json_path: str)`**: Triggers the loading of an infrastructure file, updates the window title, and calls upon the backend to process the new data.
*   **`on_model_updated(self)`**: Reacts to a successful infrastructure load by updating the scene, resetting view states, and re-applying user layout preferences.
*   **`update_route_highlights(self, nodes: List[str])`**: Updates the visual highlighting of tracks and nodes based on the currently calculated route.

## `infra_scene_builder.py`

### Overview/Description
Iterates over the loaded infrastructure models and creates the corresponding visual items (`QGraphicsItem`) for the interactive canvas.

### Core Functions
*   **`build_geographic(self, model: InfrastructureModel)`**: Translates the logical nodes, tracks, and timing points into visual representations based on their geographic (X, Y) coordinates, placing them accurately on the scene.

## `infra_items.py`

### Overview/Description
Contains the custom PyQt `QGraphicsItem` classes that define exactly how individual infrastructure elements are drawn and styled on the canvas.

### Core Components
*   **`TrackItem`**: Draws the connections between nodes using paths, handling coloring for routes and hovering.
*   **`NodeItem`**: Represents infrastructure junctions.
*   **`TimingPointItem`**: Represents interactive timing points along the tracks, allowing visual distinction for selection and constraints.
*   **`StoppingLocationItem`**: Renders stopping locations adjacent to tracks.

## `infra_ui.py`

### Overview/Description
Contains layout definitions and widget assemblies for sidebars, toolbars, and dialog windows used throughout the application.

### Core Components
*   **`ParameterView`**: Manages the sidebar UI for inputting journey profile parameters (like train ID, timestamps).
*   **`TimingConstraintDialog`**: The modal dialog that allows users to edit specific timing constraints (arrival/departure times) for individual timing points.
*   **`PanZoomGraphicsView`**: A custom `QGraphicsView` subclass that adds middle-mouse panning and scroll-wheel zooming to the standard Qt canvas.

## `modern_theme.py`

### Overview/Description
Centralizes the application's aesthetic by storing color palettes, fonts, and global styling rules.

### Core Functions
*   **`get_stylesheet(theme="light")`**: Dynamically generates and returns the global Qt stylesheet string based on the requested theme mode, injecting the colors defined in the `ModernColors` class.
