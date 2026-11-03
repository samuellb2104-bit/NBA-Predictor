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
from api.sportsdata_api_client import (
    PlayerAvailability, Scoreboard, SportsDataClient, current_season, parse_injuries,
)
from api.api_manager import (
    ROTATION_SIZE, APIManager, CachedData, DataSource, EnrichedTeamStats,
)


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
    async def test_get_injuries_parses_real_shape(self):
        client = SportsDataClient()
        client._make_request = AsyncMock(return_value=INJURIES_RESPONSE)

        players = await client.get_injuries()

        assert len(players) == 4
        johnson = players[0]
        assert johnson.player_name == "Jalen Johnson"
        assert johnson.team_id == "1"
        assert johnson.status == "Out"
        assert johnson.available is False
        assert johnson.impact_on_team == 1.0
        assert "ruled out" in johnson.short_comment
        assert johnson.date == "2026-11-02T22:58Z"

    def test_parse_injuries_status_weights(self):
        by_name = {p.player_name: p for p in parse_injuries(INJURIES_RESPONSE)}
        assert by_name["Day Tripper"].available is True
        assert by_name["Day Tripper"].impact_on_team == 0.5
        assert by_name["Sus Pended"].available is False
        assert by_name["Sus Pended"].impact_on_team == 1.0

    def test_parse_injuries_empty_payload(self):
        assert parse_injuries({}) == []

    @pytest.mark.asyncio
    async def test_get_injuries_is_cached(self):
        client = SportsDataClient()
        client._make_request = AsyncMock(return_value=INJURIES_RESPONSE)

        await client.get_injuries()
        await client.get_injuries()

        assert client._make_request.call_count == 1

    @pytest.mark.asyncio
    async def test_get_injuries_refetches_after_ttl(self):
        client = SportsDataClient()
        client._make_request = AsyncMock(return_value=INJURIES_RESPONSE)

        await client.get_injuries()
        ts, players = client._injuries_cache
        client._injuries_cache = (ts - client.INJURIES_TTL - 1, players)
        await client.get_injuries()

        assert client._make_request.call_count == 2

    @pytest.mark.asyncio
    async def test_get_injuries_propagates_request_failure(self):
        client = SportsDataClient()
        client._make_request = AsyncMock(side_effect=Exception("boom"))

        with pytest.raises(Exception):
            await client.get_injuries()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("identifier", ["LAL", "lal", "Lakers", "Los Angeles Lakers", "13"])
    async def test_get_player_availability_filters_team_by_any_identifier(self, identifier):
        client = SportsDataClient()
        client._make_request = AsyncMock(return_value=INJURIES_RESPONSE)

        players = await client.get_player_availability(identifier, current_season())

        assert [p.player_name for p in players] == ["Anthony Davis", "Day Tripper"]
        assert all(p.team_id == "13" for p in players)

    @pytest.mark.asyncio
    async def test_get_player_availability_unknown_or_healthy_team(self):
        client = SportsDataClient()
        client._make_request = AsyncMock(return_value=INJURIES_RESPONSE)

        assert await client.get_player_availability("XXX", current_season()) == []
        assert await client.get_player_availability("BOS", current_season()) == []

    @pytest.mark.asyncio
    async def test_get_player_availability_past_season_returns_empty_without_fetch(self):
        client = SportsDataClient()
        client._make_request = AsyncMock(return_value=INJURIES_RESPONSE)

        assert await client.get_player_availability("LAL", current_season() - 1) == []
        client._make_request.assert_not_called()

    def test_current_season_rolls_over_in_october(self):
        assert current_season(datetime(2026, 9, 30)) == 2026
        assert current_season(datetime(2026, 10, 1)) == 2027
        assert current_season(datetime(2027, 1, 15)) == 2027

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


def _injury(id_, name, status, comment="comment"):
    first, _, last = name.partition(" ")
    return {
        "id": id_, "status": status, "date": "2026-11-02T22:58Z",
        "shortComment": comment, "longComment": "long",
        "athlete": {"firstName": first, "lastName": last, "displayName": name,
                    "shortName": f"{first[0]}. {last}", "links": []},
    }


