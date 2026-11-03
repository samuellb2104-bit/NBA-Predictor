# NBA Predictor

NBA analytics platform: ESPN public API -> async API clients -> analytics (Monte Carlo) -> Streamlit + Plotly dashboard, with an optional FastAPI backend.

## Commands (PowerShell)

- Install: `pip install -r requirements.txt`
- Dashboard: `streamlit run streamlit_dashboard.py` (http://localhost:8501)
- API: `uvicorn server.main:app --reload` (http://localhost:8000/docs)
- Tests: `pytest` (all HTTP is mocked; passing tests do not prove ESPN's live endpoints still work)

## Architecture

- `api/` - ESPN clients (`nba_api_client.py` standings/team stats, `sportsdata_api_client.py` scoreboard/schedules), `api_manager.py` orchestration (retries, circuit breaker), `cache_manager.py` (TTL cache)
- `data/` - models, persistence, processors
- `analytics/` - `stats_calculator.py`, `monte_carlo.py`, `visualizations.py`
- `server/` - `main.py` (FastAPI `app`, lifespan builds the clients + `APIManager` into `app.state`), `fastapi_routes.py` (routes under `/api/v1`)
- `streamlit_dashboard.py` - UI
- `tests/` - pytest suite (`test_apis.py`, `test_server.py`)

## Conventions

- Team identity goes through `resolve_team()` in `api/nba_api_client.py` (accepts name, ESPN code, alias, id). Routes return the ESPN abbreviation (e.g. `GS`, not `GSW`).
- Data source is ESPN's public API (no key). RapidAPI was removed; do not reintroduce it. Some module docstrings still mention it and are stale.
- The UI and routes get data through `APIManager`, never by calling ESPN directly.
- I/O is async (httpx); keep new client code async.
- Existing comments and docstrings are mostly Spanish; match the surrounding file.
- Add or update tests in `tests/` with any behavior change, and run `pytest` before finishing.
- Never commit `.env` or secrets.

## Agents (`.claude/agents/`)

- `frontend-ux` - dashboard UI/UX (`streamlit_dashboard.py`, Plotly charts)
- `api-data` - `api/`, `server/`, `data/`, ESPN integration, caching, FastAPI
- `analytics-dev` - `analytics/`, prediction logic, tests

Each agent stays inside its area and reports back any change needed elsewhere instead of making it.
