"""
Helpers puros de presentación para el dashboard (sin dependencia de Streamlit,
para poder testearlos directamente).
"""

from typing import Optional, Tuple


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
