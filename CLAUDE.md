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
- `analytics/visualizations.py` holds pure UI helpers (health label/format, injury status colors and filter; no streamlit import). `analytics/stats_calculator.py`, `analytics/monte_carlo.py`, `data/*.py` and `api/cache_manager.py` are EMPTY placeholder files (0 bytes); build from scratch.
- `server/` - `main.py` (FastAPI `app`, lifespan builds the clients + `APIManager` into `app.state`), `fastapi_routes.py` (routes under `/api/v1`)
- `streamlit_dashboard.py` - UI
- `tests/` - pytest suite (`test_apis.py`, `test_server.py`, `test_team_ids.py`, `test_visualizations.py`). `pytest.ini` skips tests marked `live` (real ESPN calls); run them with `pytest -m live`.

## Conventions

- Team identity goes through `resolve_team()` in `api/nba_api_client.py` (accepts name, ESPN code, alias, id). Routes return the ESPN abbreviation (e.g. `GS`, not `GSW`).
- Data source is ESPN's public API (no key). RapidAPI was removed; do not reintroduce it. `SportsDataClient` / `sportsdata_api_client.py` keep their old name but call ESPN.
- Routes and the dashboard's Stats/Comparación tabs get team data through `APIManager.get_enriched_team_stats`. The dashboard still uses `nba_client` for Standings and `sportsdata_client` for scoreboard, recent games and the injured-player list. Do not add raw ESPN HTTP calls to the UI.
- One season rule: `current_season()` in `api/sportsdata_api_client.py` (rolls over in October; matches ESPN's `season.year`). Do not write a second one.
- `EnrichedTeamStats.fetch_failed` = injury fetch attempted and failed (not cached, retried). `injury_data_available` False with `fetch_failed` False = past season, show "sin datos".
- Don't test season/widget interaction with Streamlit `AppTest` on the real script: the season selectbox uses `format_func`, which makes it raise `ValueError: '2027' is not in list`.
- Stopping servers on Windows: `pkill` doesn't work; use `Get-NetTCPConnection -LocalPort <port> | Stop-Process`.
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

## Status and next steps (updated 2026-11-03)

Done: team resolver and corrected team ids (with regression tests), FastAPI server, season-keyed standings cache, real ESPN injuries, `fetch_failed` / `points` / `streak` on enriched stats, dashboard with all 30 teams, health section ("Salud del plantel") in Stats and Comparación with "sin datos" / "no se pudo consultar" messages, colored injury status with a status filter. 152 tests pass offline.

Next (not started):
1. Frontend polish (`frontend-ux`): check the status colors in light/dark mode (rgba backgrounds were never seen in a real browser; use opaque pastels if cells show no tint); report date caption; spinner around the health section; consistent team colors and a health bar in Comparación; auto-update Comparación without the button; annotate seasons without injury data in the sidebar; health vs win% scatter for all 30 teams; CSS pass, drop emoji in subheaders.
2. Monte Carlo / stats calculator (`analytics-dev`): empty files, build from scratch.
3. `critical_absences` is always empty (ESPN gives no player-importance data); the injured-player list needs a second client call because `EnrichedTeamStats` has no player list.
4. Assists/rebounds/FG% in `get_team_stats` are hard-coded `0.0` (needs another ESPN endpoint).
5. Possible rename: `SportsDataClient` -> ESPN-based name (touches server, api_manager, dashboard, tests).
6. Route default season is computed once at server start (stale across the October rollover for a long-running server).
7. `.env` (git-ignored) still holds old RapidAPI keys; the user was asked to remove them and revoke the key.
