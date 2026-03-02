from __future__ import annotations
from typing import Optional, List, Dict
from PyQt6.QtCore import QObject, pyqtSignal
from Source.infra_data_manager import InfrastructureModel, InfrastructureParser
from Source.infra_selection_model import InfrastructureSelectionModel

class InfrastructureBackend(QObject):
    """Central model container for loaded infrastructure and selection state."""

    infrastructureLoaded = pyqtSignal()

    def __init__(self):
        """Initialize empty infrastructure data and mutable selection state."""
        super().__init__()
        self._model: InfrastructureModel = InfrastructureModel()
        self._selection: InfrastructureSelectionModel = InfrastructureSelectionModel()

    @property
    def model(self) -> InfrastructureModel:
        """Return the currently loaded infrastructure model."""
        return self._model

    @property
    def selection(self) -> InfrastructureSelectionModel:
        """Return the mutable planning/selection model."""
        return self._selection

    def load_infrastructure(self, json_path: str):
        """Load infrastructure from file and emit `infrastructureLoaded`."""
        print(f"DEBUG: Backend loading {json_path}", flush=True)
        self._model = InfrastructureParser.parse_file(json_path)
        self._selection.clear_selection()
        print("DEBUG: Backend emitting infrastructureLoaded", flush=True)
        self.infrastructureLoaded.emit()

    def generate_journey_profile(self, file_path: str, parameters: dict):
        """Export current route/constraints to a journey profile JSON file."""
        from Source.journey_profile_exporter import JourneyProfileExporter
        exporter = JourneyProfileExporter(self)
        exporter.export_to_file(file_path, parameters)
