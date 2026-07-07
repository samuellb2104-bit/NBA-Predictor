"""
FastAPI Routes - Endpoints mejorados con datos enriquecidos de lesiones.

Integra:
  - NBA API para estadísticas
  - RapidAPI SportsData para lesiones/disponibilidad
  - API Manager para orquestación y caché

Endpoints:
  GET /api/v1/teams/{team}/stats - Stats enriquecidos de equipo
  GET /api/v1/players/{player_id}/stats - Stats enriquecidos de jugador
  GET /api/v1/health-check - Estado de APIs
  GET /api/v1/compare/teams - Comparación de salud entre equipos
"""

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse
from typing import List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Crear router
router = APIRouter(prefix="/api/v1", tags=["NBA Analytics"])

# Estos serían inyectados por FastAPI
# En main.py: router.app_state.api_manager = api_manager
api_manager = None  # Se inicializa en main.py


def get_api_manager():
    """Dependency injection para acceder al API Manager"""
    if api_manager is None:
        raise HTTPException(
            status_code=500,
            detail="API Manager no inicializado"
        )
    return api_manager


# ============================================================================
# ENDPOINTS DE ESTADÍSTICAS DE EQUIPO
# ============================================================================

@router.get("/teams/{team}/stats", name="get_team_stats")
async def get_team_stats(
    team: str = Query(..., min_length=2, max_length=3, description="Código del equipo (ej: LAL)"),
    season: int = Query(2025, ge=1996, le=2050, description="Temporada NBA"),
    use_cache: bool = Query(True, description="Usar caché si está disponible")
):
    """
    Obtiene estadísticas enriquecidas de un equipo.
    
    Incluye:
    - Récord (W-L, win%)
    - Salud del equipo (score 0-1)
    - Jugadores lesionados
    - Ausencias críticas
    - Win% ajustado por lesiones
    
    Ejemplo: `GET /api/v1/teams/LAL/stats?season=2025`
    """
    try:
        manager = get_api_manager()

        # Si no quiere caché, limpiar para ese equipo
        if not use_cache:
            manager.clear_cache(pattern=f"team:{team}:{season}")

        stats = await manager.get_enriched_team_stats(team, season)

        if not stats:
            raise HTTPException(
                status_code=404,
                detail=f"No se encontraron datos para el equipo {team}"
            )

        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "team": stats.team,
                "season": stats.season,
                "record": {
                    "wins": stats.wins,
                    "losses": stats.losses,
                    "win_pct": round(stats.win_pct, 3)
                },
                "health": {
                    "health_score": round(stats.team_health_score, 3),
                    "status": _get_health_status(stats.team_health_score),
                    "injured_players": stats.injured_players,
                    "unavailable_players": stats.unavailable_players,
                    "critical_absences": stats.critical_absences
                },
                "projections": {
                    "base_win_pct": round(stats.win_pct, 3),
                    "adjusted_win_pct": round(stats.projected_win_pct_adjusted, 3),
                    "impact_of_injuries": round(stats.win_pct - stats.projected_win_pct_adjusted, 3)
                }
            },
            "message": f"Stats para {team} en temporada {season}"
        }

    except Exception as e:
        logger.error(f"Error fetching team stats: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error obteniendo datos: {str(e)}"
        )


