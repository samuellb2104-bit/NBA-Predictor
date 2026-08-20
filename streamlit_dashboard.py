"""
NBA Predictor Dashboard - Streamlit
Datos reales vía la API pública de ESPN (sin API key, sin cuota).
"""

import streamlit as st
import plotly.express as px
import pandas as pd
import asyncio
import os
import logging
from datetime import datetime
from dotenv import load_dotenv

from api.nba_api_client import TEAM_NAME_TO_ID

load_dotenv()
logging.basicConfig(level=logging.INFO)


def get_current_nba_season() -> int:
    """'year' que espera la API: el año en que TERMINA la temporada
    (convención de ESPN — confirmado empíricamente: year=2024 devuelve
    los resultados reales de la temporada 2023-24).

    La temporada corre de octubre a junio. Si estamos en octubre-diciembre
    ya arrancó la que termina el año siguiente; en receso (jul-sep) se
    adelanta a la que está por comenzar, aunque todavía no tenga datos.
    """
    now = datetime.now()
    if now.month >= 7:
        return now.year + 1
    return now.year


CURRENT_SEASON = get_current_nba_season()

st.set_page_config(page_title="NBA Predictor", layout="wide")

# ─── Inicialización ───────────────────────────────────────────────────────────

@st.cache_resource
def init_clients():
    from api.nba_api_client import NBAApiClient
    from api.sportsdata_api_client import SportsDataClient
    from api.api_manager import APIManager

    nba_client = NBAApiClient()
    sportsdata_client = SportsDataClient()
    manager = APIManager(
        nba_client=nba_client,
        sportsdata_client=sportsdata_client,
        cache_ttl=int(os.getenv("CACHE_TTL", 3600)),
        use_cache=os.getenv("USE_CACHE", "true").lower() == "true"
    )
    return nba_client, sportsdata_client, manager

try:
    nba_client, sportsdata_client, manager = init_clients()
    api_ok = True
except Exception as e:
    st.error(f"❌ Error inicializando APIs: {e}")
    api_ok = False

# ─── Helpers ──────────────────────────────────────────────────────────────────

TEAMS = ["Lakers", "Celtics", "Heat", "Nuggets", "Warriors",
         "Bucks", "Suns", "Clippers", "76ers", "Nets"]

def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except Exception:
        return asyncio.run(coro)

@st.cache_data(ttl=3600)
def get_team_stats(team, season):
    if not api_ok:
        return None
    return nba_client.get_team_stats(team, season)

@st.cache_data(ttl=3600)
def get_standings(season):
    if not api_ok:
        return []
    return nba_client.get_standings(season)

@st.cache_data(ttl=3600)
def get_recent_games(team, season):
    if not api_ok:
        return []

    team_id = TEAM_NAME_TO_ID.get(team)
    if not team_id:
        return []

    async def _fetch():
        return await sportsdata_client.get_team_recent_games(team_id, season)
    try:
        return run_async(_fetch())
    except Exception as e:
        st.warning(f"Historial no disponible: {e}")
        return []

@st.cache_data(ttl=300)
def get_scoreboard(date_str):
    async def _fetch():
        return await sportsdata_client.get_scoreboard(date_str)
    try:
        return run_async(_fetch())
    except Exception as e:
        st.warning(f"Scoreboard no disponible: {e}")
        return []

# ─── UI ───────────────────────────────────────────────────────────────────────

