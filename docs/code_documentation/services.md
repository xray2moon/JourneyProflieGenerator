# Services (I/O & Communication)

Services handle communication with the outside world, such as reading from or writing to files, and transforming external data into internal application models.

## `infra_data_manager.py`

### Overview/Description
Handles file input operations for the base infrastructure. It parses raw infrastructure JSON files and converts them into instances of `infra_models` that the rest of the application can use.

### Core Functions
*   **`parse_dict(raw: dict)`**: The core parsing logic that reads raw infrastructure dictionary data, extracts nodes, tracks, timing points, and stopping locations, and validates their relationships before returning a fully constructed `InfrastructureModel`.

## `journey_profile_exporter.py`

### Overview/Description
Responsible for taking the final resolved route from the backend and formatting it into a standardized Journey Profile JSON structure. It calculates relative distances, assigns stopping events, and serializes the data.

### Core Functions
*   **`export_journey_profile(self, parameters: Dict[str, Any])`**: The primary orchestration method for export. It gathers the sequence of tracks and timing points from the current selection and structures the final JSON dictionary.
*   **`_compute_traversal_ranges(...)`**: Computes the exact `[start_m, end_m]` distance ranges for each track traversed in the route, accounting for track direction and reversals.
*   **`export_to_file(...)`**: Handles the final file I/O, writing the generated dictionary out to a designated `.json` file on disk.

## `journey_profile_importer.py`

### Overview/Description
Handles the reverse operation of the exporter: loading an existing Journey Profile JSON file back into the application. It parses the profile to restore the user's route, selection state, and timing constraints.

### Core Functions
*   **`load_dict(self, raw: dict)`**: Reads a parsed Journey Profile dictionary, identifying the intended route sequence, any constraints, and necessary metadata. Returns the data in a format suitable for the backend to replay the route.
*   **`_extract_selected_tp_ids(...)`**: A specialized function that parses the timing point sequence from the raw JSON and matches it against the currently loaded infrastructure to rebuild the exact sequence of waypoints.
