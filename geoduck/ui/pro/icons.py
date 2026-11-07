# SPDX-License-Identifier: GPL-2.0-or-later
"""Iconos de Workspace Pro: SVG propios, de trazo, monocromos (workspace-pro-spec §10).

Cada icono es un `path` en una caja de 24×24 con `currentColor`; `icon(name, color)` lo pinta del color pedido
(el del texto del tema, normalmente). Sin archivos ni recursos compilados.
"""

from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtCore import QByteArray, QRectF, QSize, Qt
from qgis.PyQt.QtGui import QIcon, QPainter, QPixmap
from qgis.PyQt.QtSvg import QSvgRenderer

_STAR = "M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.8L12 16.8l-5.2 2.8 1-5.8-4.3-4.1 5.9-.8z"

#: Nombre → cuerpo SVG (dentro de un `<svg viewBox="0 0 24 24">` con trazo de 1,8).
PATHS: dict[str, str] = {
    "table": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 10v10"/>',
    "view": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18" stroke-dasharray="2 2"/>',
    "database": '<ellipse cx="12" cy="5.5" rx="7.5" ry="2.5"/>'
    '<path d="M4.5 5.5v13c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5v-13"/>'
    '<path d="M4.5 12c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5"/>',
    "sql": '<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M13.5 6l-3 12"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "filter": '<path d="M4 5h16l-6 7.5V19l-4-2v-4.5z"/>',
    "dock": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
    "sidebar": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    "window": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    "map": '<path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2z"/><path d="M9 4v14M15 6v14"/>',
    "star": f'<path d="{_STAR}" fill="currentColor"/>',
    "star-outline": f'<path d="{_STAR}"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "chevron-left": '<path d="M15 6l-6 6 6 6"/>',
    "more": '<circle cx="5" cy="12" r="1.4" fill="currentColor"/><circle cx="12" cy="12" r="1.4" '
    'fill="currentColor"/><circle cx="19" cy="12" r="1.4" fill="currentColor"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "warning": '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17.5v.5"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    "play": '<path d="M7 5l12 7-12 7z" fill="currentColor"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1.5" fill="currentColor"/>',
    "export": '<path d="M12 4v11M7.5 8.5L12 4l4.5 4.5M5 15v4h14v-4"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="M11 12l8-8M16 7l2 2"/>',
    "geometry": '<path d="M5 18l4-11 6 4 4-6"/><circle cx="5" cy="18" r="1.5" fill="currentColor"/>'
    '<circle cx="9" cy="7" r="1.5" fill="currentColor"/>'
    '<circle cx="15" cy="11" r="1.5" fill="currentColor"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/>'
    '<path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "arrow-up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "arrow-down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
    "history": '<path d="M4 12a8 8 0 1 0 2.4-5.7M4 4v5h5"/><path d="M12 8v4l3 2"/>',
    # Trazabilidad (workspace-pro-spec §9): de dónde viene cada capa
    "file": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
    "memory": '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="10" y="10" width="4" height="4"'
    ' fill="currentColor"/><path d="M10 3v3M14 3v3M10 18v3M14 18v3M3 10h3M3 14h3M18 10h3M18 14h3"/>',
    "globe": '<circle cx="12" cy="12" r="8.5"/>'
    '<path d="M3.5 12h17M12 3.5c3 3 3 14 0 17M12 3.5c-3 3-3 14 0 17"/>',
    "qgis-layers": '<path d="M12 3l9 5-9 5-9-5z" fill="currentColor"/>'
    '<path d="M3 12.5l9 5 9-5M3 16.5l9 5 9-5"/>',
}


def svg(name: str, color: str) -> bytes:
    body = PATHS[name]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '
        f'color="{color}">{body.replace("currentColor", color)}</svg>'
    ).encode()


def pixmap(name: str, color: str, size: int = 16, scale: float = 2.0) -> QPixmap:
    """El icono pintado a `size` px lógicos (nítido en pantallas de alta densidad)."""
    renderer = QSvgRenderer(QByteArray(svg(name, color)))
    pix = QPixmap(QSize(round(size * scale), round(size * scale)))
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter, QRectF(0, 0, size * scale, size * scale))
    painter.end()
    pix.setDevicePixelRatio(scale)
    return pix


def file(name: str, color: str, size: int = 12) -> str:
    """El icono como PNG en la carpeta temporal, para las hojas de estilo (`image: url(...)`), que no aceptan
    SVG en línea. Se escribe una vez por nombre, color y tamaño."""
    from qgis.PyQt.QtCore import QDir  # noqa: PLC0415

    folder = Path(QDir.tempPath()) / "geoduck-pro-icons"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}-{color.lstrip('#')}-{size}.png"
    if not path.exists():
        pixmap(name, color, size).save(str(path), "PNG")
    return path.as_posix()


def icon(name: str, color: str, size: int = 16) -> QIcon:
    return QIcon(pixmap(name, color, size))