# Forma real de GET /injuries, recortada (ids de equipo ESPN: ATL=1, LAL=13).
INJURIES_RESPONSE = {
    "timestamp": "2026-11-03T03:32:38Z",
    "status": "success",
    "season": {"year": 2027, "type": 2, "name": "Regular Season", "displayName": "2026-27"},
    "injuries": [
        {"id": "1", "displayName": "Atlanta Hawks", "injuries": [
            _injury("537236", "Jalen Johnson", "Out",
                    "Johnson (ankle) has been ruled out for Monday's game versus Indiana."),
            _injury("2", "Sus Pended", "Suspension"),
        ]},
        {"id": "13", "displayName": "Los Angeles Lakers", "injuries": [
            _injury("3", "Anthony Davis", "Out"),
            _injury("4", "Day Tripper", "Day-To-Day"),
        ]},
    ],
}


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
        return client

    @pytest.fixture
    def mock_sportsdata_client(self):
        client = MagicMock()
        client.get_player_availability = AsyncMock(return_value=[])
        return client

    @pytest.fixture(autouse=True)
    def season_2025_is_current(self, monkeypatch):
        monkeypatch.setattr("api.api_manager.is_current_season", lambda season: season == 2025)

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
            PlayerAvailability("LeBron James", "13", "Out", False, 1.0, "", ""),
            PlayerAvailability("Anthony Davis", "13", "Day-To-Day", True, 0.5, "", ""),
        ])

        stats = await api_manager.get_enriched_team_stats("LAL", 2025)

        assert stats.injured_players == 2
        assert stats.unavailable_players == 1  # solo el Out
        assert stats.team_health_score == pytest.approx(1 - 1.5 / ROTATION_SIZE)
        assert stats.injury_data_available is True
        # Requiere datos de importancia por jugador; no se inventa.
        assert stats.critical_absences == []

    @pytest.mark.asyncio
    async def test_one_out_player_does_not_zero_the_health_score(self, api_manager, mock_sportsdata_client):
        mock_sportsdata_client.get_player_availability = AsyncMock(return_value=[
            PlayerAvailability("LeBron James", "13", "Out", False, 1.0, "", ""),
        ])

        stats = await api_manager.get_enriched_team_stats("LAL", 2025)

        assert stats.team_health_score == pytest.approx(0.9)
        assert stats.team_health_score > 0.0

    @pytest.mark.asyncio
    async def test_health_score_is_floored_at_zero(self, api_manager, mock_sportsdata_client):
        mock_sportsdata_client.get_player_availability = AsyncMock(return_value=[
            PlayerAvailability(f"P{i}", "13", "Out", False, 1.0, "", "")
            for i in range(ROTATION_SIZE + 3)
        ])

        stats = await api_manager.get_enriched_team_stats("LAL", 2025)

        assert stats.team_health_score == 0.0

    @pytest.mark.asyncio
    async def test_non_current_season_has_no_injury_data(self, api_manager, mock_sportsdata_client):
        stats = await api_manager.get_enriched_team_stats("LAL", 2024)

        assert stats.injury_data_available is False
        mock_sportsdata_client.get_player_availability.assert_not_called()

    @pytest.mark.asyncio
    async def test_injury_fetch_failure_marks_data_unavailable(self, api_manager, mock_sportsdata_client):
        mock_sportsdata_client.get_player_availability = AsyncMock(side_effect=Exception("boom"))

        stats = await api_manager.get_enriched_team_stats("LAL", 2025)

        assert stats is not None
        assert stats.injury_data_available is False
        assert stats.team_health_score == 1.0

    @pytest.mark.asyncio
    async def test_compare_teams_health_includes_injury_data_flag(self, api_manager):
        result = await api_manager.compare_teams_health("LAL", "BOS", 2025)

        assert result["LAL"]["injury_data_available"] is True
        assert result["BOS"]["injury_data_available"] is True

    @pytest.mark.asyncio
    async def test_get_enriched_team_stats_missing_team_returns_none(self, api_manager, mock_nba_client):
        mock_nba_client.get_team_stats = MagicMock(return_value=None)
        assert await api_manager.get_enriched_team_stats("XXX", 2025) is None

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
