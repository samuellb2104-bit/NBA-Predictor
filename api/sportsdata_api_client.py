"""
NBA Scoreboard / Schedule Client - Datos públicos de ESPN
(site.api.espn.com), sin API key ni cuota.
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
import httpx

logger = logging.getLogger(__name__)


@dataclass
class Scoreboard:
    """Partido del scoreboard"""
    game_id: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    status: str
    period: int
    date: str


def _extract_score(value) -> int:
    """El campo score de ESPN a veces es un número plano y a veces un
    dict {value, displayValue} según el endpoint — se normaliza acá."""
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _event_to_scoreboard(event: Dict) -> Optional[Scoreboard]:
    """Convierte un 'event' crudo de ESPN (scoreboard o schedule, misma
    forma) a Scoreboard. None si el evento no trae competición."""
    competitions = event.get("competitions", [])
    if not competitions:
        return None

    comp = competitions[0]
    competitors = comp.get("competitors", [])
    home = next((c for c in competitors if c.get("homeAway") == "home"), {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), {})
    status = comp.get("status", {})

    raw_date = event.get("date", "")  # ej. "2025-02-01T22:00Z"
    date_str = raw_date[:10].replace("-", "") if raw_date else ""

    return Scoreboard(
        game_id=event.get("id", ""),
        home_team=home.get("team", {}).get("displayName", ""),
        away_team=away.get("team", {}).get("displayName", ""),
        home_score=_extract_score(home.get("score")),
        away_score=_extract_score(away.get("score")),
        status=status.get("type", {}).get("description", ""),
        period=status.get("period", 0),
        date=date_str,
    )


class SportsDataClient:
    """Cliente de scoreboard/calendario NBA usando la API pública de ESPN."""

    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    async def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        url = f"{self.BASE_URL}{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
            logger.info(f"✓ {endpoint}")
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"✗ HTTP {e.response.status_code}: {endpoint}")
            raise
        except Exception as e:
            logger.error(f"✗ Error: {str(e)}")
            raise

    async def get_scoreboard(self, date: Optional[str] = None) -> List[Scoreboard]:
        """
        Obtiene partidos del día.

        Args:
            date: Fecha en formato YYYYMMDD (default: hoy)
        """
        try:
            if not date:
                date = datetime.now().strftime("%Y%m%d")

            data = await self._make_request("/scoreboard", params={"dates": date})

            games = [
                g for e in data.get("events", [])
                if (g := _event_to_scoreboard(e)) is not None
            ]
            # El campo date del evento es la fecha real del partido; se
            # sobreescribe con la fecha consultada para partidos sin ella.
            for g in games:
                g.date = g.date or date

            logger.info(f"✓ {len(games)} partidos encontrados para {date}")
            return games

        except Exception as e:
            logger.error(f"❌ Error scoreboard: {str(e)}")
            return []

    async def get_team_recent_games(
        self,
        team_id: str,
        season: int,
        limit: int = 10
    ) -> List[Scoreboard]:
        """
        Últimos partidos jugados de un equipo en una temporada, incluso si
        ya terminó — una sola petición trae el calendario completo, así
        que no hace falta escanear día por día.

        Args:
            team_id: ID de equipo de ESPN (ver TEAM_NAME_TO_ID en
                nba_api_client.py), no el nombre.
            season: Año en que termina la temporada (ej. 2025 -> 2024-25).
            limit: Cantidad de partidos a devolver.
        """
        try:
            data = await self._make_request(
                f"/teams/{team_id}/schedule",
                params={"season": season}
            )

            games = []
            for event in data.get("events", []):
                completions = event.get("competitions", [{}])
                completed = completions[0].get("status", {}).get("type", {}).get("completed")
                if not completed:
                    continue
                g = _event_to_scoreboard(event)
                if g:
                    games.append(g)

            games.sort(key=lambda g: g.date, reverse=True)
            return games[:limit]

        except Exception as e:
            logger.error(f"❌ Error obteniendo calendario del equipo {team_id}: {str(e)}")
            return []

    # ── Métodos de compatibilidad con api_manager.py ──────────────────────────

    async def get_player_injuries(self, season: int = 2024, team: Optional[str] = None) -> List:
        """Esta fuente no tiene endpoint de injuries — retorna lista vacía."""
        logger.info("ℹ️ Esta fuente no tiene endpoint de injuries.")
        return []

    async def get_player_availability(self, team: str, season: int = 2024) -> List:
        """Compatibilidad con api_manager — retorna lista vacía."""
        return []
