# 1. Models (State & Data)

Models are responsible for holding the application's state, data structures, and core physics logic. They do not know about the UI.

## Core Files

* **`infra_backend.py`**: The central data store. It holds the loaded infrastructure and the current state of the planned route.
* **`infra_models.py`**: Defines the raw data classes (e.g., Nodes, Tracks, Timing Points) that represent the railway infrastructure in memory.
* **`infra_selection_model.py`**: Keeps track of which elements (like Timing Points) the user has currently selected.
* **`dynamics.py`**: Contains the pure physical and mathematical models for calculating acceleration and braking curves.