st.title(f"🏀 NBA Predictor {CURRENT_SEASON - 1}-{str(CURRENT_SEASON)[-2:]}")
st.caption("Datos reales: API pública de ESPN")

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuración")
    season = st.selectbox(
        "Temporada",
        [CURRENT_SEASON, CURRENT_SEASON - 1, CURRENT_SEASON - 2],
        index=0,
        format_func=lambda y: f"{y - 1}-{str(y)[-2:]}"
    )
    st.divider()
    if st.button("🧹 Limpiar caché"):
        st.cache_data.clear()
        st.success("Caché limpiado")
    st.caption(f"Actualizado: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["📊 Stats", "🏟️ Scoreboard", "📈 Standings", "🆚 Comparación"])

# ── Tab 1: Stats de equipo ────────────────────────────────────────────────────
with tab1:
    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("Team Stats")
        team_sel = st.selectbox("Equipo", TEAMS)

        with st.spinner(f"Cargando {team_sel}..."):
            stats = get_team_stats(team_sel, season)

        if stats:
            st.metric("Wins", stats["wins"])
            st.metric("Losses", stats["losses"])
            st.metric("Win %", f"{stats['win_pct']:.1%}")
            st.metric("PPG", stats["points"])
        else:
            st.warning("Sin datos — verifica conexión a NBA API")

    with col2:
        st.subheader(f"Últimos 10 juegos — {team_sel}")
        with st.spinner(f"Buscando el historial de {team_sel} en {season - 1}-{str(season)[-2:]}..."):
            games = get_recent_games(team_sel, season)

        if games:
            rows = []
            for g in games:
                is_home = team_sel in g.home_team
                team_score = g.home_score if is_home else g.away_score
                opp_score = g.away_score if is_home else g.home_score
                rows.append({
                    "Fecha": f"{g.date[:4]}-{g.date[4:6]}-{g.date[6:]}",
                    "Rival": g.away_team if is_home else g.home_team,
                    "L/V": "Local" if is_home else "Visita",
                    "Resultado": "W" if team_score > opp_score else "L",
                    "Puntos": team_score,
                    "Puntos rival": opp_score,
                })
            df_games = pd.DataFrame(rows).sort_values("Fecha")

            fig = px.bar(
                df_games, x="Fecha", y="Puntos", color="Resultado",
                color_discrete_map={"W": "#00b09b", "L": "#e74c3c"},
                title="Puntos por partido"
            )
            fig.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(
                df_games[["Fecha", "Rival", "L/V", "Resultado", "Puntos", "Puntos rival"]],
                use_container_width=True, hide_index=True
            )
        else:
            st.warning("Sin historial de juegos para esta temporada")

# ── Tab 2: Scoreboard ─────────────────────────────────────────────────────────
with tab2:
    st.subheader("🏟️ Scoreboard")
    st.caption(
        "Elige cualquier fecha, incluso de temporadas anteriores — "
        "la fecha por defecto se ajusta a la temporada seleccionada arriba."
    )

    default_date = datetime.now() if season == CURRENT_SEASON else datetime(season, 4, 15)
    date_input = st.date_input("Fecha", default_date, key=f"scoreboard_date_{season}")
    date_str = date_input.strftime("%Y%m%d")

    with st.spinner("Consultando RapidAPI..."):
        games_today = get_scoreboard(date_str)

    if games_today:
        for game in games_today:
            with st.container():
                col1, col2, col3 = st.columns([2, 1, 2])
                with col1:
                    st.markdown(f"### {game.away_team}")
                    st.metric("Score", game.away_score)
                with col2:
                    st.markdown(f"**{game.status}**")
                    if game.period:
                        st.caption(f"Period {game.period}")
                with col3:
                    st.markdown(f"### {game.home_team}")
                    st.metric("Score", game.home_score)
                st.divider()
    else:
        st.info("Sin partidos para esta fecha o API no disponible")

# ── Tab 3: Standings ──────────────────────────────────────────────────────────
with tab3:
    st.subheader("📈 League Standings")

    with st.spinner("Cargando standings..."):
        standings = get_standings(season)

    if standings:
        df_st = pd.DataFrame(standings)
        df_st = df_st.sort_values("win_pct", ascending=False).reset_index(drop=True)
        df_st.index += 1

        st.dataframe(
            df_st[["team", "wins", "losses", "win_pct", "streak"]],
            use_container_width=True
        )

        fig = px.bar(
            df_st.head(15), x="team", y="win_pct",
            title="Win % — Top 15 equipos", color="win_pct",
            color_continuous_scale="RdYlGn"
        )
        fig.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("Sin datos de standings")

# ── Tab 4: Comparación ────────────────────────────────────────────────────────
with tab4:
    st.subheader("🆚 Comparación de equipos")
    col1, col2 = st.columns(2)

    with col1:
        team_a = st.selectbox("Equipo A", TEAMS, index=0)
    with col2:
        team_b = st.selectbox("Equipo B", TEAMS, index=1)

    if st.button("⚡ Comparar equipos"):
        with st.spinner("Cargando datos..."):
            stats_a = get_team_stats(team_a, season)
            stats_b = get_team_stats(team_b, season)

        if stats_a and stats_b:
            # Comparación Win% y PPG (únicas métricas que la API provee)
            df_chart = pd.DataFrame({
                "Equipo": [team_a, team_a, team_b, team_b],
                "Métrica": ["Win %", "PPG", "Win %", "PPG"],
                "Valor": [
                    stats_a["win_pct"] * 100, stats_a["points"],
                    stats_b["win_pct"] * 100, stats_b["points"]
                ]
            })
            fig = px.bar(
                df_chart, x="Métrica", y="Valor", color="Equipo",
                barmode="group", title="Win % y PPG"
            )
            st.plotly_chart(fig, use_container_width=True)

            # Tabla comparativa
            df_comp = pd.DataFrame({
                "Stat": ["Wins", "Losses", "Win %", "PPG"],
                team_a: [
                    stats_a["wins"], stats_a["losses"], f"{stats_a['win_pct']:.1%}",
                    stats_a["points"]
                ],
                team_b: [
                    stats_b["wins"], stats_b["losses"], f"{stats_b['win_pct']:.1%}",
                    stats_b["points"]
                ],
            })
            st.dataframe(df_comp, use_container_width=True)

            # Predicción
            winner = team_a if stats_a["win_pct"] > stats_b["win_pct"] else team_b
            diff = abs(stats_a["win_pct"] - stats_b["win_pct"])
            st.success(f"🏆 Favorito: **{winner}** (diferencia Win%: {diff:.1%})")
        else:
            st.error("No se pudieron cargar stats de uno o ambos equipos")