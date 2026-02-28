# Controllers (Logic & Input)

Controllers act as the middlemen. They listen to user inputs from the Views, execute the necessary logic, and update the Models accordingly.

## Core Files

* **`infra_view_interaction.py`**: Captures mouse clicks (left/right) and keyboard shortcuts within the graphics view, delegating actions to the appropriate managers.
* **`infra_view_routing.py`**: The core logic center for route building. It calculates the shortest paths between selected points and manages the sequence of the route.
* **`infra_view_scene.py`**: Controls the visual state of the scene (e.g., toggling the visibility of specific timing points based on user settings).
* **`infra_model_ui_connector.py`**: Bridges the gap by connecting signals emitted by the `infra_backend` to updates in the UI views.
