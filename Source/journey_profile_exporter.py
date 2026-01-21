from __future__ import annotations
import json
from typing import Dict, List, Any
from Source.infra_backend import InfrastructureBackend

class JourneyProfileExporter:
    """
    Exports the current state (route, timing constraints, parameters)
    to a Journey Profile JSON file.
    """
    def __init__(self, backend: InfrastructureBackend):
        self._backend = backend

    def export_to_dict(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        selection = self._backend.selection
        model = self._backend.model
        
        profile = {
            "metadata": {
                "infrastructure_file": model.json_path,
                "train_number": parameters.get("trainNumber", ""),
                "train_type": parameters.get("trainType", ""),
                "driving_strategy": parameters.get("drivingStrategy", "")
            },
            "route": {
                "node_ids": selection.current_route,
                "track_ids": selection.current_tracks
            },
            "timing_constraints": []
        }
        
        for tp_id, constraint in selection.timing_constraints.items():
            tp_data = {
                "timing_point_id": tp_id,
                "type": constraint.get("pointType", "STOP"),
                "arrival_time": constraint.get("arrivalTime", ""),
                "departure_time": constraint.get("departureTime", "")
            }
            profile["timing_constraints"].append(tp_data)
            
        return profile

    def export_to_file(self, file_path: str, parameters: Dict[str, Any]):
        data = self._export_to_dict(parameters)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
