"""Los ids de TEAM_NAME_TO_ID deben coincidir con la lista real de ESPN."""

import httpx
import pytest

from api.nba_api_client import TEAM_NAME_TO_ABBR, TEAM_NAME_TO_ID, resolve_team

# id ESPN -> (abreviatura, nombre). Copiado de GET .../basketball/nba/teams.
ESPN_TEAMS = {
    "1": ("ATL", "Hawks"), "2": ("BOS", "Celtics"), "3": ("NO", "Pelicans"),
    "4": ("CHI", "Bulls"), "5": ("CLE", "Cavaliers"), "6": ("DAL", "Mavericks"),
    "7": ("DEN", "Nuggets"), "8": ("DET", "Pistons"), "9": ("GS", "Warriors"),
    "10": ("HOU", "Rockets"), "11": ("IND", "Pacers"), "12": ("LAC", "Clippers"),
    "13": ("LAL", "Lakers"), "14": ("MIA", "Heat"), "15": ("MIL", "Bucks"),
    "16": ("MIN", "Timberwolves"), "17": ("BKN", "Nets"), "18": ("NY", "Knicks"),
    "19": ("ORL", "Magic"), "20": ("PHI", "76ers"), "21": ("PHX", "Suns"),
    "22": ("POR", "Trail Blazers"), "23": ("SAC", "Kings"), "24": ("SA", "Spurs"),
    "25": ("OKC", "Thunder"), "26": ("UTAH", "Jazz"), "27": ("WSH", "Wizards"),
    "28": ("TOR", "Raptors"), "29": ("MEM", "Grizzlies"), "30": ("CHA", "Hornets"),
}


def test_fixture_has_30_teams():
    assert len(ESPN_TEAMS) == 30


@pytest.mark.parametrize("tid,expected", ESPN_TEAMS.items())
def test_ids_and_abbreviations_match_espn(tid, expected):
    abbr, name = expected
    assert TEAM_NAME_TO_ID[name] == tid
    assert TEAM_NAME_TO_ABBR[name] == abbr


@pytest.mark.parametrize("tid,expected", ESPN_TEAMS.items())
def test_resolve_team_by_id(tid, expected):
    abbr, name = expected
    team = resolve_team(tid)
    assert team is not None
    assert (team.id, team.abbr, team.name) == (tid, abbr, name)


def test_maps_cover_exactly_the_same_teams():
    assert set(TEAM_NAME_TO_ID) == set(TEAM_NAME_TO_ABBR)
    assert set(TEAM_NAME_TO_ID.values()) == set(ESPN_TEAMS)


@pytest.mark.live
def test_live_matches_espn_teams_endpoint():
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
    data = httpx.get(url, timeout=15).json()
    teams = data["sports"][0]["leagues"][0]["teams"]
    live = {t["team"]["id"]: t["team"]["abbreviation"] for t in teams}
    assert live == {tid: v[0] for tid, v in ESPN_TEAMS.items()}
