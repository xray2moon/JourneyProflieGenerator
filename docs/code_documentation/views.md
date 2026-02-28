# Views (UI & Rendering)

Views are responsible for everything the user sees on the screen. They take data from the Models (usually via Controllers) and render it.

## Core Files

* **`InfrastructureView.py`**: The main GUI window. It acts as the central hub that sets up the layout and docks all other visual components.
* **`infra_scene_builder.py`**: Iterates over the infrastructure models and creates the corresponding visual items for the canvas.
* **`infra_items.py`**: Contains the custom PyQt `QGraphicsItem` classes (like `TrackItem`, `NodeItem`) that define how tracks and points are drawn.
* **`infra_ui.py`**: Contains layout definitions and widget assemblies for sidebars and toolbars.
* **`modern_theme.py`**: Stores color palettes, fonts, and styling rules.
