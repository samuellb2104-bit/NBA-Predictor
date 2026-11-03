"""
FastAPI Routes - Endpoints mejorados con datos enriquecidos de lesiones.

Integra:
  - NBA API para estadísticas
  - ESPN (SportsDataClient) para lesiones vigentes (/injuries)
  - API Manager para orquestación y caché

Endpoints:
  GET /api/v1/teams/{team}/stats - Stats enriquecidos de equipo
  GET /api/v1/health-check - Estado de APIs
  GET /api/v1/compare/teams - Comparación de salud entre equipos
"""

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from typing import List, Optional
from datetime import datetime
import logging

from api.nba_api_client import TEAM_ABBREVIATIONS, resolve_team
from api.sportsdata_api_client import current_season

logger = logging.getLogger(__name__)

# Crear router
router = APIRouter(prefix="/api/v1", tags=["NBA Analytics"])


def get_api_manager(request: Request):
    """Obtiene el APIManager guardado en app.state (lo crea server/main.py)."""
    manager = getattr(request.app.state, "api_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=500,
            detail="API Manager no inicializado"
        )
    return manager


def _resolve_or_404(team: str) -> str:
    """Devuelve la abreviatura ESPN del equipo o lanza 404."""
    info = resolve_team(team)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Equipo desconocido: {team}")
    return info.abbr


# ============================================================================
# ENDPOINTS DE ESTADÍSTICAS DE EQUIPO
# ============================================================================

@router.get("/teams/{team}/stats", name="get_team_stats")
async def get_team_stats(
    request: Request,
    team: str = Path(..., min_length=2, max_length=30, description="Equipo: código ESPN (LAL), alias (GSW), nombre (Lakers) o id"),
    season: int = Query(current_season(), ge=1996, le=2050, description="Temporada NBA"),
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
    
    Ejemplo: `GET /api/v1/teams/LAL/stats?season=2027`
    """
    try:
        manager = get_api_manager(request)
        team = _resolve_or_404(team)

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
                    "critical_absences": stats.critical_absences,
                    "injury_data_available": stats.injury_data_available
                },
                "projections": {
                    "base_win_pct": round(stats.win_pct, 3),
                    "adjusted_win_pct": round(stats.projected_win_pct_adjusted, 3),
                    "impact_of_injuries": round(stats.win_pct - stats.projected_win_pct_adjusted, 3)
                }
            },
            "message": f"Stats para {team} en temporada {season}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching team stats: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error obteniendo datos: {str(e)}"
        )


@router.get("/teams", name="get_all_teams_stats")
async def get_all_teams_stats(
    request: Request,
    season: int = Query(current_season(), ge=1996, le=2050),
    teams: Optional[List[str]] = Query(None, description="Lista de equipos a filtrar"),
    sort_by: str = Query("health_score", description="Ordenar por: health_score, wins, injured_players")
):
    """
    Obtiene stats enriquecidos de todos los equipos (o un subset).
    
    Parámetros:
    - teams: Lista de equipos (ej: ?teams=LAL&teams=BOS&teams=LAC)
    - sort_by: health_score | wins | injured_players
    
    Ejemplo: `GET /api/v1/teams?season=2027&teams=LAL&teams=BOS&sort_by=health_score`
    """
    try:
        manager = get_api_manager(request)

        # Si no especifica equipos, obtener los 30 de la NBA
        if teams:
            teams = list(dict.fromkeys(_resolve_or_404(t) for t in teams))
        else:
            teams = list(TEAM_ABBREVIATIONS)

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
                    "injury_data_available": stats.injury_data_available,
                    "adjusted_win_pct": round(stats.projected_win_pct_adjusted, 3)
                }
                for team, stats in sorted_stats
            ]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching all teams stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINTS DE COMPARACIÓN
# ============================================================================

@router.get("/compare/teams", name="compare_teams")
async def compare_teams(
    request: Request,
    team1: str = Query(..., min_length=2, max_length=30),
    team2: str = Query(..., min_length=2, max_length=30),
    season: int = Query(current_season(), ge=1996, le=2050)
):
    """
    Compara la salud de dos equipos.
    
    Ejemplo: `GET /api/v1/compare/teams?team1=LAL&team2=BOS&season=2027`
    """
    team1 = _resolve_or_404(team1)
    team2 = _resolve_or_404(team2)
    if team1 == team2:
        raise HTTPException(
            status_code=400,
            detail="Los equipos deben ser diferentes"
        )

    try:
        manager = get_api_manager(request)
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

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error comparing teams: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINTS DE SALUD DEL SISTEMA
# ============================================================================

@router.get("/health-check", name="health_check")
async def health_check(request: Request):
    """
    Verifica el estado de todas las APIs integradas.
    
    Retorna:
    - Estado de NBA API (ESPN standings)
    - Estado de SportsData (ESPN scoreboard)
    - Estadísticas de caché
    """
    try:
        manager = get_api_manager(request)
        cache_stats = manager.get_cache_stats()

        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "services": {
                "nba_api": {
                    "status": "connected",
                    "description": "ESPN standings"
                },
                "sportsdata": {
                    "status": "connected",
                    "description": "ESPN scoreboard/schedule"
                }
            },
            "cache": cache_stats
        }

    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(getattr(e, "detail", e)),
                "timestamp": datetime.now().isoformat()
            }
        )


@router.post("/cache/clear", name="clear_cache")
async def clear_cache(
    request: Request,
    pattern: Optional[str] = Query(None, description="Patrón de claves a limpiar")
):
    """
    Limpia el caché del API Manager.
    
    Parámetros:
    - pattern: Patrón glob (ej: "LAL:*" limpia todo lo de LAL)
    
    Ejemplo: `POST /api/v1/cache/clear?pattern=LAL:*`
    """
    try:
        manager = get_api_manager(request)
        manager.clear_cache(pattern=pattern)

        return {
            "status": "success",
            "message": f"Caché limpiado: {pattern or 'completo'}",
            "timestamp": datetime.now().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINTS DE MONITOREO
# ============================================================================

@router.get("/status/cache", name="cache_status")
async def cache_status(request: Request):
    """
    Retorna estadísticas detalladas del caché.
    """
    try:
        manager = get_api_manager(request)
        stats = manager.get_cache_stats()

        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "cache": stats
        }

    except HTTPException:
        raise
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
