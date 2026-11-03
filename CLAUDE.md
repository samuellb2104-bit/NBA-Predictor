# NBA Predictor

NBA analytics platform: ESPN public API -> async API clients -> Streamlit + Plotly dashboard, plus a FastAPI backend. Monte Carlo analytics are planned, not built.

## Commands (PowerShell)

- Install: `pip install -r requirements.txt`
- Dashboard: `streamlit run streamlit_dashboard.py` (http://localhost:8501)
- API: `uvicorn server.main:app --reload` (http://localhost:8000/docs)
- Tests: `pytest` (all HTTP is mocked; passing tests do not prove ESPN's live endpoints still work)
- After editing `api/` with Streamlit running, use "Limpiar caché" or restart it.

## Architecture

- `api/` - ESPN clients (`nba_api_client.py` standings/team stats, `sportsdata_api_client.py` scoreboard/schedules), `api_manager.py` orchestration + its own in-memory TTL cache (injury health score, enriched stats)
- `data/`, `analytics/` (`stats_calculator.py`, `monte_carlo.py`, `visualizations.py`) and `api/cache_manager.py` are EMPTY placeholder files (0 bytes). Nothing to reuse; build from scratch.
- `server/` - `main.py` (FastAPI `app`, lifespan builds the clients + `APIManager` into `app.state`), `fastapi_routes.py` (routes under `/api/v1`)
- `streamlit_dashboard.py` - UI
- `tests/` - pytest suite (`test_apis.py`, `test_server.py`)

## Conventions

- Team identity goes through `resolve_team()` in `api/nba_api_client.py` (accepts name, ESPN code, alias, id). Routes return the ESPN abbreviation (e.g. `GS`, not `GSW`).
- Data source is ESPN's public API (no key). RapidAPI was removed; do not reintroduce it. `SportsDataClient` / `sportsdata_api_client.py` keep their old name but call ESPN.
- Routes get data through `APIManager`. The dashboard currently calls `nba_client` / `sportsdata_client` directly; do not add raw ESPN HTTP calls to the UI.
- Injuries come from ESPN `/injuries` (current season only). Past seasons return `injury_data_available: false`; the UI should show "sin datos", not "healthy".
- `st.cache_data` functions must return plain data (dicts/lists), not dataclass instances (pickle breaks on module reload).
- I/O is async (httpx); keep new client code async.
- Existing comments and docstrings are mostly Spanish; match the surrounding file.
- Add or update tests in `tests/` with any behavior change, and run `pytest` before finishing.
- Never commit `.env` or secrets.

## Agents (`.claude/agents/`)

- `frontend-ux` - dashboard UI/UX (`streamlit_dashboard.py`, Plotly charts)
- `api-data` - `api/`, `server/`, `data/`, ESPN integration, caching, FastAPI
- `analytics-dev` - `analytics/`, prediction logic, tests

Each agent stays inside its area and reports back any change needed elsewhere instead of making it.

## Status and next steps (updated 2026-11-02)

Done: team resolver, FastAPI server (`server/main.py`), season-keyed standings cache, real ESPN injuries, default season = current (2027 = 2026-27), dashboard pickle fix. 76 tests pass.

Next:
1. Frontend (`frontend-ux`): in `streamlit_dashboard.py` read `injury_data_available` and show "sin datos" instead of "healthy" when false; then design improvements.
2. Dashboard still lacks the health/injury view; `critical_absences` is always empty (ESPN has no player-importance data).
3. Monte Carlo / stats calculator (`analytics-dev`) not started.
4. Possible rename: `SportsDataClient` -> ESPN-based name (touches server, api_manager, dashboard, tests).
5. Assists/rebounds/FG% in `get_team_stats` are hard-coded `0.0` (needs another ESPN endpoint).

Note: custom agents in `.claude/agents/` only load in a new session.
