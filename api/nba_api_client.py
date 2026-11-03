"""
NBA API Client - Datos públicos de ESPN (site.api.espn.com).

No es una API oficial documentada, pero es de acceso libre (sin API key,
sin cuota).
"""

import asyncio
import logging
import httpx
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

TEAM_NAME_TO_ID = {
    "Lakers": "13", "Celtics": "2", "Heat": "14", "Nuggets": "7",
    "Warriors": "9", "Bucks": "15", "Suns": "21", "Clippers": "12",
    "76ers": "20", "Nets": "17", "Knicks": "18", "Bulls": "4",
    "Cavaliers": "5", "Hawks": "1", "Hornets": "3", "Pistons": "8",
    "Pacers": "11", "Magic": "19", "Wizards": "27", "Raptors": "28",
    "Mavericks": "6", "Rockets": "10", "Grizzlies": "29", "Pelicans": "16",
    "Spurs": "22", "Thunder": "25", "Trail Blazers": "23", "Jazz": "26",
    "Kings": "24", "Timberwolves": "30",
}

# Nombre -> abreviatura de ESPN (la que devuelve el endpoint de standings).
TEAM_NAME_TO_ABBR = {
    "Hawks": "ATL", "Celtics": "BOS", "Nets": "BKN", "Hornets": "CHA",
    "Bulls": "CHI", "Cavaliers": "CLE", "Mavericks": "DAL", "Nuggets": "DEN",
    "Pistons": "DET", "Warriors": "GS", "Rockets": "HOU", "Pacers": "IND",
    "Clippers": "LAC", "Lakers": "LAL", "Grizzlies": "MEM", "Heat": "MIA",
    "Bucks": "MIL", "Timberwolves": "MIN", "Pelicans": "NO", "Knicks": "NY",
    "Thunder": "OKC", "Magic": "ORL", "76ers": "PHI", "Suns": "PHX",
    "Trail Blazers": "POR", "Spurs": "SA", "Kings": "SAC", "Raptors": "TOR",
    "Jazz": "UTAH", "Wizards": "WSH",
}

# Abreviaturas ESPN en orden alfabético: fuente única para la lista de 30 equipos.
TEAM_ABBREVIATIONS = sorted(TEAM_NAME_TO_ABBR.values())

# Alias comunes (otras convenciones de abreviatura) -> abreviatura ESPN.
TEAM_ALIASES = {
    "GSW": "GS", "NOP": "NO", "NYK": "NY", "SAS": "SA", "UTA": "UTAH",
    "WAS": "WSH", "PHO": "PHX", "BRK": "BKN", "CHO": "CHA",
    "SIXERS": "PHI", "BLAZERS": "POR",
}


@dataclass(frozen=True)
class TeamInfo:
    name: str    # "Lakers"
    abbr: str    # abreviatura ESPN, "LAL"
    id: str      # id de ESPN, "13"


def _norm(value: str) -> str:
    return " ".join(str(value).strip().lower().split())


_TEAMS: List[TeamInfo] = [
    TeamInfo(name, TEAM_NAME_TO_ABBR[name], tid)
    for name, tid in TEAM_NAME_TO_ID.items()
]
_TEAM_LOOKUP: Dict[str, TeamInfo] = {}
for _t in _TEAMS:
    _TEAM_LOOKUP[_norm(_t.name)] = _t
    _TEAM_LOOKUP[_norm(_t.abbr)] = _t
    _TEAM_LOOKUP[_norm(_t.id)] = _t
for _alias, _abbr in TEAM_ALIASES.items():
    _TEAM_LOOKUP[_norm(_alias)] = _TEAM_LOOKUP[_norm(_abbr)]


def resolve_team(team) -> Optional[TeamInfo]:
    """
    Resuelve un equipo a TeamInfo desde nombre ("Lakers"), nombre completo
    ("Los Angeles Lakers"), abreviatura ESPN ("LAL", "GS"), alias ("GSW")
    o id ("13"). Sin distinguir mayúsculas. Devuelve None si no existe.
    """
    if team is None:
        return None
    key = _norm(team)
    if not key:
        return None
    if key in _TEAM_LOOKUP:
        return _TEAM_LOOKUP[key]
    # Nombre completo: "Los Angeles Lakers" termina con el nombre del equipo.
    for t in _TEAMS:
        if key.endswith(" " + _norm(t.name)):
            return t
    return None


STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"


class NBAApiClient:
    """Cliente de standings/stats de equipo usando la API pública de ESPN."""

    def __init__(self, season: str = "2024-25"):
        self.season = season
        self._standings_cache: Dict[int, List[Dict]] = {}
        logger.info(f"✓ NBAApiClient inicializado (season: {season})")

    def _run(self, coro):
        """Ejecuta coroutine sincrónicamente."""
        try:
            return asyncio.run(coro)
        except RuntimeError:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()

    async def _make_request(self, url: str, params: Optional[Dict] = None) -> Dict:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    def get_standings(self, season: int = 2024) -> List[Dict]:
        """Obtiene standings de ambas conferencias vía ESPN."""
        async def _fetch():
            return await self._make_request(STANDINGS_URL, params={"season": str(season)})

        try:
            data = self._run(_fetch())
            if not data:
                return []

            result = []
            for conference in data.get("children", []):
                entries = conference.get("standings", {}).get("entries", [])

                for entry in entries:
                    team_info = entry.get("team", {})
                    stats = entry.get("stats", [])

                    def get_stat(name, stats=stats):
                        return next((s.get("value", 0) for s in stats if s.get("name") == name), 0)

                    wins = int(get_stat("wins"))
                    losses = int(get_stat("losses"))
                    total = wins + losses
                    win_pct = round(wins / total, 3) if total > 0 else 0.0
                    ppg = float(get_stat("avgPointsFor"))
                    streak = next((s.get("displayValue", "") for s in stats if s.get("name") == "streak"), "")

                    result.append({
                        "team": team_info.get("displayName", ""),
                        "abbreviation": team_info.get("abbreviation", ""),
                        "team_id": team_info.get("id", ""),
                        "conference": conference.get("abbreviation", ""),
                        "wins": wins,
                        "losses": losses,
                        "win_pct": win_pct,
                        "points": ppg,
                        "streak": streak,
                    })

            # Guardar en caché para get_team_stats
            self._standings_cache[season] = result
            logger.info(f"✓ Standings: {len(result)} equipos")
            return result

        except Exception as e:
            logger.error(f"❌ Error standings: {str(e)}")
            return []

    def get_team_stats(self, team: str, season: int = 2024) -> Optional[Dict]:
        """Obtiene stats del equipo desde standings."""
        # Cargar standings si no están en caché
        if not self._standings_cache.get(season):
            self.get_standings(season)

        standings = self._standings_cache.get(season)
        if not standings:
            return None

        info = resolve_team(team)
        if info is None:
            logger.warning(f"⚠️ Equipo desconocido: {team}")
            return None

        entry = next(
            (e for e in standings
             if e.get("team_id") == info.id or e.get("abbreviation") == info.abbr),
            None
        )

        if not entry:
            logger.warning(f"⚠️ No encontrado en standings: {team}")
            return None

        return {
            "team": team,
            "season": season,
            "wins": entry["wins"],
            "losses": entry["losses"],
            "win_pct": entry["win_pct"],
            "points": entry.get("points", 0.0),
            "assists": 0.0,
            "rebounds": 0.0,
            "fg_pct": 0.0,
            "fg3_pct": 0.0,
            "ft_pct": 0.0,
        }