@router.get("/teams", name="get_all_teams_stats")
async def get_all_teams_stats(
    season: int = Query(2025, ge=1996, le=2050),
    teams: Optional[List[str]] = Query(None, description="Lista de equipos a filtrar"),
    sort_by: str = Query("health_score", description="Ordenar por: health_score, wins, injured_players")
):
    """
    Obtiene stats enriquecidos de todos los equipos (o un subset).
    
    Parámetros:
    - teams: Lista de equipos (ej: ?teams=LAL&teams=BOS&teams=LAC)
    - sort_by: health_score | wins | injured_players
    
    Ejemplo: `GET /api/v1/teams?season=2025&teams=LAL&teams=BOS&sort_by=health_score`
    """
    try:
        manager = get_api_manager()

        # Si no especifica equipos, obtener los 30 de la NBA
        if not teams:
            teams = [
                "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN",
                "DET", "GSW", "HOU", "LAC", "LAL", "MEM", "MIA", "MIL",
                "MIN", "NOP", "NYK", "OKC", "ORL", "PHI", "PHX", "POR",
                "SAC", "SAS", "TOR", "UTA", "WAS"
            ]

        stats_dict = await manager.get_all_team_stats(teams, season)

        # Ordenar según parámetro
        if sort_by == "health_score":
            sorted_stats = sorted(
                stats_dict.items(),
                key=lambda x: x[1].team_health_score,
                reverse=True
            )
        elif sort_by == "wins":
            sorted_stats = sorted(
                stats_dict.items(),
                key=lambda x: x[1].wins,
                reverse=True
            )
        elif sort_by == "injured_players":
            sorted_stats = sorted(
                stats_dict.items(),
                key=lambda x: x[1].injured_players
            )
        else:
            sorted_stats = list(stats_dict.items())

        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "count": len(sorted_stats),
            "season": season,
            "data": [
                {
                    "team": team,
                    "record": f"{stats.wins}-{stats.losses}",
                    "win_pct": round(stats.win_pct, 3),
                    "health_score": round(stats.team_health_score, 3),
                    "injured_players": stats.injured_players,
                    "adjusted_win_pct": round(stats.projected_win_pct_adjusted, 3)
                }
                for team, stats in sorted_stats
            ]
        }

    except Exception as e:
        logger.error(f"Error fetching all teams stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINTS DE COMPARACIÓN
# ============================================================================

@router.get("/compare/teams", name="compare_teams")
async def compare_teams(
    team1: str = Query(..., min_length=2, max_length=3),
    team2: str = Query(..., min_length=2, max_length=3),
    season: int = Query(2025, ge=1996, le=2050)
):
    """
    Compara la salud de dos equipos.
    
    Ejemplo: `GET /api/v1/compare/teams?team1=LAL&team2=BOS&season=2025`
    """
    if team1.upper() == team2.upper():
        raise HTTPException(
            status_code=400,
            detail="Los equipos deben ser diferentes"
        )

    try:
        manager = get_api_manager()
        comparison = await manager.compare_teams_health(team1, team2, season)

        if not comparison:
            raise HTTPException(
                status_code=404,
                detail=f"No se encontraron datos para comparación"
            )

        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "season": season,
            "comparison": comparison,
            "advantage": {
                "team": comparison["health_advantage"],
                "reason": f"{team1} tiene mayor salud de equipo"
                if comparison["health_advantage"] == team1
                else f"{team2} tiene mayor salud de equipo"
            }
        }

    except Exception as e:
        logger.error(f"Error comparing teams: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINTS DE SALUD DEL SISTEMA
# ============================================================================

@router.get("/health-check", name="health_check")
async def health_check():
    """
    Verifica el estado de todas las APIs integradas.
    
    Retorna:
    - Estado de NBA API
    - Estado de RapidAPI SportsData
    - Estadísticas de caché
    """
    try:
        manager = get_api_manager()
        cache_stats = manager.get_cache_stats()

        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "services": {
                "nba_api": {
                    "status": "connected",
                    "description": "NBA Stats API"
                },
                "sportsdata": {
                    "status": "connected",
                    "description": "RapidAPI SportsData"
                }
            },
            "cache": cache_stats
        }

    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }, 503


@router.post("/cache/clear", name="clear_cache")
async def clear_cache(
    pattern: Optional[str] = Query(None, description="Patrón de claves a limpiar")
):
    """
    Limpia el caché del API Manager.
    
    Parámetros:
    - pattern: Patrón glob (ej: "LAL:*" limpia todo lo de LAL)
    
    Ejemplo: `POST /api/v1/cache/clear?pattern=LAL:*`
    """
    try:
        manager = get_api_manager()
        manager.clear_cache(pattern=pattern)

        return {
            "status": "success",
            "message": f"Caché limpiado: {pattern or 'completo'}",
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINTS DE MONITOREO
# ============================================================================

@router.get("/status/cache", name="cache_status")
async def cache_status():
    """
    Retorna estadísticas detalladas del caché.
    """
    try:
        manager = get_api_manager()
        stats = manager.get_cache_stats()

        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "cache": stats
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# UTILIDADES
# ============================================================================

def _get_health_status(score: float) -> str:
    """Convierte un health score (0-1) a descripción textual"""
    if score >= 0.9:
        return "Excelente 🟢"
    elif score >= 0.7:
        return "Bueno 🟡"
    elif score >= 0.5:
        return "Regular 🟠"
    else:
        return "Crítico 🔴"


# ============================================================================
# EJEMPLO DE INTEGRACIÓN EN MAIN.PY
# ============================================================================

"""
# En tu main.py:

from fastapi import FastAPI
from api_manager import APIManager
from sportsdata_api_client import SportsDataClient
from nba_api_client import NBAClient  # Tu cliente actual
from routes import router

app = FastAPI(title="NBA Predictor API")

@app.on_event("startup")
async def startup():
    # Inicializar clientes
    nba_client = NBAClient()
    sportsdata_client = SportsDataClient(api_key="tu_key")
    
    # Crear API Manager
    api_manager = APIManager(
        nba_client=nba_client,
        sportsdata_client=sportsdata_client,
        cache_ttl=3600
    )
    
    # Hacerlo disponible en toda la app
    app.state.api_manager = api_manager
    
    # Inyectar en router
    global api_manager as global_api_manager
    global_api_manager = api_manager

# Incluir router
app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
"""