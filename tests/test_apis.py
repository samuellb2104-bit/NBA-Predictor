"""
Tests unitarios para los nuevos módulos de integración de APIs.

Usa pytest y pytest-asyncio.

Ejecutar:
    pytest tests/ -v
    pytest tests/ -v --cov=api  # Con coverage
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

# Imports (ajustar paths según tu estructura)
from sportsdata_api_client import (
    SportsDataClient,
    PlayerInjury,
    PlayerAvailability,
    CachedData,
    DataSource
)
from api_manager import APIManager, EnrichedPlayerStats, EnrichedTeamStats


# ============================================================================
# TESTS PARA SPORTSDATA CLIENT
# ============================================================================

class TestSportsDataClient:
    """Tests para SportsDataClient"""

    @pytest.fixture
    async def client(self):
        """Fixture que proporciona un cliente"""
        client = SportsDataClient(api_key="test_key")
        yield client
        await client.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_client_initialization(self):
        """Test que el cliente se inicializa correctamente"""
        client = SportsDataClient(api_key="test_key")
        assert client.api_key == "test_key"
        assert client.timeout == 30
        assert "X-RapidAPI-Key" in client.headers

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test que el context manager funciona"""
        async with SportsDataClient(api_key="test_key") as client:
            assert client.client is not None
            assert isinstance(client.client, AsyncMock) or hasattr(client.client, 'get')

    @pytest.mark.asyncio
    async def test_cache_key_generation(self):
        """Test generación de cache keys"""
        client = SportsDataClient(api_key="test_key")
        key = client._cache_key("player", 123, 2025)
        assert key == "player:123:2025"
        assert isinstance(key, str)

    @pytest.mark.asyncio
    async def test_calculate_player_impact_healthy(self):
        """Test cálculo de impacto para jugador sano"""
        player_data = {"points": 25, "assists": 8}
        impact = SportsDataClient._calculate_player_impact(
            player_data,
            is_injured=False,
            injury=None
        )
        assert impact == 0.0  # No hay impacto si está sano

    @pytest.mark.asyncio
    async def test_calculate_player_impact_injured(self):
        """Test cálculo de impacto para jugador lesionado"""
        player_data = {"points": 25}
        injury = MagicMock()
        injury.injury_status = "Out"

        impact = SportsDataClient._calculate_player_impact(
            player_data,
            is_injured=True,
            injury=injury
        )
        assert impact == 1.0  # Máximo impacto

    @pytest.mark.asyncio
    async def test_calculate_player_impact_day_to_day(self):
        """Test cálculo de impacto para 'Day-to-Day'"""
        injury = MagicMock()
        injury.injury_status = "Day-to-Day"

        impact = SportsDataClient._calculate_player_impact(
            {},
            is_injured=True,
            injury=injury
        )
        assert impact == 0.6

    @pytest.mark.asyncio
    async def test_get_player_injuries_empty(self):
        """Test get_player_injuries cuando no hay lesiones"""
        client = SportsDataClient(api_key="test_key")
        client._make_request = AsyncMock(return_value={"response": []})

        injuries = await client.get_player_injuries(season=2025)
        assert injuries == []

    @pytest.mark.asyncio
    async def test_get_player_injuries_with_data(self):
        """Test get_player_injuries con datos"""
        client = SportsDataClient(api_key="test_key")

        mock_response = {
            "response": [
                {
                    "player": {"id": 201939, "name": "LeBron James"},
                    "team": {"name": "LAL"},
                    "status": "Day-to-Day",
                    "detail": "Ankle sprain",
                    "date": "2025-01-15T10:00:00Z"
                }
            ]
        }

        client._make_request = AsyncMock(return_value=mock_response)
        injuries = await client.get_player_injuries(season=2025, team="LAL")

        assert len(injuries) == 1
        assert injuries[0].player_name == "LeBron James"
        assert injuries[0].team == "LAL"
        assert injuries[0].injury_status == "Day-to-Day"

    @pytest.mark.asyncio
    async def test_batch_get_injuries(self):
        """Test obtener lesiones de múltiples equipos"""
        client = SportsDataClient(api_key="test_key")

        # Mock para retornar lesiones según equipo
        async def mock_get_injuries(season, team):
            if team == "LAL":
                return [MagicMock(team="LAL", player_name="LeBron")]
            elif team == "BOS":
                return [MagicMock(team="BOS", player_name="Jayson")]
            return []

        client.get_player_injuries = mock_get_injuries

        result = await client.batch_get_injuries(["LAL", "BOS"], season=2025)

        assert "LAL" in result
        assert "BOS" in result
        assert len(result["LAL"]) == 1
        assert len(result["BOS"]) == 1


# ============================================================================
# TESTS PARA API MANAGER
# ============================================================================

