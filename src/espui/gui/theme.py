"""The look of the mock-up (docs/plan.html) for Qt: colours, fonts and a style sheet.

The mock-up's CSS tokens (``--bg``, ``--ink``, ``--mut``, ``--red``, ``--blue``,
``--line``, ``--soft``, ``--chrome``, ``--panel``) exist in a light and a dark
variant; the variant follows the system colour scheme, as ``color-scheme:
light dark`` does in the browser. The system font is used for the interface,
JetBrains Mono for page tabs and code, carmine for the main action.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

MONO_FAMILY = "JetBrains Mono"


@dataclass(frozen=True, slots=True)
class Theme:
    dark: bool
    bg: str
    ink: str
    mut: str
    red: str
    blue: str
    line: str
    soft: str
    chrome: str
    panel: str

    def color(self, name: str) -> QColor:
        return QColor(getattr(self, name))


LIGHT = Theme(
    dark=False,
    bg="#ffffff",
    ink="#10131a",
    mut="#596070",
    red="#c1121f",
    blue="#0b4f8a",
    line="#d9dce2",
    soft="#f2f4f7",
    chrome="#eceef2",
    panel="#fbfbfc",
)
DARK = Theme(
    dark=True,
    bg="#0f1217",
    ink="#e6e8ec",
    mut="#9aa2b1",
    red="#ff6b6f",
    blue="#79b2ec",
    line="#2a2f38",
    soft="#181c23",
    chrome="#1b1f27",
    panel="#13171d",
)
SCREEN_OUTLINE = "#3a404b"
"""Outline of an inactive page (the same in both variants, as in the mock-up)."""

_current = LIGHT


def current() -> Theme:
    return _current


def system_is_dark() -> bool:
    hints = QGuiApplication.styleHints()
    return bool(hints is not None and hints.colorScheme() == Qt.ColorScheme.Dark)


def mono_font(size: int = 12) -> QFont:
    font = QFont(MONO_FAMILY)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPixelSize(size)
    return font


def _load_mono() -> None:
    """The bundled JetBrains Mono (the same TTF the generator uses)."""
    if MONO_FAMILY in QFontDatabase.families():
        return
    path = resources.files("espui.assets").joinpath("fonts", "JetBrainsMono[wght].ttf")
    QFontDatabase.addApplicationFontFromData(path.read_bytes())


def style_sheet(t: Theme) -> str:
    return f"""
* {{ font-size: 13px; }}
QMainWindow, QDialog {{ background: {t.panel}; color: {t.ink}; }}
QWidget {{ color: {t.ink}; }}
QMenuBar {{ background: {t.panel}; border-bottom: 1px solid {t.line}; padding: 2px 8px; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; border-radius: 4px; }}
QMenuBar::item:selected {{ background: {t.soft}; }}
QMenu {{ background: {t.bg}; border: 1px solid {t.line}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {t.soft}; color: {t.ink}; }}
QMenu::item:disabled {{ color: {t.mut}; }}
QMenu::separator {{ height: 1px; background: {t.line}; margin: 4px 0; }}
QToolBar {{ background: {t.panel}; border: 0; border-bottom: 1px solid {t.line};
            padding: 6px 10px; spacing: 6px; }}
QToolBar QToolButton, QToolButton#display_button {{
    border: 1px solid {t.line}; border-radius: 6px; background: {t.bg};
    min-height: 28px; padding: 0 10px; }}
QToolBar QToolButton:hover {{ border-color: {t.mut}; }}
QToolBar QToolButton:disabled {{ color: {t.mut}; }}
QToolBar QToolButton:checked {{ background: {t.soft}; border-color: {t.blue}; color: {t.blue}; }}
QToolButton#generate {{ background: {t.red}; color: #ffffff; border: 0; font-weight: 600; }}
QToolButton#generate:hover {{ background: {t.red}; }}
QLabel#target {{ color: {t.mut}; }}
QPushButton {{ min-height: 28px; padding: 0 12px; border: 1px solid {t.line}; border-radius: 6px;
               background: {t.bg}; }}
