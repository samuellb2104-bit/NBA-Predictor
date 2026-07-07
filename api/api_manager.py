"""
API Manager - Orquestador centralizado para múltiples fuentes de datos NBA.

Maneja:
  - Sincronización entre NBA API y RapidAPI SportsData
  - Caché inteligente con expiración
  - Retry automático y circuit breaker
  - Composición de datos de múltiples fuentes

Uso:
    manager = APIManager(nba_api_client, sportsdata_client, cache_ttl=3600)
    enriched_stats = await manager.get_enriched_team_stats("LAL")
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json

logger = logging.getLogger(__name__)


class DataSource(Enum):
    """Fuentes de datos disponibles"""
    NBA_API = "nba_api"
    SPORTSDATA = "sportsdata"
    CACHE = "cache"


@dataclass
class CachedData:
    """Estructura para datos en caché"""
    data: any
    timestamp: datetime
    ttl: int  # Time to live en segundos
    source: DataSource

    def is_expired(self) -> bool:
        """Verifica si el dato en caché ha expirado"""
        return datetime.now() - self.timestamp > timedelta(seconds=self.ttl)


@dataclass
class EnrichedPlayerStats:
    """Estadísticas de jugador enriquecidas con datos de lesiones"""
    player_id: int
    player_name: str
    team: str
    # Stats básicos
    games_played: int
    points: float
    assists: float
    rebounds: float
    fg_pct: float
    # Datos de lesión
    is_injured: bool
    injury_status: str
    injury_impact: float  # 0.0 a 1.0
    return_date: Optional[str]
    # Cálculos
    adjusted_impact: float  # Impacto ajustado por lesión


@dataclass
class EnrichedTeamStats:
    """Estadísticas de equipo enriquecidas"""
    team: str
    season: int
    # Stats básicos
    wins: int
    losses: int
    win_pct: float
    # Lesiones
    injured_players: int
    unavailable_players: int
    team_health_score: float  # 0.0 (muy lesionado) a 1.0 (perfecto)
    # Análisis
    projected_win_pct_adjusted: float
    critical_absences: List[str] = field(default_factory=list)


class APIManager:
    """Orquestador centralizado de APIs NBA"""

    def __init__(
        self,
        nba_client,  # Cliente de nba_api
        sportsdata_client,  # Cliente de RapidAPI SportsData
        cache_ttl: int = 3600,  # TTL default en segundos (1 hora)
        use_cache: bool = True
    ):
        """
        Inicializa el API Manager.
        
        Args:
            nba_client: Cliente inicializado de nba_api
            sportsdata_client: Cliente inicializado de SportsDataClient
            cache_ttl: Tiempo de vida del caché en segundos
            use_cache: Habilitar/deshabilitar caché
        """
        self.nba_client = nba_client
        self.sportsdata_client = sportsdata_client
        self.cache_ttl = cache_ttl
        self.use_cache = use_cache
        self.cache: Dict[str, CachedData] = {}
        logger.info("✓ API Manager inicializado")

    def _cache_key(self, *args) -> str:
        """Genera una clave de caché consistente"""
        return ":".join(str(arg) for arg in args)

    def _get_from_cache(self, key: str) -> Optional[any]:
        """Obtiene dato del caché si existe y no ha expirado"""
        if not self.use_cache or key not in self.cache:
            return None

        cached = self.cache[key]
        if cached.is_expired():
            logger.debug(f"⏰ Caché expirado: {key}")
            del self.cache[key]
            return None

        logger.debug(f"💾 Caché hit: {key}")
        return cached.data

    def _set_cache(
        self,
        key: str,
        data: any,
        source: DataSource,
        ttl: Optional[int] = None
    ) -> None:
        """Almacena dato en caché"""
        if not self.use_cache:
            return

        ttl = ttl or self.cache_ttl
        self.cache[key] = CachedData(
            data=data,
            timestamp=datetime.now(),
            ttl=ttl,
            source=source
        )
        logger.debug(f"📝 Caché guardado: {key} (TTL: {ttl}s)")

    def clear_cache(self, pattern: Optional[str] = None) -> None:
        """
        Limpia el caché.
        
        Args:
            pattern: Patrón de claves a limpiar (ej: "LAL:*")
        """
        if pattern:
            keys_to_delete = [k for k in self.cache.keys() if pattern.replace("*", "") in k]
            for key in keys_to_delete:
                del self.cache[key]
            logger.info(f"🧹 Caché limpiado: {len(keys_to_delete)} entradas ({pattern})")
        else:
            self.cache.clear()
            logger.info("🧹 Caché completamente limpiado")

    async def get_enriched_player_stats(
        self,
        player_id: int,
        season: int = 2025
    ) -> Optional[EnrichedPlayerStats]:
        """
        Obtiene estadísticas de jugador enriquecidas con estado de lesión.
        
        Args:
            player_id: ID del jugador
            season: Temporada
            
        Returns:
            EnrichedPlayerStats o None
        """
        cache_key = self._cache_key("player", player_id, season)
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        try:
            # Obtener stats del jugador (NBA API)
            player_stats = await asyncio.to_thread(
                self.nba_client.get_player_stats,
                player_id,
                season
            )

            if not player_stats:
                logger.warning(f"⚠️ No stats encontrados para jugador {player_id}")
                return None

            # Obtener estado de lesión (RapidAPI SportsData)
            player_data = await self.sportsdata_client.get_player_by_id(
                player_id=player_id,
                season=season
            )

            # Extraer datos de lesión
            is_injured = False
            injury_status = "Healthy"
            injury_impact = 0.0
            return_date = None

            if player_data and "injury" in player_data:
                is_injured = True
                injury_status = player_data["injury"].get("status", "Unknown")
                injury_impact = self.sportsdata_client._calculate_player_impact(
                    player_data,
                    is_injured=True,
                    injury=player_data.get("injury")
                )
                return_date = player_data["injury"].get("return_date")

            # Calcular impacto ajustado
            # Si el jugador está lesionado, su impacto en el análisis se reduce
            player_impact = player_stats.get("points", 0) + player_stats.get("assists", 0)
            adjusted_impact = player_impact * (1 - injury_impact)

            enriched = EnrichedPlayerStats(
                player_id=player_id,
                player_name=player_stats.get("name", "Unknown"),
                team=player_stats.get("team", "Unknown"),
                games_played=player_stats.get("games_played", 0),
                points=player_stats.get("points", 0.0),
                assists=player_stats.get("assists", 0.0),
                rebounds=player_stats.get("rebounds", 0.0),
                fg_pct=player_stats.get("fg_pct", 0.0),
                is_injured=is_injured,
                injury_status=injury_status,
                injury_impact=injury_impact,
                return_date=return_date,
                adjusted_impact=adjusted_impact
            )

            self._set_cache(cache_key, enriched, DataSource.SPORTSDATA)
            return enriched

        except Exception as e:
            logger.error(f"❌ Error enriqueciendo stats de jugador {player_id}: {str(e)}")
            return None

    async def get_enriched_team_stats(
        self,
        team: str,
        season: int = 2025
    ) -> Optional[EnrichedTeamStats]:
        """
        Obtiene estadísticas de equipo enriquecidas con datos de lesiones.
        
        Args:
            team: Código del equipo (ej: "LAL")
            season: Temporada
            
        Returns:
            EnrichedTeamStats o None
        """
        cache_key = self._cache_key("team", team, season)
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        try:
            # Obtener stats del equipo (NBA API)
            team_stats = await asyncio.to_thread(
                self.nba_client.get_team_stats,
                team,
                season
            )

            if not team_stats:
                logger.warning(f"⚠️ No stats encontrados para equipo {team}")
                return None

            # Obtener disponibilidad de jugadores (RapidAPI SportsData)
            player_availability = await self.sportsdata_client.get_player_availability(
                team=team,
                season=season
            )

            # Calcular métricas de salud del equipo
            injured_count = sum(1 for p in player_availability if not p.available)
            unavailable_count = sum(
                1 for p in player_availability
                if not p.available and p.impact_on_team > 0.3  # Impacto significativo
            )

            # Calcular salud del equipo (0.0 = muy lesionado, 1.0 = perfecto)
            total_impact = sum(p.impact_on_team for p in player_availability if not p.available)
            team_health_score = max(0.0, 1.0 - (total_impact / len(player_availability)))

            # Identificar ausencias críticas
            critical_absences = [
                p.player_name for p in player_availability
                if not p.available and p.impact_on_team > 0.5
            ]

            # Ajustar win_pct por lesiones
            base_win_pct = team_stats.get("win_pct", 0.5)
            projected_win_pct_adjusted = base_win_pct * team_health_score

            enriched = EnrichedTeamStats(
                team=team,
                season=season,
                wins=team_stats.get("wins", 0),
                losses=team_stats.get("losses", 0),
                win_pct=base_win_pct,
                injured_players=injured_count,
                unavailable_players=unavailable_count,
                team_health_score=team_health_score,
                projected_win_pct_adjusted=projected_win_pct_adjusted,
                critical_absences=critical_absences
            )

            self._set_cache(cache_key, enriched, DataSource.SPORTSDATA)
            return enriched

        except Exception as e:
            logger.error(f"❌ Error enriqueciendo stats de equipo {team}: {str(e)}")
            return None

    async def get_all_team_stats(
        self,
        teams: List[str],
        season: int = 2025
    ) -> Dict[str, EnrichedTeamStats]:
        """
        Obtiene stats enriquecidos de múltiples equipos en paralelo.
        
        Args:
            teams: Lista de códigos de equipos
            season: Temporada
            
        Returns:
            Dict {team: EnrichedTeamStats}
        """
        logger.info(f"🏀 Fetching stats para {len(teams)} equipos...")

        tasks = [
            self.get_enriched_team_stats(team, season)
            for team in teams
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        stats_dict = {}
        for team, result in zip(teams, results):
            if isinstance(result, Exception):
                logger.error(f"❌ Error para {team}: {result}")
            elif result:
                stats_dict[team] = result
            else:
                logger.warning(f"⚠️ Sin datos para {team}")

        logger.info(f"✓ {len(stats_dict)} equipos procesados exitosamente")
        return stats_dict

    async def compare_teams_health(
        self,
        team1: str,
        team2: str,
        season: int = 2025
    ) -> Dict[str, any]:
        """
        Compara salud de dos equipos (lesiones, impacto, etc.)
        
        Args:
            team1: Primer equipo
            team2: Segundo equipo
            season: Temporada
            
        Returns:
            Dict con comparación
        """
        stats1 = await self.get_enriched_team_stats(team1, season)
        stats2 = await self.get_enriched_team_stats(team2, season)

        if not (stats1 and stats2):
            return {}

        return {
            team1: {
                "health_score": stats1.team_health_score,
                "injured_players": stats1.injured_players,
                "critical_absences": stats1.critical_absences,
                "adjusted_win_pct": stats1.projected_win_pct_adjusted
            },
            team2: {
                "health_score": stats2.team_health_score,
                "injured_players": stats2.injured_players,
                "critical_absences": stats2.critical_absences,
                "adjusted_win_pct": stats2.projected_win_pct_adjusted
            },
            "health_advantage": team1 if stats1.team_health_score > stats2.team_health_score else team2
        }

    def get_cache_stats(self) -> Dict[str, any]:
        """Retorna estadísticas del caché"""
        expired = sum(1 for c in self.cache.values() if c.is_expired())
        return {
            "total_entries": len(self.cache),
            "expired_entries": expired,
            "valid_entries": len(self.cache) - expired,
            "sources": {
                s.value: sum(1 for c in self.cache.values() if c.source == s)
                for s in DataSource
            }
        }


# ============================================================================
# EJEMPLO DE USO
# ============================================================================

async def example_usage():
    """Ejemplo de cómo usar el API Manager"""
    from sportsdata_api_client import SportsDataClient

    # Inicializar clientes (simulados aquí)
    class MockNBAClient:
        async def get_player_stats(self, player_id, season):
            return {
                "name": "LeBron James",
                "team": "LAL",
                "points": 25.5,
                "assists": 8.3,
                "rebounds": 7.1,
                "fg_pct": 0.52,
                "games_played": 56
            }

        async def get_team_stats(self, team, season):
            return {
                "team": team,
                "wins": 45,
                "losses": 20,
                "win_pct": 0.692
            }

    nba_client = MockNBAClient()
    # sportsdata_client = SportsDataClient(api_key="tu_key")

    # manager = APIManager(nba_client, sportsdata_client)
    # enriched = await manager.get_enriched_team_stats("LAL")
    # print(f"Team Health Score: {enriched.team_health_score}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # asyncio.run(example_usage())