"""Dark laboratory theme shared by the OMX Studio v2 screens."""

BG, INK, MUTED = "#0c1119", "#e2eaf5", "#9aaac0"
GO, STOP, WAIT, BLUE, GRAY = "#70d6b0", "#ff8794", "#eac574", "#55d6c8", "#8799b2"

def tone(bg, fg, border):
    return (f"background:{bg};color:{fg};border:1px solid {border};"
            "border-radius:8px;padding:10px 12px;font-weight:600;")

STYLES = {
    "STYLE_GREEN": tone("#112f29", "#70d6b0", "#28564a"),
    "STYLE_RED": tone("#351b25", "#ff8794", "#66303f"),
    "STYLE_ORANGE": tone("#332a18", "#eac574", "#5a4827"),
    "STYLE_BLUE": tone("#162c3d", "#82cfff", "#2a4965"),
    "STYLE_GRAY": tone("#192330", "#a0afc3", "#2a394d"),
}

CAM_STYLE = "background:#070c12;color:#7f93ad;border:1px solid #243347;border-radius:9px;font-size:14px;"

def apply_palette(app):
    # Give menus, file chooser items and placeholders the same dark base palette.
    from PySide6.QtGui import QColor, QPalette
    palette = QPalette()
    colors = {
        QPalette.Window: BG, QPalette.WindowText: INK,
        QPalette.Base: "#101824", QPalette.AlternateBase: "#172231",
        QPalette.Text: INK, QPalette.Button: "#1a2635", QPalette.ButtonText: INK,
        QPalette.Highlight: "#266e6b", QPalette.HighlightedText: "#edfffd",
        QPalette.ToolTipBase: "#26374a", QPalette.ToolTipText: INK,
        QPalette.PlaceholderText: "#7689a3", QPalette.Link: BLUE,
        QPalette.Light: "#354b65", QPalette.Midlight: "#2d4057",
        QPalette.Mid: "#263448", QPalette.Dark: "#070c12", QPalette.Shadow: "#03070d",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor("#63738b"))
    app.setPalette(palette)

QSS = """
QWidget { background:#0c1119; color:#e2eaf5; font-family:'Noto Sans CJK KR'; font-size:13px; }
QLabel { background:transparent; border:0; }
QWidget#titleBar { background:#111b28; border-bottom:1px solid #28394e; }
QLabel#titleBrand { color:#9cb5cd; font-size:11px; font-weight:700; }
QPushButton#titleNav { background:transparent; color:#91a6bf; border:0; border-bottom:2px solid transparent; border-radius:0; padding:0 19px; font-size:13px; font-weight:600; }
QPushButton#titleNav:hover { background:#1c3040; color:#d1f5ee; }
QPushButton#titleNav:checked { background:#173037; border-bottom:2px solid #55d6c8; color:#89e9dc; }
QPushButton#windowControl, QPushButton#windowClose { background:transparent; border:0; border-radius:0; padding:0; }
QPushButton#windowControl:hover { background:#283c51; }
QPushButton#windowControl:pressed { background:#37516b; }
QPushButton#windowClose:hover { background:#aa354c; }
QPushButton#windowClose:pressed { background:#7e2337; }
QFrame#panel { background:#141c28; border:1px solid #263448; border-radius:12px; }
QLabel#pageTitle { font-size:25px; font-weight:700; color:#edf3fb; }
QLabel#eyebrow { font-size:10px; font-weight:700; color:#55d6c8; }
QLabel#muted { color:#9aaac0; font-size:12px; }
QLabel#cardTitle { font-size:14px; font-weight:700; color:#d4e1f0; }
QLabel#fieldLabel { color:#9aaac0; font-size:11px; }
QLabel#metric { color:#9fdecf; font-size:12px; font-weight:600; padding:5px 10px; background:#142c2d; border:1px solid #234346; border-radius:7px; }
QLabel#sessionPath { color:#8b9db6; font-size:10px; }
QGroupBox { background:#141c28; border:1px solid #263448; border-radius:10px; margin-top:18px; padding:16px 12px 12px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:14px; padding:0 5px; color:#a5b7ce; }
QPushButton { background:#1b2737; color:#c5d3e5; border:1px solid #304157; border-radius:8px; padding:8px 12px; font-weight:500; }
QPushButton:hover { background:#213448; border-color:#4c7d8e; color:#e6fffa; }
QPushButton:pressed { background:#254b51; }
QPushButton:disabled { background:#151f2d; border-color:#253246; color:#63748e; }
QPushButton#primary { background:#55d6c8; color:#092723; border-color:#55d6c8; font-weight:700; }
QPushButton#primary:hover { background:#7ee7db; }
QPushButton#primary:disabled { background:#1b383b; color:#6d8e93; border-color:#294a4d; }
QPushButton#danger { color:#f49aa6; background:#2a1c27; border-color:#52313e; }
QPushButton#danger:disabled { color:#826875; background:#211c28; border-color:#342b3a; }
QPushButton#record { font-size:15px; font-weight:700; }
QPushButton#disclosure { text-align:left; border:0; padding:4px 0; color:#9aaac0; font-size:11px; }
QPushButton#monitorToggle { text-align:left; color:#9fb4cd; padding:9px 13px; background:#141e2c; border-color:#263448; }
QPushButton#cameraMode { padding:5px 12px; font-size:11px; background:#141e2c; border-color:#2a394e; color:#92a5bf; }
QPushButton#cameraMode:checked { background:#163c3d; border-color:#36716f; color:#8be4d8; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background:#0e1723; border:1px solid #2b3a50; border-radius:7px; padding:7px 9px; selection-background-color:#266e6b; selection-color:#edfffd; min-height:17px; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { background:#111f2b; border-color:#4b9c9a; }
QLineEdit:disabled { color:#65768f; background:#141e2b; }
QComboBox QAbstractItemView { background:#192638; color:#dce8f7; selection-background-color:#235254; border:1px solid #34475e; }
QPlainTextEdit { background:#0d1520; border:1px solid #263448; border-radius:8px; padding:8px; font-family:monospace; font-size:11px; color:#adbed4; }
QTableWidget { background:#141c28; alternate-background-color:#182435; gridline-color:#253347; border:0; font-size:12px; }
QHeaderView::section { background:#1b293b; border:0; border-bottom:1px solid #304059; padding:7px 5px; color:#acbdd3; font-weight:500; font-size:11px; }
QTableCornerButton::section { background:#1b293b; border:0; }
QTabWidget::pane { border:0; }
QTabBar::tab { background:transparent; color:#8fa1ba; padding:10px 20px; border:0; border-bottom:2px solid transparent; font-weight:500; }
QTabBar::tab:selected { color:#70e0d2; border-bottom:2px solid #55d6c8; background:#14262e; }
QTabBar::tab:hover { color:#b0f4e9; background:#192b37; }
QTabWidget#mainTabs > QTabBar::tab { padding:9px 20px; font-size:13px; font-weight:600; }
QScrollArea { background:transparent; border:0; }
QScrollBar:vertical { width:8px; background:transparent; margin:0; }
QScrollBar::handle:vertical { background:#34475f; min-height:30px; border-radius:4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:none; }
QCheckBox { spacing:8px; background:transparent; }
QToolTip { background:#26374a; color:#e2eaf5; border:1px solid #3a5069; padding:6px; }
"""
