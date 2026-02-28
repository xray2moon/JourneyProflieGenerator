# Architecture Overview

The **Journey Profile Generator** follows a modular, UI-driven architecture centered around the **PyQt6** framework. To ensure maintainability and separation of concerns, the project is structured following the **Model-View-Controller (MVC)** (or Model-View-Presenter) design pattern.

## Core Pillars

1. **Models (State & Data)**: Everything inside `infra_backend.py` and `infra_models.py`. These components store the actual data of the railway network and the current state of the route. They have zero knowledge of the graphical user interface.
2. **Views (UI & Rendering)**: Everything in `InfrastructureView.py`, `infra_scene_builder.py`, and `infra_items.py`. They are responsible for taking data from the backend and drawing lines, nodes, and timing points on the screen.
3. **Controllers (Logic)**: Everything in `infra_view_routing.py` and `infra_view_interaction.py`. These listen to user actions (like a mouse click), calculate the shortest path, and update the Backend Model.
4. **Services (I/O)**: `infra_data_manager.py` and `journey_profile_exporter.py` handle reading the raw JSON files and exporting the final results.

This separation ensures that if the data format for the JSON export changes, only the Services layer needs to be touched, leaving the UI completely unaffected.
