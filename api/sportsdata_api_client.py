"""
NBA API Free Data Client - RapidAPI
Endpoints reales disponibles en el plan free.

Host: nba-api-free-data.p.rapidapi.com
"""

import asyncio
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


@dataclass
class PlayerStatus:
    """Estado de un jugador (reemplaza injuries)"""
    player_id: str
    player_name: str
    team: str
    status: str        # Active, Inactive, Injured, etc.
    position: str
    jersey: str


@dataclass
class TeamRecord:
    """Record de un equipo desde RapidAPI"""
    team_id: str
    team_name: str
    wins: int
    losses: int
    win_pct: float
    conference: str
    division: str


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


class SportsDataClient:
    """Cliente para NBA API Free Data en RapidAPI"""

    BASE_URL = "https://nba-api-free-data.p.rapidapi.com"

    def __init__(
        self,
        api_key: str,
        api_host: str = "nba-api-free-data.p.rapidapi.com",
        timeout: int = 30
    ):
        self.api_key = api_key
        self.api_host = api_host
        self.timeout = timeout
        self.headers = {
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": api_host,
            "Content-Type": "application/json"
        }
        self.client = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(headers=self.headers, timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Request con reintentos automáticos."""
        if not self.client:
            self.client = httpx.AsyncClient(headers=self.headers, timeout=self.timeout)

        url = f"{self.BASE_URL}{endpoint}"
        try:
            response = await self.client.get(url, params=params)
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
        Obtiene partidos del día (Scoreboard/Get by Date).
        
        Args:
            date: Fecha en formato YYYYMMDD (default: hoy)
        """
        try:
            if not date:
                date = datetime.now().strftime("%Y%m%d")

            data = await self._make_request(
                "/nba-scoreboard-by-date",
                params={"date": date})

            games = []
            scoreboard = data.get("scoreboard", {})
            for game in scoreboard.get("games", []):
                games.append(Scoreboard(
                    game_id=game.get("gameId", ""),
                    home_team=game.get("homeTeam", {}).get("teamName", ""),
                    away_team=game.get("awayTeam", {}).get("teamName", ""),
                    home_score=game.get("homeTeam", {}).get("score", 0),
                    away_score=game.get("awayTeam", {}).get("score", 0),
                    status=game.get("gameStatusText", ""),
                    period=game.get("period", 0),
                    date=date
                ))

            logger.info(f"✓ {len(games)} partidos encontrados para {date}")
            return games

        except Exception as e:
            logger.error(f"❌ Error scoreboard: {str(e)}")
            return []

    async def get_standings(self, season: str = "2024-25") -> List[TeamRecord]:
        """
        Obtiene standings de la liga (Standings/League Standings).
        
        Args:
            season: Temporada (ej: "2024-25")
        """
        try:
            data = await self._make_request(
                "/nba-standings",
                params={"season": season, "standingType": "league"}
            )

            records = []
            for team in data.get("standings", {}).get("entries", []):
                team_data = team.get("team", {})
                stats = team.get("stats", [])

                # Extraer wins/losses de la lista de stats
                wins = next((s["value"] for s in stats if s.get("name") == "wins"), 0)
                losses = next((s["value"] for s in stats if s.get("name") == "losses"), 0)
                win_pct = next((s["value"] for s in stats if s.get("name") == "winPercent"), 0.0)

                records.append(TeamRecord(
                    team_id=str(team_data.get("id", "")),
                    team_name=team_data.get("displayName", ""),
                    wins=int(wins),
                    losses=int(losses),
                    win_pct=float(win_pct),
                    conference=team.get("standingSummary", ""),
                    division=""
                ))

            logger.info(f"✓ {len(records)} equipos en standings")
            return records

        except Exception as e:
            logger.error(f"❌ Error standings: {str(e)}")
            return []

    async def get_player_status(self, team_id: str) -> List[PlayerStatus]:
        """
        Obtiene estado de jugadores de un equipo (Player/Status).
        Útil para ver jugadores inactivos/lesionados.
        
        Args:
            team_id: ID del equipo en la API
        """
        try:
            data = await self._make_request("/nba-player-status", params={"teamId": team_id})

            players = []
            for player in data.get("playerStatus", {}).get("players", []):
                players.append(PlayerStatus(
                    player_id=str(player.get("id", "")),
                    player_name=player.get("displayName", ""),
                    team=player.get("teamName", ""),
                    status=player.get("status", {}).get("type", {}).get("description", "Active"),
                    position=player.get("position", {}).get("abbreviation", ""),
                    jersey=player.get("jersey", "")
                ))

            return players

        except Exception as e:
            logger.error(f"❌ Error player status: {str(e)}")
            return []

    async def get_team_record(self, team_id: str) -> Optional[TeamRecord]:
        """
        Obtiene record de un equipo (Team/Record).
        
        Args:
            team_id: ID del equipo
        """
        try:
            data = await self._make_request("/nba-team-record", params={"teamId": team_id})

            team = data.get("team", {})
            record = team.get("record", {}).get("items", [{}])[0]
            stats = record.get("stats", [])

            wins = next((s["value"] for s in stats if s.get("name") == "wins"), 0)
            losses = next((s["value"] for s in stats if s.get("name") == "losses"), 0)
            win_pct = next((s["value"] for s in stats if s.get("name") == "winPercent"), 0.0)

            return TeamRecord(
                team_id=str(team.get("id", "")),
                team_name=team.get("displayName", ""),
                wins=int(wins),
                losses=int(losses),
                win_pct=float(win_pct),
                conference="",
                division=""
            )

        except Exception as e:
            logger.error(f"❌ Error team record: {str(e)}")
            return None

    async def get_player_stats(self, player_id: str, season: str = "2024-25") -> Optional[Dict]:
        """
        Obtiene estadísticas de un jugador (Statistics/Player Stats).
        
        Args:
            player_id: ID del jugador
            season: Temporada
        """
        try:
            data = await self._make_request(
                "/nba-player-statistics",
                params={"playerId": player_id, "season": season}
            )
            return data

        except Exception as e:
            logger.error(f"❌ Error player stats {player_id}: {str(e)}")
            return None

    async def get_schedule(self, date: Optional[str] = None) -> List[Dict]:
        """
        Obtiene calendario de partidos (Schedule/Get by Date).
        
        Args:
            date: Fecha en formato YYYYMMDD
        """
        try:
            if not date:
                date = datetime.now().strftime("%Y%m%d")

            data = await self._make_request("/nba-schedule", params={"gameDate": date})
            return data.get("games", [])

        except Exception as e:
            logger.error(f"❌ Error schedule: {str(e)}")
            return []

    # ── Métodos de compatibilidad con api_manager.py ──────────────────────────

    async def get_player_injuries(self, season: int = 2024, team: Optional[str] = None) -> List:
        """
        Compatibilidad con api_manager. 
        Esta API no tiene endpoint de injuries — retorna lista vacía.
        Usa get_player_status() para ver jugadores inactivos.
        """
        logger.info("ℹ️ Esta API no tiene endpoint de injuries. Usa get_player_status().")
        return []

    async def get_player_availability(self, team: str, season: int = 2024) -> List:
        """Compatibilidad con api_manager — retorna lista vacía."""
        return []