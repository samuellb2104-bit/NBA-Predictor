"""
API Manager - Orquestador centralizado para múltiples fuentes de datos NBA.

Maneja:
  - Sincronización entre ESPN standings (NBA API) y ESPN scoreboard/lesiones
  - Caché inteligente con expiración
  - Retry automático y circuit breaker
  - Composición de datos de múltiples fuentes

Uso:
    manager = APIManager(nba_client, sportsdata_client, cache_ttl=3600)
    enriched_stats = await manager.get_enriched_team_stats("LAL")
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from api.sportsdata_api_client import is_current_season

logger = logging.getLogger(__name__)

# Tamaño de la rotación NBA usada para normalizar el impacto de lesiones:
# team_health_score = max(0, 1 - sum(pesos) / ROTATION_SIZE). Un jugador
# Out (peso 1.0) resta 0.1; ESPN no da importancia por jugador, así que
# todos cuentan igual.
ROTATION_SIZE = 10


class DataSource(Enum):
    """Fuentes de datos disponibles (ambas son endpoints públicos de ESPN)"""
    NBA_API = "nba_api"  # standings / stats de equipo
    SPORTSDATA = "sportsdata"  # scoreboard / calendario / lesiones
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
    # False si la temporada no es la actual (ESPN solo da lesiones vigentes)
    # o falló la consulta: distingue "sin lesiones" de "sin datos".
    injury_data_available: bool = True


class APIManager:
    """Orquestador centralizado de APIs NBA"""

    def __init__(
        self,
        nba_client,  # NBAApiClient (ESPN standings)
        sportsdata_client,  # SportsDataClient (ESPN scoreboard/lesiones)
        cache_ttl: int = 3600,  # TTL default en segundos (1 hora)
        use_cache: bool = True
    ):
        """
        Inicializa el API Manager.
        
        Args:
            nba_client: NBAApiClient (standings / stats de equipo, ESPN)
            sportsdata_client: SportsDataClient (scoreboard / lesiones, ESPN)
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

            # Lesiones: ESPN solo publica el reporte vigente, no histórico.
            player_availability = []
            injury_data_available = False
            if is_current_season(season):
                try:
                    player_availability = await self.sportsdata_client.get_player_availability(
                        team=team,
                        season=season
                    )
                    injury_data_available = True
                except Exception as e:
                    logger.warning(f"⚠️ Sin datos de lesiones para {team}: {e}")

            injured_count = len(player_availability)
            # No disponibles = Out/Suspension (los Day-To-Day cuentan como
            # lesionados pero siguen disponibles).
            unavailable_count = sum(1 for p in player_availability if not p.available)

            total_impact = sum(p.impact_on_team for p in player_availability)
            team_health_score = max(0.0, 1.0 - total_impact / ROTATION_SIZE)

            # TODO: requiere datos de importancia por jugador (minutos/usage),
            # que ESPN /injuries no entrega; no se inventa.
            critical_absences: List[str] = []

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
                critical_absences=critical_absences,
                injury_data_available=injury_data_available
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
                "adjusted_win_pct": stats1.projected_win_pct_adjusted,
                "injury_data_available": stats1.injury_data_available
            },
            team2: {
                "health_score": stats2.team_health_score,
                "injured_players": stats2.injured_players,
                "critical_absences": stats2.critical_absences,
                "adjusted_win_pct": stats2.projected_win_pct_adjusted,
                "injury_data_available": stats2.injury_data_available
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
