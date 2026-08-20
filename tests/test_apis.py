"""
Tests for the api/ package: NBAApiClient, SportsDataClient, APIManager.

Run:
    pytest tests/ -v
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.nba_api_client import NBAApiClient, TEAM_NAME_TO_ID
from api.sportsdata_api_client import Scoreboard, SportsDataClient
from api.api_manager import APIManager, CachedData, DataSource, EnrichedTeamStats


# ============================================================================
# FIXTURES: sample raw API responses (shapes captured from ESPN's live API)
# ============================================================================

def _standings_response(east_entries=None, west_entries=None):
    return {
        "children": [
            {"abbreviation": "East", "standings": {"entries": east_entries or []}},
            {"abbreviation": "West", "standings": {"entries": west_entries or []}},
        ]
    }


STANDINGS_RESPONSE = _standings_response(
    west_entries=[
        {
            "team": {"id": "13", "displayName": "Los Angeles Lakers", "abbreviation": "LAL"},
            "stats": [
                {"name": "wins", "value": 47},
                {"name": "losses", "value": 35},
                {"name": "avgPointsFor", "value": 115.5},
                {"name": "streak", "value": 2, "displayValue": "W2"},
            ],
        },
    ],
    east_entries=[
        {
            "team": {"id": "2", "displayName": "Boston Celtics", "abbreviation": "BOS"},
            "stats": [
                {"name": "wins", "value": 64},
                {"name": "losses", "value": 18},
                {"name": "avgPointsFor", "value": 120.6},
                {"name": "streak", "value": 2, "displayValue": "W2"},
            ],
        },
    ],
)


def _event(game_id, home_name, home_score, away_name, away_score,
           completed=True, date="2025-02-01T22:00Z"):
    return {
        "id": game_id,
        "date": date,
        "competitions": [{
            "status": {
                "period": 4,
                "type": {"description": "Final" if completed else "Scheduled", "completed": completed},
            },
            "competitors": [
                {"homeAway": "home", "score": home_score, "team": {"displayName": home_name}},
                {"homeAway": "away", "score": away_score, "team": {"displayName": away_name}},
            ],
        }],
    }


SCOREBOARD_RESPONSE = {"events": [_event("401705252", "Indiana Pacers", 132, "Atlanta Hawks", 119)]}


# ============================================================================
# TESTS PARA NBA API CLIENT
# ============================================================================

class TestNBAApiClient:
    def test_get_standings_parses_real_response_shape(self, monkeypatch):
        client = NBAApiClient()
        monkeypatch.setattr(client, "_make_request", AsyncMock(return_value=STANDINGS_RESPONSE))

        standings = client.get_standings(season=2024)

        assert len(standings) == 2
        lakers = next(s for s in standings if s["abbreviation"] == "LAL")
        assert lakers["wins"] == 47
        assert lakers["losses"] == 35
        assert lakers["win_pct"] == round(47 / 82, 3)
        assert lakers["points"] == 115.5
        assert lakers["conference"] == "West"

    def test_get_team_stats_uses_standings_cache(self, monkeypatch):
        client = NBAApiClient()
        monkeypatch.setattr(client, "_make_request", AsyncMock(return_value=STANDINGS_RESPONSE))

        stats = client.get_team_stats("Lakers", season=2024)

        assert stats["team"] == "Lakers"
        assert stats["wins"] == 47
        assert stats["points"] == 115.5
        # No expuesto por la API pública de ESPN — ver notas en api_manager
        assert stats["assists"] == 0.0

    def test_get_team_stats_unknown_team_returns_none(self, monkeypatch):
        client = NBAApiClient()
        monkeypatch.setattr(client, "_make_request", AsyncMock(return_value=STANDINGS_RESPONSE))

        assert client.get_team_stats("Not A Team", season=2024) is None

    def test_get_all_teams_returns_known_teams(self):
        client = NBAApiClient()
        teams = client.get_all_teams()

        assert len(teams) == len(TEAM_NAME_TO_ID)
        assert {"name": "Lakers", "id": "13"} in teams

    def test_get_recent_games_not_supported(self):
        client = NBAApiClient()
        assert client.get_recent_games("Lakers", season=2024) == []


# ============================================================================
# TESTS PARA SPORTSDATA CLIENT
# ============================================================================

class TestSportsDataClient:
    @pytest.mark.asyncio
    async def test_get_scoreboard_parses_real_response_shape(self):
        client = SportsDataClient()
        client._make_request = AsyncMock(return_value=SCOREBOARD_RESPONSE)

        games = await client.get_scoreboard(date="20250201")

        assert len(games) == 1
        game = games[0]
        assert game.home_team == "Indiana Pacers"
        assert game.away_team == "Atlanta Hawks"
        assert game.home_score == 132
        assert game.away_score == 119
        assert game.status == "Final"
        assert game.period == 4

    @pytest.mark.asyncio
    async def test_get_scoreboard_handles_request_failure(self):
        client = SportsDataClient()
        client._make_request = AsyncMock(side_effect=Exception("boom"))

        assert await client.get_scoreboard(date="20250201") == []

    @pytest.mark.asyncio
    async def test_get_player_injuries_is_a_stub(self):
        """This data source has no injuries endpoint — always returns []."""
        client = SportsDataClient()
        assert await client.get_player_injuries(season=2025) == []

    @pytest.mark.asyncio
    async def test_get_player_availability_is_a_stub(self):
        client = SportsDataClient()
        assert await client.get_player_availability(team="LAL") == []

    @pytest.mark.asyncio
    async def test_get_team_recent_games_returns_only_completed_games_sorted_desc(self):
        """The team-schedule endpoint returns the whole season in one call —
        filter to completed games only and sort most-recent-first."""
        client = SportsDataClient()
        client._make_request = AsyncMock(return_value={"events": [
            _event("1", "Los Angeles Lakers", 110, "Boston Celtics", 100, date="2024-10-23T02:00Z"),
            _event("2", "Los Angeles Lakers", 105, "Miami Heat", 98, date="2025-04-13T19:30Z"),
            _event("3", "Los Angeles Lakers", 0, "Denver Nuggets", 0, completed=False, date="2025-04-15T19:30Z"),
        ]})

        games = await client.get_team_recent_games(team_id="13", season=2025, limit=10)

        assert len(games) == 2  # el partido sin jugar queda afuera
        assert games[0].game_id == "2"  # más reciente primero
        assert games[1].game_id == "1"

    @pytest.mark.asyncio
    async def test_get_team_recent_games_respects_limit(self):
        client = SportsDataClient()
        client._make_request = AsyncMock(return_value={"events": [
            _event(str(i), "Los Angeles Lakers", 100 + i, "Boston Celtics", 90,
                   date=f"2025-01-{i:02d}T22:00Z")
            for i in range(1, 16)
        ]})

        games = await client.get_team_recent_games(team_id="13", season=2025, limit=5)

        assert len(games) == 5

    @pytest.mark.asyncio
    async def test_get_team_recent_games_handles_request_failure(self):
        client = SportsDataClient()
        client._make_request = AsyncMock(side_effect=Exception("boom"))

        assert await client.get_team_recent_games(team_id="13", season=2025) == []


# ============================================================================
# TESTS PARA API MANAGER
# ============================================================================

class TestAPIManager:
    @pytest.fixture
    def mock_nba_client(self):
        client = MagicMock()
        client.get_team_stats = MagicMock(return_value={
            "team": "LAL",
            "wins": 45,
            "losses": 20,
            "win_pct": 0.692,
        })
        client.get_player_stats = MagicMock(return_value={
            "name": "LeBron James",
            "team": "LAL",
            "points": 25.5,
            "assists": 8.3,
            "rebounds": 7.1,
            "fg_pct": 0.52,
            "games_played": 56,
        })
        return client

    @pytest.fixture
    def mock_sportsdata_client(self):
        client = MagicMock()
        client.get_player_availability = AsyncMock(return_value=[])
        return client

    @pytest.fixture
    def api_manager(self, mock_nba_client, mock_sportsdata_client):
        return APIManager(
            nba_client=mock_nba_client,
            sportsdata_client=mock_sportsdata_client,
            cache_ttl=3600
        )

    def test_cache_key_generation(self, api_manager):
        assert api_manager._cache_key("team", "LAL", 2025) == "team:LAL:2025"

    def test_cache_set_and_get(self, api_manager):
        api_manager._set_cache("test_key", {"test": "data"}, DataSource.NBA_API)
        assert api_manager._get_from_cache("test_key") == {"test": "data"}

    def test_cache_expiration(self, api_manager):
        api_manager.cache["test_key"] = CachedData(
            data={"test": "data"},
            timestamp=datetime.now() - timedelta(seconds=10),
            ttl=1,
            source=DataSource.NBA_API
        )
        assert api_manager._get_from_cache("test_key") is None

    def test_cache_clear_pattern(self, api_manager):
        api_manager._set_cache("LAL:1", "data1", DataSource.NBA_API)
        api_manager._set_cache("LAL:2", "data2", DataSource.NBA_API)
        api_manager._set_cache("BOS:1", "data3", DataSource.NBA_API)

        api_manager.clear_cache(pattern="LAL:*")

        assert "LAL:1" not in api_manager.cache
        assert "LAL:2" not in api_manager.cache
        assert "BOS:1" in api_manager.cache

    @pytest.mark.asyncio
    async def test_get_enriched_team_stats_with_no_availability_data(self, api_manager):
        """When the availability source returns nothing, the team is assumed healthy."""
        stats = await api_manager.get_enriched_team_stats("LAL", 2025)

        assert stats is not None
        assert stats.team == "LAL"
        assert stats.wins == 45
        assert stats.losses == 20
        assert stats.team_health_score == 1.0
        assert stats.injured_players == 0
        assert stats.critical_absences == []

    @pytest.mark.asyncio
    async def test_get_enriched_team_stats_with_injured_players(self, api_manager, mock_sportsdata_client):
        mock_sportsdata_client.get_player_availability = AsyncMock(return_value=[
            SimpleNamespace(player_name="LeBron James", available=False, impact_on_team=0.8),
            SimpleNamespace(player_name="Anthony Davis", available=True, impact_on_team=0.0),
        ])

        stats = await api_manager.get_enriched_team_stats("LAL", 2025)

        assert stats.injured_players == 1
        assert stats.unavailable_players == 1
        assert stats.critical_absences == ["LeBron James"]
        assert 0.0 <= stats.team_health_score < 1.0

    @pytest.mark.asyncio
    async def test_get_enriched_team_stats_missing_team_returns_none(self, api_manager, mock_nba_client):
        mock_nba_client.get_team_stats = MagicMock(return_value=None)
        assert await api_manager.get_enriched_team_stats("XXX", 2025) is None

    @pytest.mark.asyncio
    async def test_get_enriched_player_stats_without_injury_data(self, api_manager):
        """No injury endpoint is available from this data source — impact stays at 0."""
        stats = await api_manager.get_enriched_player_stats(player_id=2544, season=2025)

        assert stats is not None
        assert stats.player_name == "LeBron James"
        assert stats.is_injured is False
        assert stats.injury_status == "Unknown"
        assert stats.adjusted_impact == pytest.approx(25.5 + 8.3)

    @pytest.mark.asyncio
    async def test_get_all_team_stats(self, api_manager):
        stats_dict = await api_manager.get_all_team_stats(["LAL", "BOS"], 2025)

        assert isinstance(stats_dict, dict)
        assert set(stats_dict.keys()) == {"LAL", "BOS"}

    def test_get_cache_stats(self, api_manager):
        api_manager._set_cache("key1", "data1", DataSource.NBA_API)
        api_manager._set_cache("key2", "data2", DataSource.SPORTSDATA)

        stats = api_manager.get_cache_stats()

        assert stats["total_entries"] == 2
        assert stats["valid_entries"] == 2


# ============================================================================
# TESTS PARA DATACLASSES
# ============================================================================

class TestDataClasses:
    def test_enriched_team_stats_creation(self):
        stats = EnrichedTeamStats(
            team="LAL",
            season=2025,
            wins=45,
            losses=20,
            win_pct=0.692,
            injured_players=3,
            unavailable_players=2,
            team_health_score=0.85,
            projected_win_pct_adjusted=0.65,
            critical_absences=["LeBron James"]
        )

        assert stats.team == "LAL"
        assert stats.team_health_score == 0.85
        assert len(stats.critical_absences) == 1

    def test_cached_data_expiration(self):
        fresh = CachedData(
            data={"test": "data"},
            timestamp=datetime.now(),
            ttl=3600,
            source=DataSource.NBA_API
        )
        assert not fresh.is_expired()

        stale = CachedData(
            data={"test": "data"},
            timestamp=datetime.now() - timedelta(hours=2),
            ttl=3600,
            source=DataSource.NBA_API
        )
        assert stale.is_expired()

    def test_scoreboard_dataclass(self):
        game = Scoreboard(
            game_id="1",
            home_team="Indiana Pacers",
            away_team="Atlanta Hawks",
            home_score=132,
            away_score=119,
            status="Final",
            period=4,
            date="20250201"
        )
        assert game.home_score == 132


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
