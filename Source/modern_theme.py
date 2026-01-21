from pathlib import Path
from PyQt6.QtGui import QColor

class ModernColors:
    # ... (keep existing)
    # Light Theme
    L_BACKGROUND = "#f8f9fa"
    L_SURFACE = "#ffffff"
    L_PRIMARY = "#007aff"
    L_SECONDARY = "#5856d6"
    L_TEXT = "#1c1c1e"
    L_TEXT_SECONDARY = "#8e8e93"
    L_BORDER = "#d1d1d6"
    L_HOVER = "#e5e5ea"
    
    # Dark Theme
    D_BACKGROUND = "#1c1c1e"
    D_SURFACE = "#2c2c2e"
    D_PRIMARY = "#0a84ff"
    D_SECONDARY = "#5e5ce6"
    D_TEXT = "#ffffff"
    D_TEXT_SECONDARY = "#8e8e93"
    D_BORDER = "#3a3a3c"
    D_HOVER = "#3a3a3c"

    # Infrastructure Colors
    TRACK_DEFAULT_L = "#606060"
    TRACK_DEFAULT_D = "#a0a0a0"
    TRACK_HOVER = "#007aff"
    TRACK_ROUTE = "#34c759"
    TRACK_TP_VISIBLE = "#5856d6"
    
    NODE_DEFAULT = "#ff3b30"
    NODE_START = "#34c759"
    NODE_END = "#ff9500"
    
    TP_DEFAULT = "#007aff"
    SL_DEFAULT = "#af52de"

def get_stylesheet(theme="light"):
    if theme == "light":
        bg = ModernColors.L_BACKGROUND
        surface = ModernColors.L_SURFACE
        primary = ModernColors.L_PRIMARY
        text = ModernColors.L_TEXT
        text_sec = ModernColors.L_TEXT_SECONDARY
        border = ModernColors.L_BORDER
        hover = ModernColors.L_HOVER
        check_border = "#8e8e93" # Darker border for light mode checkboxes
    else:
        bg = ModernColors.D_BACKGROUND
        surface = ModernColors.D_SURFACE
        primary = ModernColors.D_PRIMARY
        text = ModernColors.D_TEXT
        text_sec = ModernColors.D_TEXT_SECONDARY
        border = ModernColors.D_BORDER
        hover = ModernColors.D_HOVER
        check_border = border
    
    popup_border = f"1px solid {border}" if theme == "light" else f"1px solid {surface}"

    asset_path = str(Path(__file__).parent / "assets" / "checkmark.svg").replace("\\", "/")

    return f"""
    QWidget {{
        background-color: {bg};
        color: {text};
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        font-size: 13px;
    }}

    QTabWidget::pane {{
        border: none;
        border-top: 1px solid {border};
        background: {surface};
    }}

    QTabBar {{
        background-color: transparent;
    }}

    QTabBar::tab {{
        background: transparent;
        border: none;
        padding: 12px 24px;
        margin-right: 8px;
        color: {text_sec};
        border-bottom: 3px solid transparent;
        font-weight: 500;
        font-size: 14px;
    }}

    QTabBar::tab:hover {{
        color: {text};
    }}

    QTabBar::tab:selected {{
        color: {primary};
        border-bottom: 3px solid {primary};
        font-weight: bold;
    }}

    QGroupBox {{
        font-weight: bold;
        border: 1px solid {border};
        border-radius: 8px;
        margin-top: 12px;
        padding-top: 12px;
    }}

    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 5px;
        left: 10px;
    }}

    QPushButton {{
        background-color: {surface};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 6px 12px;
        min-height: 20px;
    }}

    QPushButton:hover {{
        background-color: {hover};
    }}

    QPushButton:pressed {{
        background-color: {border};
    }}

    QLineEdit {{
        background-color: {surface};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 4px 8px;
    }}

    QComboBox {{
        background-color: {surface};
        border: 1px solid {border};
        border-radius: 8px;
        padding: 5px 24px 5px 10px;
        combobox-popup: 0;
    }}

    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 26px;
        border-left: none;
        background: transparent;
    }}

    QComboBox::down-arrow {{
        width: 12px;
        height: 12px;
    }}

    /* The outer container of the popup - match background to hide rectangular corners */
    QComboBox QFrame {{
        background-color: {bg};
        border: none;
    }}

    /* The actual list inside the popup */
    QComboBox QAbstractItemView {{
        background-color: {surface};
        border: 1px solid {border};
        border-radius: 8px;
        outline: 0px;
        margin: 0px;
        padding: 4px;
    }}

    QComboBox QAbstractItemView::item {{
        padding: 8px 12px;
        border-radius: 6px;
        margin: 2px;
        color: {text};
    }}

    QComboBox QAbstractItemView::item:selected {{
        background-color: {primary};
        color: {surface};
    }}

    QCheckBox {{
        spacing: 8px;
        color: {text};
    }}

    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 5px;
        border: 2px solid {check_border};
        background-color: transparent;
    }}

    QCheckBox::indicator:hover {{
        border-color: #03DAC6;
    }}

    QCheckBox::indicator:unchecked {{
        background-color: transparent;
        border: 2px solid {check_border};
    }}

    QCheckBox::indicator:checked {{
        background-color: #03DAC6;
        border-color: #03DAC6;
        image: url({asset_path});
    }}

    QLabel#legend {{
        background-color: {ModernColors.D_SURFACE}cc;
        border: 1px solid {ModernColors.D_BORDER};
        color: {"#000000" if theme == "light" else "#ffffff"};
        border-radius: 10px;
        padding: 10px;
        font-size: 12px;
    }}

    QScrollBar:vertical {{
        border: none;
        background: {surface};
        width: 10px;
        margin: 0px;
    }}

    QScrollBar::handle:vertical {{
        background: {border};
        min-height: 20px;
        border-radius: 5px;
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        border: none;
        background: none;
    }}

    QScrollBar:horizontal {{
        border: none;
        background: {surface};
        height: 10px;
        margin: 0px;
    }}

    QScrollBar::handle:horizontal {{
        background: {border};
        min-width: 20px;
        border-radius: 5px;
    }}

    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        border: none;
        background: none;
    }}

    QAbstractScrollArea::corner {{
        background: {surface};
        border: none;
    }}
    """