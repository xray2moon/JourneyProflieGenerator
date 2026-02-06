from __future__ import annotations
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QPointF
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QTabWidget,
    QGraphicsScene,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QLabel,
)

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from Source.infra_ui import ParameterView, PanZoomGraphicsView, SettingsView
from Source.infra_scene_builder import InfrastructureSceneBuilder
from Source.infra_items import NodeItem, TrackItem, TimingPointItem, StoppingLocationItem
from Source.infra_view_interaction import InfrastructureViewInteractionMixin
from Source.infra_view_layouts import InfrastructureViewLayoutsMixin
from Source.infra_view_routing import InfrastructureViewRoutingMixin
from Source.infra_view_scene import InfrastructureViewSceneMixin
from Source.infra_view_settings import InfrastructureViewSettingsMixin
from Source.modern_theme import get_stylesheet
from Source.infra_backend import InfrastructureBackend
from Source.infra_model_ui_connector import ModelUIConnector
from Source.journey_profile_exporter import JourneyProfileExporter

class InfrastructureView(
    QWidget,
    InfrastructureViewSettingsMixin,
    InfrastructureViewRoutingMixin,
    InfrastructureViewLayoutsMixin,
    InfrastructureViewSceneMixin,
    InfrastructureViewInteractionMixin,
):
    routeChanged = pyqtSignal(list)
    timingConstraintsChanged = pyqtSignal(list)
    selectionChanged = pyqtSignal(dict)

    def __init__(self, json_path: Optional[str] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # Backend components
        self._backend = InfrastructureBackend()
        self._connector = ModelUIConnector(self._backend, self)
        self._exporter = JourneyProfileExporter(self._backend)

        self._scene = QGraphicsScene(self)
        self._scene_builder = InfrastructureSceneBuilder(self._scene)
        self._view = PanZoomGraphicsView(self._scene, self)
        
        self._view.set_can_start_background_pan(self._can_start_background_pan)
        self._legend = QLabel(self._view.viewport())
        self._legend.setObjectName("legend")
        self._legend.setTextFormat(Qt.TextFormat.RichText)
        self._legend.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._legend.adjustSize()
        self._legend.move(12, 12)
        self._legend.raise_()

        # Toolbar
        self._clear_route_btn = QPushButton("Clear route")
        self._clear_route_btn.clicked.connect(self.clear_route)
        self._layout_combo = QComboBox()
        self._layout_combo.addItems(["Geographic", "Schematic"])
        self._layout_combo.currentTextChanged.connect(self._on_layout_mode_changed)
        
        self._route_start_label = QLabel("Start: -")
        self._route_end_label = QLabel("End: -")

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 4)
        toolbar.setSpacing(10)
        toolbar.addWidget(self._clear_route_btn)
        toolbar.addSpacing(4)
        toolbar.addWidget(QLabel("Layout:"))
        toolbar.addWidget(self._layout_combo)
        toolbar.addStretch(1)
        toolbar.addWidget(self._route_start_label)
        toolbar.addSpacing(8)
        toolbar.addWidget(self._route_end_label)

        infra_tab = QWidget()
        infra_layout = QVBoxLayout(infra_tab)
        infra_layout.setContentsMargins(4, 4, 4, 4)
        infra_layout.setSpacing(4)
        infra_layout.addLayout(toolbar)
        infra_layout.addWidget(self._view)

        self._tabs = QTabWidget()
        self._tabs.addTab(infra_tab, "Infrastructure View")
        
        self._parameter_view = ParameterView(self)
        self._parameter_view.infrastructureLoadRequested.connect(self.load_infrastructure)
        self._parameter_view.parametersChanged.connect(self._on_parameters_changed)
        self._parameter_view.journeyProfileGenerationRequested.connect(self._on_journey_profile_generation_requested)
        self._tabs.addTab(self._parameter_view, "Parameter View")
        
        self._settings_view = SettingsView(self)
        self._settings_view.themeChanged.connect(self._on_theme_changed)
        self._settings_view.showAllTimingPointsChanged.connect(self._on_show_all_tp_changed)
        self._settings_view.keepSelectionChanged.connect(self._on_keep_selection_changed)
        self._settings_view.showLegendChanged.connect(self._on_show_legend_changed)
        self._settings_view.defaultViewChanged.connect(self._on_default_view_changed)
        self._tabs.addTab(self._settings_view, "Settings")
        self._tabs.addTab(QWidget(), "Confirm")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._tabs)
        self.setLayout(layout)

        self._initial_fit_done = False
        self._layout_mode = "geographic"
        
        # Routing graph
        self._graph: Dict[str, List[Tuple[str, str, float]]] = {}

        # UI Cache for items
        self._node_items: Dict[str, NodeItem] = {}
        self._track_items: Dict[str, TrackItem] = {}
        self._tp_items: Dict[int, TimingPointItem] = {}
        self._sl_items: Dict[str, StoppingLocationItem] = {}
        self._tp_track_map: Dict[str, List[TimingPointItem]] = {}

        # Default state
        self._parameters: dict = self._parameter_view.parameters()
        self._current_theme = "light"
        QApplication.instance().setStyleSheet(get_stylesheet(self._current_theme))
        
        self._show_all_tp: bool = False
        self._keep_selection: bool = False
        self._show_legend: bool = True
        self._default_view: str = "Geographic"

        self._scene.selectionChanged.connect(self._on_selection_changed)
        self._update_legend_text()

        if json_path:
            self.load_infrastructure(json_path)
            
        self._load_settings()

    @property
    def backend(self) -> InfrastructureBackend:
        return self._backend

    def load_infrastructure(self, json_path: str):
        print(f"DEBUG: load_infrastructure requested for {json_path}", flush=True)
        try:
            self._backend.load_infrastructure(json_path)
            self._tabs.setCurrentIndex(0)
        except Exception as exc:
            self._parameter_view.set_infrastructure_error(json_path, str(exc))
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Failed to load infrastructure", str(exc))

    def on_model_updated(self):
        """Called by connector when backend data changes."""
        print("DEBUG: on_model_updated called", flush=True)
        model = self._backend.model
        self._build_graph()
        self._rebuild_scene()
        self._initial_fit_done = False
        QTimer.singleShot(0, self._fit_to_scene)
        
        self._parameter_view.set_infrastructure_summary(
            model.json_path,
            nodes=len(model.nodes),
            tracks=len(model.tracks),
            timing_points=len(model.timing_points),
            stopping_locations=len(model.stopping_locations)
        )

    def update_route_highlights(self, nodes: List[str]):
        self.update_route_highlights_ui()
        self.routeChanged.emit(list(nodes))

    def update_timing_points(self, constraints: Dict[int, dict]):
        self._restore_timing_point_markers()
        self.timingConstraintsChanged.emit(list(constraints.values()))

    def update_tp_visibility(self, visible_tracks: set[str]):
        # Full rebuild for simplicity, can be optimized
        self._rebuild_scene()

    def _on_parameters_changed(self, params: dict) -> None:
        self._parameters = dict(params or {})

    def _on_journey_profile_generation_requested(self, file_path: str, parameters: dict) -> None:
        if not self._backend.selection.current_route:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No route", "Please select a route first.")
            return
        
        try:
            self._backend.generate_journey_profile(file_path, parameters)
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Success", f"Journey Profile generated:\n{file_path}")
        except Exception as exc:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Generation failed", str(exc))

    def export_state(self) -> dict:
        return self._exporter.export_to_dict(self._parameters)

if __name__ == "__main__":
    if sys.platform == "darwin": pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    default_json = "data_examples/ebd_v7_3_stations-infrastructure-description.json"
    if not Path(default_json).exists():
        if Path("ebd_v7_3_stations-infrastructure-description.json").exists():
            default_json = "ebd_v7_3_stations-infrastructure-description.json"
    w = InfrastructureView(json_path=default_json)
    w.resize(1200, 800)
    w.show()
    sys.exit(app.exec())