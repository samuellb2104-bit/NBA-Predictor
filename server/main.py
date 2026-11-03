"""
FastAPI app - ejecutar con: uvicorn server.main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.api_manager import APIManager
from api.nba_api_client import NBAApiClient
from api.sportsdata_api_client import SportsDataClient
from server.fastapi_routes import router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Construye los clientes y el APIManager y los deja en app.state."""
    app.state.api_manager = APIManager(
        nba_client=NBAApiClient(),
        sportsdata_client=SportsDataClient(),
        cache_ttl=3600,
    )
    yield
    app.state.api_manager = None


app = FastAPI(title="NBA Predictor API", lifespan=lifespan)
app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
