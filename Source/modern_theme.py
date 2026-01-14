from PyQt6.QtGui import QColor

class ModernColors:
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

    # Infrastructure Colors (Shared or Theme-specific)
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
    else:
        bg = ModernColors.D_BACKGROUND
        surface = ModernColors.D_SURFACE
        primary = ModernColors.D_PRIMARY
        text = ModernColors.D_TEXT
        text_sec = ModernColors.D_TEXT_SECONDARY
        border = ModernColors.D_BORDER
        hover = ModernColors.D_HOVER

    return f"""
    QWidget {{
        background-color: {bg};
        color: {text};
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        font-size: 13px;
    }}

    QTabWidget::pane {{
        border: 1px solid {border};
        top: -1px;
        background: {surface};
        border-radius: 8px;
    }}

    QTabBar::tab {{
        background: {bg};
        border: 1px solid {border};
        padding: 8px 16px;
        margin-right: 4px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        color: {text_sec};
    }}

    QTabBar::tab:selected {{
        background: {surface};
        border-bottom-color: {surface};
        color: {text};
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
        border-radius: 6px;
        padding: 4px 24px 4px 8px;
    }}

    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 20px;
        border-left: 1px solid {border};
    }}

    QLabel#legend {{
        background-color: {surface}cc;
        border: 1px solid {border};
        border-radius: 10px;
        padding: 10px;
        font-size: 12px;
    }}

    QScrollBar:vertical {{
        border: none;
        background: {bg};
        width: 10px;
        margin: 0px 0px 0px 0px;
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
    """
