"""Original line-icon set (24 px grid, rounded 1.75 px strokes) rendered to QIcon and tinted per theme."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Each entry is the inner SVG markup. `currentColor` is replaced with the requested tint.
_GLYPHS: dict[str, str] = {
    # file and history
    "open": '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2.5h7.5A2.5 2.5 0 0 1 21 10v7.5a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/>',
    "save": '<path d="M5 3.5h11l3.5 3.5v11.5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2z"/><path d="M7.5 3.5v4.5h7V3.5"/><path d="M7 20.5v-6h10v6"/>',
    "print": '<path d="M7 8.5V3.5h10v5"/><path d="M7 17.5H5a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="7" y="14" width="10" height="6.5" rx="1"/>',
    "undo": '<path d="M8.5 13.5 4 9l4.5-4.5"/><path d="M4 9h9.5a6 6 0 0 1 0 12H10"/>',
    "redo": '<path d="m15.5 13.5 4.5-4.5-4.5-4.5"/><path d="M20 9h-9.5a6 6 0 0 0 0 12H14"/>',
    "new": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M12 11.5v6M9 14.5h6"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/>',
    "images": '<rect x="3" y="5" width="14" height="14" rx="2"/><path d="M21 8v10a2 2 0 0 1-2 2H8"/><circle cx="8" cy="10" r="1.4"/><path d="m17 15-3.5-3.5L6 19"/>',
    "batch": '<rect x="7" y="3" width="13" height="13" rx="2"/><path d="M4 8v10a2 2 0 0 0 2 2h10"/><path d="M11 9.5h5M11 12.5h3"/>',
    # navigation and view
    "chevron-left": '<path d="m14.5 6-6 6 6 6"/>',
    "chevron-right": '<path d="m9.5 6 6 6-6 6"/>',
    "chevron-up": '<path d="m6 14.5 6-6 6 6"/>',
    "chevron-down": '<path d="m6 9.5 6 6 6-6"/>',
    "chevrons-left": '<path d="m12 6-6 6 6 6M18 6l-6 6 6 6"/>',
    "chevrons-right": '<path d="m6 6 6 6-6 6M12 6l6 6-6 6"/>',
    "minus": '<path d="M5.5 12h13"/>',
    "plus": '<path d="M12 5.5v13M5.5 12h13"/>',
    "fit-width": '<path d="M3.5 5v14M20.5 5v14"/><path d="M8 12h8M10.5 9 8 12l2.5 3M13.5 9 16 12l-2.5 3"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m20 20-4.9-4.9"/>',
    "arrow-down": '<path d="M12 4.5v15M6 13.5l6 6 6-6"/>',
    "arrow-up": '<path d="M12 19.5v-15M6 10.5l6-6 6 6"/>',
    "close": '<path d="m6 6 12 12M18 6 6 18"/>',
    "panel-left": '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M9.5 4.5v15"/>',
    "panel-right": '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M14.5 4.5v15"/>',
    "pages": '<rect x="4" y="3.5" width="9" height="12" rx="1.5"/><path d="M8 19.5h8.5a2 2 0 0 0 2-2V8"/>',
    "bookmark": '<path d="M6.5 3.5h11v17L12 16.5l-5.5 4z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4"/>',
    "moon": '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/>',
    "monitor": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8.5 20h7M12 16v4"/>',
    "lock-small": '<rect x="5.5" y="11" width="13" height="9.5" rx="2"/><path d="M8.5 11V8a3.5 3.5 0 0 1 7 0v3"/>',
    "drop": '<path d="M12 4v10M8 10.5l4 4 4-4"/><path d="M4.5 15v2.5a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V15"/>',
    # tools: read and edit
    "select": '<path d="M9 4.5h6M9 19.5h6M12 4.5v15"/>',
    "hand": '<path d="M8.5 12.5V6a1.5 1.5 0 0 1 3 0v5M11.5 10.5V4.5a1.5 1.5 0 0 1 3 0v6M14.5 10.5V6.5a1.5 1.5 0 0 1 3 0v7c0 4-2.6 7-6.5 7-2.7 0-4.4-1.1-5.8-3.2l-2-3.1a1.5 1.5 0 0 1 2.4-1.8l1.9 2.1"/>',
    "edit": '<path d="M5.5 4.5 11 19.5l2.3-6.2 6.2-2.3z"/><path d="m13.8 13.8 4.7 4.7"/>',
    "text": '<path d="M5 7V4.5h14V7M12 4.5v15M9 19.5h6"/>',
    "replace": '<path d="M4 7V4.5h11V7M9.5 4.5V14"/><path d="M13 20l.7-2.8 5.7-5.7a1.6 1.6 0 0 1 2.2 2.2l-5.7 5.7z"/>',
    "image": '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><circle cx="9" cy="10" r="1.7"/><path d="m21 16-5-5L7 19.5"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    # tools: review
    "highlight": '<path d="m14.5 4.5 5 5-8.5 8.5H6.5v-4.5z"/><path d="M4 21h8"/>',
    "underline": '<path d="M7 4v7a5 5 0 0 0 10 0V4"/><path d="M5 20.5h14"/>',
    "strikeout": '<path d="M16.5 7.5c-.6-2-2.4-3-4.6-3-2.4 0-4.1 1.2-4.1 3 0 4.2 8.6 2.7 8.6 6.7 0 1.9-1.9 3.3-4.4 3.3-2.5 0-4.3-1.1-4.8-3.1"/><path d="M4 12h16"/>',
    "note": '<path d="M4 6a2.5 2.5 0 0 1 2.5-2.5h11A2.5 2.5 0 0 1 20 6v8.5a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 3.5V17A2.5 2.5 0 0 1 4 14.5z"/><path d="M8 8.5h8M8 12h5"/>',
    "ink": '<path d="M3.5 15.5c2.2-7 4-9.5 5.2-9.5 1.8 0-.5 8.5 1.8 8.5 1.6 0 2.1-3.5 3.7-3.5 1.4 0 1.4 2.5 3 2.5.9 0 1.6-.6 2.3-1.5"/><path d="M3.5 20.5h17"/>',
    "rectangle": '<rect x="4" y="5.5" width="16" height="13" rx="2.5"/>',
    "line": '<path d="M5 19 19 5"/><circle cx="5" cy="19" r="1.6"/><circle cx="19" cy="5" r="1.6"/>',
    "arrow": '<path d="M4.5 19.5 18.5 5.5"/><path d="M9.5 5.5h9v9"/>',
    "freetext": '<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="M8.5 9.5h7M12 9.5v6"/>',
    "measure": '<rect x="3" y="8.5" width="18" height="7" rx="1.8" transform="rotate(-30 12 12)"/><path d="m8.2 11.3 1.3 2.2m2.1-3.6 1.3 2.2m2.1-3.6 1.3 2.2"/>',
    "ellipse": '<ellipse cx="12" cy="12" rx="8.5" ry="6.5"/>',
    # tools: forms and security
    "field": '<rect x="3" y="7" width="18" height="10" rx="2.5"/><path d="M7.5 10.5v3"/>',
    "fill": '<path d="M4 20h4.5L19 9.5a2.1 2.1 0 0 0-3-3L5.5 17z"/><path d="M14.5 6.5l3 3"/><path d="M4 20.5h16"/>',
    "redact": '<rect x="3" y="9.5" width="18" height="5.5" rx="1.2" fill="currentColor"/><path d="M5 5.5h8M5 19h11"/>',
    "crop": '<path d="M6.5 2.5v13a2 2 0 0 0 2 2h13M2.5 6.5h13a2 2 0 0 1 2 2v13"/>',
    # document actions
    "merge": '<path d="M7 4h7l4 4v8a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/><path d="M14 4v4h4"/><path d="M9 21.5h8.5a3 3 0 0 0 3-3V11"/>',
    "rotate": '<rect x="3.5" y="7.5" width="9" height="13" rx="1.5"/><path d="M15.5 4.5a7 7 0 0 1 5 6.5"/><path d="M20.5 3.5v4.5H16"/>',
    "forms": '<rect x="5" y="4" width="14" height="17" rx="2.5"/><path d="M9 3h6v3.5H9z"/><path d="m9 14 2 2 4-4.5"/>',
    "redactions": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M8.5 15h7" stroke-width="3.5"/>',
    "ocr": '<path d="M4 8V6.5A2.5 2.5 0 0 1 6.5 4H8M16 4h1.5A2.5 2.5 0 0 1 20 6.5V8M20 16v1.5a2.5 2.5 0 0 1-2.5 2.5H16M8 20H6.5A2.5 2.5 0 0 1 4 17.5V16"/><path d="M8 9.5h8M8 12.5h8M8 15.5h4.5"/>',
    "export": '<path d="M12 15V3.5M7.5 8 12 3.5 16.5 8"/><path d="M4.5 14v4.5a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V14"/>',
    "protect": '<rect x="5" y="11" width="14" height="9.5" rx="2.5"/><path d="M8 11V7.5a4 4 0 0 1 8 0V11"/>',
    # document tools
    "header-footer": '<rect x="5" y="3.5" width="14" height="17" rx="2.5"/><path d="M5 8.5h14M5 15.5h14M9 12h6"/>',
    "bates": '<path d="M8 4.5H4.5v15H8M16 4.5h3.5v15H16"/><path d="M10.5 9h3M10.5 12h3M10.5 15h3"/>',
    "redact-search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m20 20-4.9-4.9"/><rect x="7" y="9.2" width="7" height="2.6" rx=".9" fill="currentColor"/>',
    "optimize": '<path d="M4 4l5.5 5.5M9.5 4.8v4.7H4.8"/><path d="M20 20l-5.5-5.5M14.5 19.2v-4.7h4.7"/>',
    "flatten": '<path d="m12 3.5 8.5 4.5-8.5 4.5L3.5 8z"/><path d="m3.5 12 8.5 4.5 8.5-4.5"/><path d="m3.5 16 8.5 4.5 8.5-4.5"/>',
    "page-labels": '<path d="M3.5 4.5a1 1 0 0 1 1-1h7.2a1 1 0 0 1 .7.3l8 8a1 1 0 0 1 0 1.4l-7 7a1 1 0 0 1-1.4 0l-8-8a1 1 0 0 1-.3-.7z"/><circle cx="8" cy="8" r="1.3"/>',
    "insert-page": '<path d="M13 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4.5"/><path d="M13 3l5 5v3.5"/><path d="M13 3v5h5"/><path d="M17.5 15v6M14.5 18h6"/>',
    "stamp": '<path d="M9 3.5h6v4.2c0 1.6 2.5 2 2.5 4.3v2.5h-11V12c0-2.3 2.5-2.7 2.5-4.3z"/><path d="M5 18h14M6 21h12"/>',
    "check": '<path d="M12 3.5 5 6v5.5c0 4.3 2.8 7.6 7 9 4.2-1.4 7-4.7 7-9V6z"/><path d="m9 12 2.2 2.2L15.5 10"/>',
    # text alignment (format bar)
    "align-left": '<path d="M4 6h16M4 10h10M4 14h16M4 18h10"/>',
    "align-center": '<path d="M4 6h16M7 10h10M4 14h16M7 18h10"/>',
    "align-right": '<path d="M4 6h16M10 10h10M4 14h16M10 18h10"/>',
    "align-justify": '<path d="M4 6h16M4 10h16M4 14h16M4 18h16"/>',
    "compare-text":'<rect x="3" y="4.5" width="7.5" height="15" rx="1.5"/><rect x="13.5" y="4.5" width="7.5" height="15" rx="1.5"/><path d="M5.5 9h2.5M5.5 12h2.5M16 9h2.5M16 15h2.5"/>',
}

_ALIASES = {"saveas": "save", "editpdf": "edit", "blank": "new", "about": "file"}

APP_MARK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">'
    '<rect x="16" y="16" width="224" height="224" rx="52" fill="#14283e"/>'
    '<path d="M70 48h79l39 39v120H70z" fill="#f3f7fb"/><path d="M149 48v39h39z" fill="#adc8da"/>'
    '<path d="M90 112h66M90 132h45M90 152h32" stroke="#49718a" stroke-width="9" stroke-linecap="round"/>'
    '<path d="M127 180l12-33 42-42 21 21-42 42z" fill="#38ccb2"/><path d="M127 180l12-33 21 21z" fill="#1d776a"/>'
    '<path d="M174 112l21 21" stroke="#14283e" stroke-width="5"/></svg>'
)

SIZES = (16, 20, 24, 32, 40, 48, 64)
STROKE = 1.75

# Colours used when an icon is requested by tone; refreshed by set_palette() on a theme change.
_PALETTE = {"ink": "#1B2326", "muted": "#4F5B5F", "disabled": "#8A9498", "accent": "#0A7A6C", "onaccent": "#FFFFFF"}
_cache: dict[tuple, QIcon] = {}


def names() -> list[str]:
    return sorted(_GLYPHS)


def set_palette(tokens: dict[str, str]) -> None:
    _PALETTE.update(ink=tokens["ink"], muted=tokens["inkmuted"], disabled=tokens["inkdisabled"],
                    accent=tokens["accent"], onaccent=tokens["onaccent"])
    _cache.clear()


def svg(name: str, color: str, stroke: float = STROKE) -> str:
    inner = _GLYPHS[_ALIASES.get(name, name)].replace("currentColor", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{inner}</svg>')


def _render(markup: str, size: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(markup.encode("utf-8")))
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return QPixmap.fromImage(image)


def pixmap(name: str, color: str, size: int = 24, ratio: float = 1.0) -> QPixmap:
    pix = _render(svg(name, color), max(1, round(size * ratio)))
    pix.setDevicePixelRatio(ratio)
    return pix


def themed_icon(name: str, tone: str = "ink", checked: str | None = None) -> QIcon:
    """Icon tinted from the active palette. `tone` is the resting colour; `checked` (a tone) is used for the On state."""
    key = (name, tone, checked)
    if key not in _cache:
        normal, disabled, accent = _PALETTE[tone], _PALETTE["disabled"], _PALETTE["accent"]
        hover = _PALETTE["ink"]
        icon = QIcon()
        for size in SIZES:
            icon.addPixmap(_render(svg(name, normal), size), QIcon.Mode.Normal, QIcon.State.Off)
            icon.addPixmap(_render(svg(name, hover), size), QIcon.Mode.Active, QIcon.State.Off)
            icon.addPixmap(_render(svg(name, accent), size), QIcon.Mode.Selected, QIcon.State.Off)
            icon.addPixmap(_render(svg(name, disabled), size), QIcon.Mode.Disabled, QIcon.State.Off)
            if checked:
                on = _PALETTE[checked]
                for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected):
                    icon.addPixmap(_render(svg(name, on), size), mode, QIcon.State.On)
                icon.addPixmap(_render(svg(name, disabled), size), QIcon.Mode.Disabled, QIcon.State.On)
        _cache[key] = icon
    return _cache[key]


def tinted_icon(name: str, color: str, disabled: str | None = None) -> QIcon:
    """Icon in an explicit colour (for example, white on the primary button)."""
    icon = QIcon()
    for size in SIZES:
        icon.addPixmap(_render(svg(name, color), size), QIcon.Mode.Normal)
        icon.addPixmap(_render(svg(name, disabled or _PALETTE["disabled"]), size), QIcon.Mode.Disabled)
    return icon


def app_mark(size: int = 96, ratio: float = 1.0) -> QPixmap:
    pix = _render(APP_MARK_SVG, max(1, round(size * ratio)))
    pix.setDevicePixelRatio(ratio)
    return pix


__all__ = ["names", "set_palette", "svg", "pixmap", "themed_icon", "tinted_icon", "app_mark", "QColor"]
