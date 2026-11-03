# NBA Predictor

NBA analytics platform: ESPN public API -> async API clients -> analytics (Monte Carlo) -> Streamlit + Plotly dashboard, with an optional FastAPI backend.

## Commands (PowerShell)

- Install: `pip install -r requirements.txt`
- Dashboard: `streamlit run streamlit_dashboard.py` (http://localhost:8501)
- API: `uvicorn server.main:app --reload` (currently broken: `server/main.py` is empty, no `app` is defined)
- Tests: `pytest` (all HTTP is mocked; passing tests do not prove ESPN's live endpoints still work)

## Architecture

- `api/` - ESPN clients (`nba_api_client.py` standings/team stats, `sportsdata_api_client.py` scoreboard/schedules), `api_manager.py` orchestration (retries, circuit breaker), `cache_manager.py` (TTL cache)
- `data/` - models, persistence, processors
- `analytics/` - `stats_calculator.py`, `monte_carlo.py`, `visualizations.py`
- `server/` - FastAPI routes under `/api/v1` (`fastapi_routes.py`); `main.py` still to be written
- `streamlit_dashboard.py` - UI
- `tests/` - pytest suite (`test_apis.py`)

## Conventions

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
