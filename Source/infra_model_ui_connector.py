from __future__ import annotations
from typing import TYPE_CHECKING
from PyQt6.QtCore import QObject

if TYPE_CHECKING:
    from Source.infra_backend import InfrastructureBackend
    from Source.InfrastructureView import InfrastructureView

class ModelUIConnector(QObject):
    def __init__(self, backend: InfrastructureBackend, view: InfrastructureView):
        super().__init__()
        self._backend = backend
        self._view = view
        
        # Connect Backend -> View
        self._backend.infrastructureLoaded.connect(self._on_infrastructure_loaded)
        
        # Connect Selection -> View (updates highlights, etc.)
        self._backend.selection.routeChanged.connect(self._view.update_route_highlights)
        self._backend.selection.timingConstraintsChanged.connect(self._view.update_timing_points)
        self._backend.selection.visibleTpTracksChanged.connect(self._view.update_tp_visibility)
        self._backend.selection.startTpChanged.connect(lambda _: self._view.update_route_highlights_ui())
        self._backend.selection.endTpChanged.connect(lambda _: self._view.update_route_highlights_ui())
        self._backend.selection.waypointTpsChanged.connect(lambda _: self._view.update_route_highlights_ui())

    def _on_infrastructure_loaded(self):
        # Notify the view to rebuild itself with new data
        self._view.on_model_updated()
