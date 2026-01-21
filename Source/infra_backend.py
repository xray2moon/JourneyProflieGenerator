from __future__ import annotations
from typing import Optional, List, Dict
from PyQt6.QtCore import QObject, pyqtSignal
from Source.infra_data_manager import InfrastructureModel, InfrastructureParser
from Source.infra_selection_model import InfrastructureSelectionModel

class InfrastructureBackend(QObject):
    """
    Central backend that holds the infrastructure data and selection state.
    Acts as the 'Single Source of Truth'.
    """
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
        self._model = InfrastructureParser.parse_file(json_path)
        self._selection.clear()
        self.infrastructureLoaded.emit()
