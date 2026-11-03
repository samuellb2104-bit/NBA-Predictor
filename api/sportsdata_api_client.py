"""
NBA Scoreboard / Schedule Client - Datos públicos de ESPN
(site.api.espn.com), sin API key ni cuota.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
import httpx

from api.nba_api_client import resolve_team

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


# Peso de impacto por estado de lesión. ESPN no entrega importancia del
# jugador (minutos, usage), así que NO se inventa: solo se pondera el estado.
INJURY_STATUS_WEIGHT = {
    "out": 1.0,
    "suspension": 1.0,
    "day-to-day": 0.5,
}
DEFAULT_STATUS_WEIGHT = 0.5  # estados desconocidos: tratar como dudoso


@dataclass
class PlayerAvailability:
    """Jugador con reporte de lesión/suspensión"""
    player_name: str
    team_id: str          # id de equipo ESPN
    status: str           # "Out" | "Day-To-Day" | "Suspension"
    available: bool       # False solo para Out / Suspension
    impact_on_team: float  # peso por estado (ver INJURY_STATUS_WEIGHT)
    short_comment: str
    date: str


def current_season(today: Optional[datetime] = None) -> int:
    """Año en que termina la temporada en curso (oct-dic -> año+1)."""
    today = today or datetime.now()
    return today.year + 1 if today.month >= 10 else today.year


def is_current_season(season: int) -> bool:
    return season == current_season()


def parse_injuries(data: Dict) -> List[PlayerAvailability]:
    """Normaliza el payload crudo de /injuries a PlayerAvailability."""
    players: List[PlayerAvailability] = []
    for team in data.get("injuries", []):
        team_id = str(team.get("id", ""))
        for item in team.get("injuries", []):
            status = item.get("status") or "Unknown"
            key = status.strip().lower()
            athlete = item.get("athlete") or {}
            name = athlete.get("displayName") or " ".join(
                x for x in (athlete.get("firstName"), athlete.get("lastName")) if x
            )
            players.append(PlayerAvailability(
                player_name=name or "Unknown",
                team_id=team_id,
                status=status,
                available=key not in ("out", "suspension"),
                impact_on_team=INJURY_STATUS_WEIGHT.get(key, DEFAULT_STATUS_WEIGHT),
                short_comment=item.get("shortComment", ""),
                date=item.get("date", ""),
            ))
    return players


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

    INJURIES_TTL = 600  # segundos; el payload de lesiones pesa ~1MB

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self._injuries_cache = None  # (monotonic_ts, List[PlayerAvailability])
        self._injuries_lock = asyncio.Lock()

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

    # ── Lesiones (ESPN /injuries) ─────────────────────────────────────────────

    async def get_injuries(self, force_refresh: bool = False) -> List[PlayerAvailability]:
        """
        Reporte de lesiones ACTUAL de toda la liga (el endpoint no acepta
        temporada). El payload pesa ~1MB, así que se cachea INJURIES_TTL
        segundos en el cliente. Lanza excepción si la petición falla, para
        que el llamador distinga "sin lesiones" de "sin datos".
        """
        if not force_refresh and self._injuries_fresh():
            return self._injuries_cache[1]

        async with self._injuries_lock:
            # Otra corrutina pudo refrescar mientras esperábamos el lock.
            if not force_refresh and self._injuries_fresh():
                return self._injuries_cache[1]
            data = await self._make_request("/injuries")
            players = parse_injuries(data)
            self._injuries_cache = (time.monotonic(), players)
            logger.info(f"✓ {len(players)} lesiones en la liga")
            return players

    def _injuries_fresh(self) -> bool:
        return (
            self._injuries_cache is not None
            and time.monotonic() - self._injuries_cache[0] < self.INJURIES_TTL
        )

    async def get_player_availability(
        self, team: str, season: Optional[int] = None
    ) -> List[PlayerAvailability]:
        """
        Jugadores lesionados de un equipo (cualquier identificador que
        acepte resolve_team). Devuelve [] para temporadas que no son la
        actual: ESPN solo publica lesiones vigentes; usar
        is_current_season(season) para distinguir "sin datos" de "sin
        lesiones". Propaga el error si la petición falla.
        """
        if season is not None and not is_current_season(season):
            return []
        info = resolve_team(team)
        if info is None:
            return []
        return [p for p in await self.get_injuries() if p.team_id == info.id]
