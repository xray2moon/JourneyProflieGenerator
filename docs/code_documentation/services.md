# Services (I/O & Communication)

Services handle communication with the outside world, such as reading from or writing to files.

## Core Files

* **`infra_data_manager.py`**: Handles file I/O operations and parses raw infrastructure JSON files into the `infra_models`.
* **`journey_profile_exporter.py`**: Takes the final route from the backend and formats it into the standardized Journey Profile JSON structure.
* **`journey_profile_importer.py`**: Handles the reverse operation: loading an existing Journey Profile JSON back into the application for editing.
