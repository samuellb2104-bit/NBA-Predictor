"""
Tests for team resolution and the FastAPI app (clients mocked).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from api.api_manager import APIManager
from api.nba_api_client import (
    TEAM_ABBREVIATIONS, TEAM_NAME_TO_ID, NBAApiClient, resolve_team,
)
from server.main import app


# ============================================================================
# resolve_team
# ============================================================================

class TestResolveTeam:
    @pytest.mark.parametrize("value", [
        "Lakers", "lakers", "LAL", "lal", "13", "Los Angeles Lakers", " LAL ",
    ])
    def test_lakers_variants(self, value):
        info = resolve_team(value)
        assert info is not None and info.abbr == "LAL" and info.id == "13"

    @pytest.mark.parametrize("alias,abbr", [
        ("GSW", "GS"), ("GS", "GS"), ("NOP", "NO"), ("NYK", "NY"),
        ("SAS", "SA"), ("UTA", "UTAH"), ("UTAH", "UTAH"), ("WAS", "WSH"),
        ("Warriors", "GS"), ("Trail Blazers", "POR"),
    ])
    def test_aliases(self, alias, abbr):
        assert resolve_team(alias).abbr == abbr

    @pytest.mark.parametrize("value", ["", None, "XXX", "La", "Not A Team"])
    def test_unknown(self, value):
        assert resolve_team(value) is None

    def test_thunder_id_fixed(self):
        assert TEAM_NAME_TO_ID["Thunder"] == "25"
        assert resolve_team("OKC").id == "25"

    def test_thirty_unique_teams_including_indiana(self):
        assert len(TEAM_ABBREVIATIONS) == 30
        assert len(set(TEAM_ABBREVIATIONS)) == 30
        assert "IND" in TEAM_ABBREVIATIONS
        assert len(set(TEAM_NAME_TO_ID.values())) == 30

    def test_get_team_stats_accepts_code(self, monkeypatch):
        client = NBAApiClient()
        client._standings_cache = {2024: [
            {"team": "Los Angeles Lakers", "abbreviation": "LAL", "team_id": "13",
             "wins": 47, "losses": 35, "win_pct": 0.573, "points": 115.5},
        ]}
        for ident in ("LAL", "Lakers", "lal", "13"):
            assert client.get_team_stats(ident, 2024)["wins"] == 47
        assert client.get_team_stats("BOS", 2024) is None
        assert client.get_team_stats("XXX", 2024) is None

    def test_standings_cache_is_keyed_by_season(self):
        client = NBAApiClient()
        wins_by_season = {2024: 47, 2025: 50}

        def fake_standings(season):
            client._standings_cache[season] = [
                {"team": "Los Angeles Lakers", "abbreviation": "LAL", "team_id": "13",
                 "wins": wins_by_season[season], "losses": 82 - wins_by_season[season],
                 "win_pct": 0.6, "points": 110.0},
            ]
            return client._standings_cache[season]

        client.get_standings = MagicMock(side_effect=fake_standings)
        assert client.get_team_stats("LAL", 2024)["wins"] == 47
        assert client.get_team_stats("LAL", 2025)["wins"] == 50
        assert client.get_team_stats("LAL", 2024)["wins"] == 47
        assert client.get_standings.call_count == 2


# ============================================================================
# FastAPI app
# ============================================================================

@pytest.fixture
def client(monkeypatch):
    nba = MagicMock()
    nba.get_team_stats = MagicMock(side_effect=lambda team, season: (
        {"wins": 47, "losses": 35, "win_pct": 0.573} if team == "LAL" else None
    ))
    sports = MagicMock()
    sports.get_player_availability = AsyncMock(return_value=[])
    # La temporada 2025 se trata como la vigente para estos tests.
    monkeypatch.setattr("api.api_manager.is_current_season", lambda season: season == 2025)
    with TestClient(app) as c:
        # El lifespan crea clientes reales; se reemplaza por mocks.
        app.state.api_manager = APIManager(nba, sports, cache_ttl=60)
        yield c


class TestApp:
    def test_team_stats_ok(self, client):
        r = client.get("/api/v1/teams/LAL/stats?season=2025")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["team"] == "LAL"
        assert data["record"]["wins"] == 47
        assert data["health"]["injury_data_available"] is True
        assert data["health"]["fetch_failed"] is False
        assert data["record"]["points"] == 0.0
        assert data["record"]["streak"] == ""

    def test_team_stats_past_season_flags_no_injury_data(self, client):
        data = client.get("/api/v1/teams/LAL/stats?season=2024").json()["data"]
        assert data["health"]["injury_data_available"] is False
        assert data["health"]["fetch_failed"] is False

    def test_team_stats_fetch_failure_current_season(self, client):
        client.app.state.api_manager.sportsdata_client.get_player_availability = AsyncMock(
            side_effect=Exception("boom"))
        data = client.get("/api/v1/teams/LAL/stats?season=2025").json()["data"]
        assert data["health"]["injury_data_available"] is False
        assert data["health"]["fetch_failed"] is True
        rows = client.get("/api/v1/teams?teams=LAL&season=2025").json()["data"]
        assert rows[0]["fetch_failed"] is True

    def test_team_stats_points_and_streak(self, client):
        client.app.state.api_manager.nba_client.get_team_stats = MagicMock(
            return_value={"wins": 1, "losses": 1, "win_pct": 0.5, "points": 114.26, "streak": "L2"})
        rec = client.get("/api/v1/teams/LAL/stats?season=2025").json()["data"]["record"]
        assert rec["points"] == 114.3
        assert rec["streak"] == "L2"

    def test_all_teams_and_compare_surface_injury_flag(self, client):
        rows = client.get("/api/v1/teams?teams=LAL&season=2025").json()["data"]
        assert rows[0]["injury_data_available"] is True
        assert rows[0]["fetch_failed"] is False
        client.app.state.api_manager.nba_client.get_team_stats = MagicMock(
            return_value={"wins": 40, "losses": 42, "win_pct": 0.49})
        cmp = client.get("/api/v1/compare/teams?team1=LAL&team2=BOS&season=2025").json()
        assert cmp["comparison"]["LAL"]["injury_data_available"] is True

    def test_team_stats_alias_and_name(self, client):
        assert client.get("/api/v1/teams/lakers/stats").status_code == 200

    def test_unknown_team_404(self, client):
        assert client.get("/api/v1/teams/XXX/stats").status_code == 404

    def test_known_team_without_data_404(self, client):
        # BOS existe pero el mock no devuelve datos: debe seguir siendo 404, no 500.
        assert client.get("/api/v1/teams/BOS/stats").status_code == 404

    def test_health_check(self, client):
        r = client.get("/api/v1/health-check")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_health_check_unhealthy_is_503(self, client):
        app.state.api_manager = None
        r = client.get("/api/v1/health-check")
        assert r.status_code == 503
        assert r.json()["status"] == "unhealthy"

    def test_compare_same_team_400(self, client):
        assert client.get("/api/v1/compare/teams?team1=GSW&team2=GS").status_code == 400

    def test_all_teams_default_requests_thirty(self, client):
        r = client.get("/api/v1/teams")
        assert r.status_code == 200
        # El mock solo tiene datos para LAL.
        assert r.json()["count"] == 1
        called = {c.args[0] for c in client.app.state.api_manager.nba_client.get_team_stats.call_args_list}
        assert len(called) == 30 and "IND" in called


def test_default_season_is_current_season(client):
    from api.sportsdata_api_client import current_season
    assert client.get("/api/v1/teams/LAL/stats").json()["data"]["season"] == current_season()
