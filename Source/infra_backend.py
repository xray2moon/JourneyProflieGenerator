from __future__ import annotations
from typing import Optional, List, Dict
from PyQt6.QtCore import QObject, pyqtSignal
from Source.infra_data_manager import InfrastructureModel, InfrastructureParser
from Source.infra_selection_model import InfrastructureSelectionModel

class InfrastructureBackend(QObject):
    infrastructureLoaded = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._model: InfrastructureModel = InfrastructureModel()
        self._selection: InfrastructureSelectionModel = InfrastructureSelectionModel()

    @property
    def model(self) -> InfrastructureModel:
        return self._model

    @property
    def selection(self) -> InfrastructureSelectionModel:
        return self._selection

    def load_infrastructure(self, json_path: str):
        """Loads infrastructure and notifies listeners."""
        print(f"DEBUG: Backend loading {json_path}", flush=True)
        self._model = InfrastructureParser.parse_file(json_path)
        self._selection.clear_selection()
        print("DEBUG: Backend emitting infrastructureLoaded", flush=True)
        self.infrastructureLoaded.emit()

    def generate_journey_profile(self, file_path: str, parameters: dict):
        """Generates and saves a journey profile."""
        from Source.journey_profile_exporter import JourneyProfileExporter
        exporter = JourneyProfileExporter(self)
        exporter.export_to_file(file_path, parameters)
