"""
InfrastructureView.py

PyQt6 widget that loads an EBD infrastructure JSON (nodes/tracks/timingPoints/stoppingLocations),
renders it with a QGraphicsScene, and supports:
- zoom (mouse wheel) + pan (middle mouse drag or space+left drag)
- route selection by clicking infrastructure nodes (red)
- timing constraints by clicking timing points (blue markers along tracks)

Layout modes:
- Geographic: uses the raw node coordinates and shaping points.
- Schematic: currently intentionally blank (disabled).

Notes:
- Virtual nodes/tracks are ignored by design.
- "Timing points" are rendered as interactive markers positioned along tracks using
  distanceToTargetNodeInMeters and the referenced targetNodeId.

Signals:
- routeChanged(list[str])                     : ordered list of node UUIDs representing the selected route
- timingConstraintsChanged(list[dict])        : list of timing point constraints (dicts)
- selectionChanged(dict)                      : emits small info dict on hover/click for tooltips/side panels
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
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
from Source.infra_view_data import InfrastructureViewDataMixin
from Source.infra_view_interaction import InfrastructureViewInteractionMixin
from Source.infra_view_layouts import InfrastructureViewLayoutsMixin
from Source.infra_view_routing import InfrastructureViewRoutingMixin
from Source.infra_view_scene import InfrastructureViewSceneMixin
from Source.infra_view_settings import InfrastructureViewSettingsMixin
from Source.modern_theme import get_stylesheet


# --------------------------
# Main widget
# --------------------------

class InfrastructureView(
    QWidget,
    InfrastructureViewSettingsMixin,
    InfrastructureViewDataMixin,
    InfrastructureViewRoutingMixin,
    InfrastructureViewLayoutsMixin,
    InfrastructureViewSceneMixin,
    InfrastructureViewInteractionMixin,
):
    """
    Top-level QWidget with 3 tabs:
    - Infrastructure View (this canvas)
    - Parameter view (placeholder)
    - confirm (placeholder)

    Core API:
    - load_infrastructure(json_path)
    - clear_route()
    - export_state() -> {"routeNodeIds": [...], "timingConstraints": [...]}
    """
    routeChanged = pyqtSignal(list)  # list[str]
    timingConstraintsChanged = pyqtSignal(list)  # list[dict]
    selectionChanged = pyqtSignal(dict)  # for tooltips/sidepanels

    def __init__(self, json_path: Optional[str] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._scene = QGraphicsScene(self)
        self._view = PanZoomGraphicsView(self._scene, self)
        self._view.set_can_start_background_pan(self._can_start_background_pan)
        self._legend = QLabel(self._view.viewport())
        self._legend.setObjectName("legend")
        self._legend.setTextFormat(Qt.TextFormat.RichText)
        self._legend.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # Initial text set by _update_legend_text() later in init
        self._legend.adjustSize()
        self._legend.move(12, 12)
        self._legend.raise_()

        # Small toolbar area (optional but useful)
        self._clear_route_btn = QPushButton("Clear route")
        self._clear_route_btn.clicked.connect(self.clear_route)
        self._layout_combo = QComboBox()
        self._layout_combo.addItems(["Geographic", "Schematic"])
        self._layout_combo.currentTextChanged.connect(self._on_layout_mode_changed)
        layout_label = QLabel("Layout:")
        layout_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self._route_start_label = QLabel("Start: -")
        self._route_start_label.setToolTip("No start node selected")
        self._route_end_label = QLabel("End: -")
        self._route_end_label.setToolTip("No end node selected")

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 4)
        toolbar.setSpacing(10)
        toolbar.addWidget(self._clear_route_btn)
        toolbar.addSpacing(4)
        toolbar.addWidget(layout_label)
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
        self._parameter_view.infrastructureLoadRequested.connect(self._on_infrastructure_load_requested)
        self._parameter_view.parametersChanged.connect(self._on_parameters_changed)
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
        self._node_positions: Dict[str, QPointF] = {}
        self._track_render_paths: Dict[str, QPainterPath] = {}
        self._track_render_polylines: Dict[str, List[QPointF]] = {}

        # Model caches
        self._nodes: Dict[str, Node] = {}
        self._tracks: Dict[str, Track] = {}
        self._timing_points: Dict[int, TimingPoint] = {}
        self._stopping_locations: Dict[str, StoppingLocation] = {}

        # Group label mapping for stopping locations
        self._sl_to_group: Dict[str, str] = {}  # stoppingLocationId -> groupName

        # Graphics items
        self._node_items: Dict[str, NodeItem] = {}
        self._track_items: Dict[str, TrackItem] = {}
        self._tp_items: Dict[int, TimingPointItem] = {}
        self._sl_items: Dict[str, StoppingLocationItem] = {}
        self._tp_track_map: Dict[str, List[TimingPointItem]] = {}
        self._visible_tp_tracks: set[str] = set()

        # Routing graph: nodeId -> list of (neighborNodeId, trackId, weight)
        self._graph: Dict[str, List[Tuple[str, str, float]]] = {}
        # Simple points: nodeId -> allowed track-to-track transitions (unordered pairs)
        self._simple_point_connections: Dict[str, set[frozenset[str]]] = {}

        # Current state
        self._route_node_ids: List[str] = []
        self._route_track_ids: List[str] = []
        self._hover_track_id: Optional[str] = None
        # timingPointId -> constraint dict
        self._timing_constraints: Dict[int, dict] = {}
        self._infrastructure_json_path: Optional[str] = None
        self._parameters: dict = self._parameter_view.parameters()
        self._current_theme = "light"
        QApplication.instance().setStyleSheet(get_stylesheet(self._current_theme))
        
        # New settings state
        self._show_all_tp: bool = False
        self._keep_selection: bool = False
        self._show_legend: bool = True
        self._default_view: str = "Geographic"

        # Scene interaction
        self._scene.selectionChanged.connect(self._on_selection_changed)
        self._update_legend_text()

        if json_path:
            self.load_infrastructure(json_path)
            
        self._load_settings()





# --------------------------
# Standalone demo
# --------------------------

if __name__ == "__main__":
    # MacBook/High-DPI compatibility
    if sys.platform == "darwin":
        # macOS specific fixes if any
        pass
    
    # Enable High DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion") # Fusion is most consistent across platforms for custom QSS

    # Adjust path as needed:
    default_json = "data_examples/ebd_v7_3_stations-infrastructure-description.json"
    # fallback for local quick test:
    if not Path(default_json).exists():
        # Try current directory
        if Path("ebd_v7_3_stations-infrastructure-description.json").exists():
            default_json = "ebd_v7_3_stations-infrastructure-description.json"

    w = InfrastructureView(json_path=default_json)
    w.resize(1200, 800)
    w.show()

    sys.exit(app.exec())