class TestAPIManager:
    """Tests para APIManager"""

    @pytest.fixture
    def mock_nba_client(self):
        """Mock del cliente NBA"""
        client = MagicMock()
        client.get_player_stats = AsyncMock(return_value={
            "name": "LeBron James",
            "team": "LAL",
            "points": 25.5,
            "assists": 8.3,
            "rebounds": 7.1,
            "fg_pct": 0.52,
            "games_played": 56
        })
        client.get_team_stats = AsyncMock(return_value={
            "team": "LAL",
            "wins": 45,
            "losses": 20,
            "win_pct": 0.692
        })
        return client

    @pytest.fixture
    def mock_sportsdata_client(self):
        """Mock del cliente SportsData"""
        client = MagicMock()
        client.get_player_by_id = AsyncMock(return_value=None)
        client.get_player_availability = AsyncMock(return_value=[])
        client._calculate_player_impact = lambda *args, **kwargs: 0.0
        return client

    @pytest.fixture
    def api_manager(self, mock_nba_client, mock_sportsdata_client):
        """Fixture que proporciona un APIManager"""
        return APIManager(
            nba_client=mock_nba_client,
            sportsdata_client=mock_sportsdata_client,
            cache_ttl=3600
        )

    def test_cache_key_generation(self, api_manager):
        """Test generación de cache keys"""
        key = api_manager._cache_key("team", "LAL", 2025)
        assert key == "team:LAL:2025"

    def test_cache_set_and_get(self, api_manager):
        """Test almacenamiento y recuperación del caché"""
        key = "test_key"
        data = {"test": "data"}

        api_manager._set_cache(key, data, DataSource.NBA_API)
        cached = api_manager._get_from_cache(key)

        assert cached == data

    def test_cache_expiration(self, api_manager):
        """Test que el caché expira correctamente"""
        key = "test_key"
        data = {"test": "data"}

        # Crear un CachedData con TTL muy corto
        api_manager.cache[key] = CachedData(
            data=data,
            timestamp=datetime.now() - timedelta(seconds=10),
            ttl=1,  # Expira en 1 segundo
            source=DataSource.NBA_API
        )

        # Debe estar expirado
        cached = api_manager._get_from_cache(key)
        assert cached is None

    def test_cache_clear_pattern(self, api_manager):
        """Test limpieza de caché con patrón"""
        api_manager._set_cache("LAL:1", "data1", DataSource.NBA_API)
        api_manager._set_cache("LAL:2", "data2", DataSource.NBA_API)
        api_manager._set_cache("BOS:1", "data3", DataSource.NBA_API)

        api_manager.clear_cache(pattern="LAL:*")

        assert "LAL:1" not in api_manager.cache
        assert "LAL:2" not in api_manager.cache
        assert "BOS:1" in api_manager.cache

    @pytest.mark.asyncio
    async def test_get_enriched_team_stats(self, api_manager):
        """Test obtención de stats enriquecidos de equipo"""
        stats = await api_manager.get_enriched_team_stats("LAL", 2025)

        assert stats is not None
        assert stats.team == "LAL"
        assert stats.wins == 45
        assert stats.losses == 20
        assert isinstance(stats.team_health_score, float)

    @pytest.mark.asyncio
    async def test_get_all_team_stats(self, api_manager):
        """Test obtención de stats de múltiples equipos"""
        stats_dict = await api_manager.get_all_team_stats(["LAL", "BOS"], 2025)

        # El mock retorna datos para ambos
        assert isinstance(stats_dict, dict)

    def test_get_cache_stats(self, api_manager):
        """Test estadísticas del caché"""
        api_manager._set_cache("key1", "data1", DataSource.NBA_API)
        api_manager._set_cache("key2", "data2", DataSource.SPORTSDATA)

        stats = api_manager.get_cache_stats()

        assert stats["total_entries"] == 2
        assert stats["valid_entries"] == 2


# ============================================================================
# TESTS PARA DATACLASSES
# ============================================================================

class TestDataClasses:
    """Tests para dataclasses"""

    def test_player_injury_creation(self):
        """Test creación de PlayerInjury"""
        injury = PlayerInjury(
            player_id=201939,
            player_name="LeBron James",
            team="LAL",
            injury_status="Day-to-Day",
            injury_description="Ankle sprain",
            return_date="2025-01-20",
            updated_at="2025-01-15T10:00:00Z"
        )

        assert injury.player_name == "LeBron James"
        assert injury.team == "LAL"
        assert injury.injury_status == "Day-to-Day"

    def test_enriched_team_stats_creation(self):
        """Test creación de EnrichedTeamStats"""
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
        """Test expiración de CachedData"""
        # No expirado
        cached = CachedData(
            data={"test": "data"},
            timestamp=datetime.now(),
            ttl=3600,
            source=DataSource.NBA_API
        )
        assert not cached.is_expired()

        # Expirado
        cached_expired = CachedData(
            data={"test": "data"},
            timestamp=datetime.now() - timedelta(hours=2),
            ttl=3600,
            source=DataSource.NBA_API
        )
        assert cached_expired.is_expired()


# ============================================================================
# TESTS DE INTEGRACIÓN
# ============================================================================

class TestIntegration:
    """Tests de integración end-to-end"""

    @pytest.mark.asyncio
    async def test_full_enrichment_pipeline(self):
        """Test pipeline completo de enriquecimiento"""
        # Setup
        mock_nba = MagicMock()
        mock_nba.get_team_stats = AsyncMock(return_value={
            "team": "LAL",
            "wins": 45,
            "losses": 20,
            "win_pct": 0.692
        })

        mock_sportsdata = MagicMock()
        mock_sportsdata.get_player_availability = AsyncMock(return_value=[
            MagicMock(
                player_name="LeBron",
                available=False,
                impact_on_team=0.8
            )
        ])

        manager = APIManager(mock_nba, mock_sportsdata)

        # Execute
        stats = await manager.get_enriched_team_stats("LAL", 2025)

        # Assert
        assert stats is not None
        assert stats.injured_players == 1
        assert stats.unavailable_players == 1


# ============================================================================
# PYTEST CONFIG
# ============================================================================

@pytest.fixture(scope="session")
def event_loop():
    """Fixture para pytest-asyncio"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])