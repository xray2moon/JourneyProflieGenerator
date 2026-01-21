from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import QWidget, QApplication

from Source.modern_theme import ModernColors, get_stylesheet


class InfrastructureViewSettingsMixin:
    def _position_overlay_widgets(self) -> None:
        if getattr(self, "_legend", None) is None:
            return
        self._legend.adjustSize()
        self._legend.move(12, 12)
        self._legend.raise_()

    def _load_settings(self) -> None:
        settings_path = Path("user_settings.json")
        if settings_path.exists():
            try:
                with open(settings_path, "r") as f:
                    settings = json.load(f)
                    self._current_theme = settings.get("theme", "light")
                    self._show_all_tp = settings.get("show_all_tp", False)
                    self._keep_selection = settings.get("keep_selection", False)
                    self._show_legend = settings.get("show_legend", True)
                    self._default_view = settings.get("default_view", "Geographic")
                    if self._default_view not in {"Geographic", "Schematic"}:
                        self._default_view = "Geographic"
                    
                    # Apply settings to UI
                    self._settings_view._theme_combo.setCurrentText(self._current_theme.capitalize())
                    self._settings_view._show_all_tp_check.setChecked(self._show_all_tp)
                    self._settings_view._keep_selection_check.setChecked(self._keep_selection)
                    self._settings_view._show_legend_check.setChecked(self._show_legend)
                    self._settings_view._default_view_combo.setCurrentText(self._default_view)
                    
                    # Apply to view
                    self._on_theme_changed(self._current_theme)
                    self._on_layout_mode_changed(self._default_view)
                    self._layout_combo.setCurrentText(self._default_view)
                    self._on_show_legend_changed(self._show_legend)
            except Exception as e:
                print(f"Failed to load settings: {e}")

    def _save_settings(self) -> None:
        settings = {
            "theme": self._current_theme,
            "show_all_tp": self._show_all_tp,
            "keep_selection": self._keep_selection,
            "show_legend": self._show_legend,
            "default_view": self._default_view
        }
        try:
            with open("user_settings.json", "w") as f:
                json.dump(settings, f)
        except Exception as e:
            print(f"Failed to save settings: {e}")

    def _on_theme_changed(self, theme: str) -> None:
        self._current_theme = theme
        self._save_settings()
        
        # Apply global stylesheet
        QApplication.instance().setStyleSheet(get_stylesheet(theme))
        
        # Update view background
        if theme == "dark":
            self._view.setBackgroundBrush(QBrush(QColor(ModernColors.D_BACKGROUND)))
        else:
            self._view.setBackgroundBrush(QBrush(QColor(ModernColors.L_BACKGROUND)))

        self._rebuild_scene()

    def _on_show_all_tp_changed(self, enabled: bool) -> None:
        self._show_all_tp = enabled
        self._save_settings()
        self._rebuild_scene() # Rebuild to apply visibility rules

    def _on_keep_selection_changed(self, enabled: bool) -> None:
        self._keep_selection = enabled
        self._save_settings()

    def _on_show_legend_changed(self, enabled: bool) -> None:
        self._show_legend = enabled
        self._legend.setVisible(enabled)
        self._save_settings()

    def _on_default_view_changed(self, view_name: str) -> None:
        self._default_view = view_name
        self._save_settings()

    def _update_legend_text(self) -> None:
        if getattr(self, "_legend", None) is None:
            return
        
        # Use dark theme track color since legend is now always dark
        track_color = ModernColors.TRACK_DEFAULT_D

        self._legend.setText(
            "<b>Legende</b><br>"
            f"<span style='color:{track_color}'>■</span> Gleis&nbsp;&nbsp;"
            f"<span style='color:{ModernColors.TRACK_TP_VISIBLE}'>■</span> Gleis (TPs an)&nbsp;&nbsp;"
            f"<span style='color:{ModernColors.TRACK_ROUTE}'>■</span> Route<br>"
            f"<span style='color:{ModernColors.TRACK_HOVER}'>■</span> Hover&nbsp;&nbsp;"
            f"<span style='color:{ModernColors.NODE_DEFAULT}'>●</span> Bahnhof/Node&nbsp;&nbsp;"
            f"<span style='color:{ModernColors.TP_DEFAULT}'>●</span> Timing point&nbsp;&nbsp;"
            f"<span style='color:{ModernColors.SL_DEFAULT}'>●</span> Halt<br>"
            f"<span style='color:{ModernColors.NODE_START}'>●</span> Start&nbsp;&nbsp;"
            f"<span style='color:{ModernColors.NODE_END}'>●</span> Ende"
        )
        self._position_overlay_widgets()

    def resizeEvent(self, event):
        # This is a mixin method; using `super()` here can skip the QWidget implementation
        # depending on the MRO. Call QWidget explicitly to ensure Qt's base handling runs.
        QWidget.resizeEvent(self, event)
        self._position_overlay_widgets()
        # Do the initial fit once, when the widget first gets a meaningful size.
        if not getattr(self, "_initial_fit_done", False):
            QTimer.singleShot(0, self._fit_to_scene)

    # -----------
    # Interaction / event filter
    # -----------
