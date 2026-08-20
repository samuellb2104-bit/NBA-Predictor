# NBA-Predictor

An NBA analytics platform that aggregates real statistics and player
injury/availability data from multiple sports APIs, exposes them through a
resilient async **FastAPI** backend, and visualizes them in an interactive
**Streamlit + Plotly** dashboard — including **Monte Carlo** simulations for
game predictions.

## Purpose

The goal of the project is to turn raw NBA data into actionable insight:

- **Aggregate** team and player statistics from ESPN's public NBA data
  (standings, schedules, scoreboards) — no API key required.
- **Orchestrate** multiple data sources behind a single API layer with
  intelligent caching, automatic retries, and circuit-breaker resilience.
- **Analyze** matchups through statistical calculations and **Monte Carlo**
  simulations to estimate game outcomes.
- **Visualize** everything in a clean, interactive web dashboard so results are
  easy to explore.

## Architecture

The project is organized into clear, decoupled layers:

```
NBA-predictor/
├── api/                # External API clients + orchestration
│   ├── nba_api_client.py        # ESPN standings / team stats
│   ├── sportsdata_api_client.py # ESPN scoreboard / team schedules
│   ├── api_manager.py           # Multi-source orchestration, retries, circuit breaker
│   └── cache_manager.py         # Intelligent caching with TTL/expiration
├── data/               # Data layer
│   ├── models.py               # Data models
│   ├── database.py             # Persistence
│   └── processors.py           # Data transformation
├── analytics/          # Analytics & predictions
│   ├── stats_calculator.py     # Statistical calculations
│   ├── monte_carlo.py          # Monte Carlo simulations
│   └── visualizations.py       # Chart builders
├── server/             # FastAPI backend
│   ├── main.py
│   └── fastapi_routes.py       # Versioned REST endpoints (/api/v1/...)
├── tests/              # Pytest suite
├── streamlit_dashboard.py      # Streamlit + Plotly web dashboard
└── requirements.txt
```

### API endpoints (`/api/v1`)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| `GET`  | `/api/v1/teams/{team}/stats`         | Enriched team statistics |
| `GET`  | `/api/v1/players/{player_id}/stats`  | Enriched player statistics |
| `GET`  | `/api/v1/health-check`               | Status of the connected APIs |
| `GET`  | `/api/v1/compare/teams`              | Health/availability comparison between teams |

##  Tech Stack

**Language:** Python 3

| Category | Tools |
| -------- | ----- |
| **Backend / API** | FastAPI, Uvicorn (ASGI server) |
| **HTTP** | httpx (async client) |
| **Data sources** | ESPN public NBA API (standings, schedules, scoreboards) — no key needed |
| **Data processing** | pandas |
| **Analytics** | Monte Carlo simulations, custom statistics calculator |
| **Dashboard / UI** | Streamlit, Plotly |
| **Config** | python-dotenv (`.env`) |
| **Testing** | pytest, pytest-asyncio |

##  Getting Started

### 1. Install dependencies

```powershell
pip install -r requirements.txt
```

### 2. Configure environment variables (optional)

No API key is required — the data source is ESPN's public NBA API. A `.env`
file (git-ignored) is only needed if you want to override the cache
defaults:

```env
CACHE_TTL=3600
USE_CACHE=true
```

### 3. Run the dashboard

```powershell
streamlit run streamlit_dashboard.py
```

The app opens at **http://localhost:8501**.

### 4. (Optional) Run the API backend

```powershell
uvicorn server.main:app --reload
```

### Run the tests

```powershell
pytest
```

## Security

Secrets are kept out of version control: `.env`, `.env.local`, IDE settings,
and other sensitive files are excluded via `.gitignore`.
