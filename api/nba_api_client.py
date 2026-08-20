"""
NBA API Client - Datos públicos de ESPN (site.api.espn.com).

No es una API oficial documentada, pero es de acceso libre (sin API key,
sin cuota) y es la misma fuente que usan servicios de terceros como
RapidAPI "NBA Free Data" por debajo.
"""

import asyncio
import logging
import httpx
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

TEAM_NAME_TO_ID = {
    "Lakers": "13", "Celtics": "2", "Heat": "14", "Nuggets": "7",
    "Warriors": "9", "Bucks": "15", "Suns": "21", "Clippers": "12",
    "76ers": "20", "Nets": "17", "Knicks": "18", "Bulls": "4",
    "Cavaliers": "5", "Hawks": "1", "Hornets": "3", "Pistons": "8",
    "Pacers": "11", "Magic": "19", "Wizards": "27", "Raptors": "28",
    "Mavericks": "6", "Rockets": "10", "Grizzlies": "29", "Pelicans": "16",
    "Spurs": "22", "Thunder": "33", "Trail Blazers": "23", "Jazz": "26",
    "Kings": "24", "Timberwolves": "30",
}

STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"


class NBAApiClient:
    """Cliente de standings/stats de equipo usando la API pública de ESPN."""

    def __init__(self, season: str = "2024-25"):
        self.season = season
        self._standings_cache: Optional[List[Dict]] = None
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
            self._standings_cache = result
            logger.info(f"✓ Standings: {len(result)} equipos")
            return result

        except Exception as e:
            logger.error(f"❌ Error standings: {str(e)}")
            return []

    def get_team_stats(self, team: str, season: int = 2024) -> Optional[Dict]:
        """Obtiene stats del equipo desde standings."""
        # Cargar standings si no están en caché
        if not self._standings_cache:
            self.get_standings(season)

        if not self._standings_cache:
            return None

        team_id = TEAM_NAME_TO_ID.get(team)
        entry = next(
            (e for e in self._standings_cache
             if e.get("team_id") == team_id or team.lower() in e.get("team", "").lower()),
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

    def get_recent_games(self, team: str, season: int = 2024, limit: int = 10) -> List[Dict]:
        """No disponible aquí — ver SportsDataClient.get_team_recent_games."""
        logger.info(f"ℹ️ get_recent_games no disponible para {team}")
        return []

    def get_all_teams(self) -> List[Dict]:
        return [{"name": k, "id": v} for k, v in TEAM_NAME_TO_ID.items()]
