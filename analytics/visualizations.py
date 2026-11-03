"""
Helpers puros de presentación para el dashboard (sin dependencia de Streamlit,
para poder testearlos directamente).
"""

from typing import Dict, List, Optional, Tuple

# Estado ESPN -> (color base, traducción). Suspension se distingue de Out con
# un púrpura; cualquier otro estado usa el gris neutro.
_STATUS_STYLES = {
    "out": ("#e74c3c", "Fuera"),
    "suspension": ("#8e44ad", "Suspendido"),
    "day-to-day": ("#f1c40f", "Día a día"),
}
_NEUTRAL_STATUS_COLOR = "#95a5a6"


def health_label(score: Optional[float], data_available: bool) -> Tuple[str, str]:
    """
    Traduce el health score (0-1) a (etiqueta, color).

    Si no hay datos de lesiones el score es un 1.0 neutro, no "saludable":
    se devuelve "Sin datos" en lugar de interpretarlo.
    """
    if not data_available or score is None:
        return "Sin datos", "#95a5a6"
    if score >= 0.9:
        return "Saludable", "#00b09b"
    if score >= 0.75:
        return "Algunas bajas", "#f1c40f"
    if score >= 0.5:
        return "Bajas importantes", "#e67e22"
    return "Plantel diezmado", "#e74c3c"


def format_health(score: Optional[float], data_available: bool) -> str:
    """Texto corto para tablas/métricas: '85% (Algunas bajas)' o 'Sin datos'."""
    label, _ = health_label(score, data_available)
    if label == "Sin datos":
        return label
    return f"{score:.0%} ({label})"


def status_color(status: Optional[str]) -> str:
    """Color base (hex) de un estado de lesión; gris neutro si es desconocido."""
    key = (status or "").strip().lower()
    return _STATUS_STYLES.get(key, (_NEUTRAL_STATUS_COLOR, ""))[0]


def status_label_es(status: Optional[str]) -> str:
    """Traducción al español del estado; si es desconocido se devuelve tal cual."""
    key = (status or "").strip().lower()
    if key in _STATUS_STYLES:
        return _STATUS_STYLES[key][1]
    return status or "Sin estado"


def status_css(status: Optional[str]) -> str:
    """
    CSS para una celda de estado: fondo translúcido del color base y texto
    heredado del tema (legible en claro y oscuro, sin blanco/negro fijos).
    """
    hex_color = status_color(status).lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"background-color: rgba({r}, {g}, {b}, 0.35); font-weight: 600"


def filter_by_status(players: List[Dict], selected: List[str]) -> List[Dict]:
    """Filtra jugadores (dicts con 'status') por los estados seleccionados."""
    chosen = set(selected)
    return [p for p in players if p.get("status") in chosen]


def present_statuses(players: List[Dict]) -> List[str]:
    """Estados presentes en los datos, sin duplicados y en orden de aparición."""
    seen: List[str] = []
    for p in players:
        st_ = p.get("status")
        if st_ and st_ not in seen:
            seen.append(st_)
    return seen