QPushButton:hover {{ border-color: {t.mut}; }}
QPushButton:pressed {{ background: {t.soft}; }}
QPushButton:disabled {{ color: {t.mut}; }}
QPushButton[primary="true"] {{ background: {t.blue}; color: #ffffff; border: 0; font-weight: 600; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    min-height: 26px; padding: 1px 6px; border: 1px solid {t.line}; border-radius: 5px;
    background: {t.bg}; selection-background-color: {t.blue}; selection-color: #ffffff; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {t.blue}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    color: {t.mut}; background: {t.soft}; }}
QComboBox QAbstractItemView {{ background: {t.bg}; border: 1px solid {t.line};
                               selection-background-color: {t.soft}; selection-color: {t.ink}; }}
QPlainTextEdit {{ font-family: "{MONO_FAMILY}"; font-size: 11.5px; background: {t.soft}; border: 0; }}
QSlider::groove:horizontal {{ height: 4px; background: {t.line}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t.red}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; margin: -6px 0; border-radius: 7px; background: {t.red}; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}
QDockWidget {{ color: {t.mut}; font-weight: 600; font-size: 12px; }}
QDockWidget::title {{ background: {t.panel}; padding: 8px 12px 4px; border-bottom: 1px solid {t.line}; }}
QDockWidget > QWidget {{ background: {t.panel}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: {t.panel}; border: 0; }}
QListWidget {{ background: {t.panel}; border: 0; outline: 0; }}
QListWidget::item {{ padding: 4px 8px; border-radius: 6px; }}
QListWidget::item:hover {{ background: {t.soft}; }}
QListWidget::item:selected {{ background: {t.soft}; color: {t.blue}; }}
QListWidget#palette::item {{ padding: 6px 8px; }}
QTabBar {{ background: {t.chrome}; }}
QWidget#pages_bar QTabBar {{ font-family: "{MONO_FAMILY}"; font-size: 12px; }}
QWidget#pages_bar QTabBar::tab {{ color: {t.mut}; background: transparent;
                border: 1px solid transparent; border-bottom: 0; border-top-left-radius: 6px;
                border-top-right-radius: 6px; min-height: 28px; padding: 0 6px 0 12px; margin-right: 2px; }}
QWidget#pages_bar QTabBar::tab:hover {{ color: {t.ink}; }}
QWidget#pages_bar QTabBar::tab:selected {{ background: {t.panel}; border-color: {t.line}; color: {t.ink}; }}
/* Tabs of docked panels (Layers · Test values): the interface font, never cut short. */
QMainWindow > QTabBar::tab {{ color: {t.mut}; background: transparent; border: 1px solid transparent;
                border-top: 0; border-bottom-left-radius: 6px; border-bottom-right-radius: 6px;
                min-height: 26px; padding: 0 14px; margin-right: 2px; }}
QMainWindow > QTabBar::tab:hover {{ color: {t.ink}; }}
QMainWindow > QTabBar::tab:selected {{ background: {t.panel}; border-color: {t.line}; color: {t.ink}; }}
QWidget#pages_bar {{ background: {t.chrome}; border-bottom: 1px solid {t.line}; }}
QToolButton#add_page {{ border: 0; background: transparent; color: {t.blue}; font-weight: 600;
                        min-height: 28px; padding: 0 10px; }}
QToolButton#section_header {{ color: {t.mut}; font-size: 12px; font-weight: 600; border: 0;
                             background: transparent; padding: 10px 0 6px; text-align: left; }}
QFrame#rule {{ border: 1px solid {t.line}; border-radius: 6px; background: {t.bg}; }}
QFrame#rule[kind="mapping"] {{ border: 1px dashed {t.blue}; }}
QFrame#rule[active="true"] {{ border: 1px solid {t.red}; }}
QFrame#rule QLabel {{ color: {t.mut}; font-size: 12px; }}
QFrame#rule QToolButton {{ border: 0; color: {t.mut}; background: transparent; }}
QFrame#rule QToolButton:hover {{ color: {t.red}; }}
QStatusBar {{ background: {t.chrome}; color: {t.mut}; border-top: 1px solid {t.line}; font-size: 12px; }}
QStatusBar QLabel {{ color: {t.mut}; font-size: 12px; padding: 0 10px; }}
QToolTip {{ background: {t.ink}; color: {t.bg}; border: 0; padding: 6px 10px; border-radius: 6px; }}
QSplitter::handle {{ background: {t.line}; }}
QScrollBar:vertical {{ width: 10px; background: transparent; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; }}
QScrollBar::handle {{ background: {t.line}; border-radius: 5px; min-height: 24px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
"""


def apply(app: QApplication | None = None, dark: bool | None = None) -> Theme:
    """Apply the mock-up's look to the whole application; returns the variant used."""
    global _current
    app = app or QApplication.instance()  # type: ignore[assignment]
    assert app is not None
    theme = DARK if (system_is_dark() if dark is None else dark) else LIGHT
    _current = theme
    _load_mono()
    palette = QPalette()
    for role, name in (
        (QPalette.ColorRole.Window, "panel"),
        (QPalette.ColorRole.WindowText, "ink"),
        (QPalette.ColorRole.Base, "bg"),
        (QPalette.ColorRole.AlternateBase, "soft"),
        (QPalette.ColorRole.Text, "ink"),
        (QPalette.ColorRole.Button, "bg"),
        (QPalette.ColorRole.ButtonText, "ink"),
        (QPalette.ColorRole.Highlight, "blue"),
        (QPalette.ColorRole.PlaceholderText, "mut"),
        (QPalette.ColorRole.ToolTipBase, "ink"),
        (QPalette.ColorRole.ToolTipText, "bg"),
        (QPalette.ColorRole.Link, "blue"),
    ):
        palette.setColor(role, theme.color(name))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, theme.color("mut"))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, theme.color("mut")
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, theme.color("mut")
    )
    app.setPalette(palette)
    app.setStyle("Fusion")  # draws every widget from the palette and the style sheet alike
    app.setStyleSheet(style_sheet(theme))
    return theme
