import pandas as pd
import random


# -----------------------------
# BUILD TEAM STATISTICS
# -----------------------------

def build_team_stats(df):

    teams = {}

    for team in df["TEAM_ABBREVIATION"].unique():

        team_df = df[df["TEAM_ABBREVIATION"] == team]

        wins = team_df["W"].sum()
        losses = team_df["L"].sum()

        fg_pct = (
            team_df["FGM"].sum() /
            team_df["FGA"].sum()
        ) if team_df["FGA"].sum() > 0 else 0

        three_pct = (
            team_df["FG3M"].sum() /
            team_df["FG3A"].sum()
        ) if team_df["FG3A"].sum() > 0 else 0

        teams[team] = {
            "assists": team_df["AST"].sum(),
            "rebounds": team_df["REB"].sum(),
            "fg_pct": fg_pct,
            "three_pct": three_pct,
            "win_pct": wins / (wins + losses)
            if (wins + losses) > 0 else 0
        }

    return teams


# -----------------------------
# NORMALIZE STATS
# -----------------------------

def normalize_stats(team_stats):

    metrics = [
        "assists",
        "rebounds",
        "fg_pct",
        "three_pct",
        "win_pct"
    ]

    for metric in metrics:

        values = [
            team_stats[team][metric]
            for team in team_stats
        ]

        minimum = min(values)
        maximum = max(values)

        for team in team_stats:

            if maximum == minimum:
                team_stats[team][metric] = 0

            else:
                team_stats[team][metric] = (
                    team_stats[team][metric] - minimum
                ) / (
                    maximum - minimum
                )

    return team_stats


# -----------------------------
# TEAM SCORE
# -----------------------------

def calculate_team_score(team):

    return (
        0.35 * team["win_pct"] +
        0.25 * team["fg_pct"] +
        0.20 * team["three_pct"] +
        0.10 * team["rebounds"] +
        0.10 * team["assists"]
    )


# -----------------------------
# SINGLE MATCHUP
# -----------------------------

def simulate_matchup(team1, team2, team_stats):

    score1 = calculate_team_score(
        team_stats[team1]
    )

    score2 = calculate_team_score(
        team_stats[team2]
    )

    probability_team1 = (
        score1 /
        (score1 + score2)
    )

    winner = random.choices(
        [team1, team2],
        weights=[
            probability_team1,
            1 - probability_team1
        ]
    )[0]

    return winner


# -----------------------------
# PLAY-IN TOURNAMENT
# -----------------------------

def simulate_playin(seeds, team_stats):

    seed7 = seeds[6]
    seed8 = seeds[7]
    seed9 = seeds[8]
    seed10 = seeds[9]

    game1_winner = simulate_matchup(
        seed7,
        seed8,
        team_stats
    )

    game1_loser = (
        seed8
        if game1_winner == seed7
        else seed7
    )

    game2_winner = simulate_matchup(
        seed9,
        seed10,
        team_stats
    )

    game3_winner = simulate_matchup(
        game1_loser,
        game2_winner,
        team_stats
    )

    return game1_winner, game3_winner


# -----------------------------
# PLAYOFF SIMULATION
# -----------------------------

def simulate_playoffs(team_stats):

    # Example seeds
    west = [
        "OKC",
        "SAS",
        "DEN",
        "LAL",
        "HOU",
        "MIN",
        "POR",
        "PHX",
        "LAC",
        "GSW"
    ]

    east = [
        "DET",
        "BOS",
        "NYK",
        "CLE",
        "TOR",
        "ATL",
        "PHI",
        "ORL",
        "CHA",
        "MIA"
    ]

    west_7, west_8 = simulate_playin(
        west,
        team_stats
    )

    east_7, east_8 = simulate_playin(
        east,
        team_stats
    )

    first_round = [

        (west[0], west_8),
        (west[1], west_7),
        (west[2], west[5]),
        (west[3], west[4]),

        (east[0], east_8),
        (east[1], east_7),
        (east[2], east[5]),
        (east[3], east[4])
    ]

    winners = []

    for team1, team2 in first_round:

        winners.append(
            simulate_matchup(
                team1,
                team2,
                team_stats
            )
        )

    second_round = [

        (winners[0], winners[1]),
        (winners[2], winners[3]),

        (winners[4], winners[5]),
        (winners[6], winners[7])
    ]

    semifinal_winners = []

    for team1, team2 in second_round:

        semifinal_winners.append(
            simulate_matchup(
                team1,
                team2,
                team_stats
            )
        )

    conference_finals = [

        (
            semifinal_winners[0],
            semifinal_winners[1]
        ),

        (
            semifinal_winners[2],
            semifinal_winners[3]
        )
    ]

    finalists = []

    for team1, team2 in conference_finals:

        finalists.append(
            simulate_matchup(
                team1,
                team2,
                team_stats
            )
        )

    champion = simulate_matchup(
        finalists[0],
        finalists[1],
        team_stats
    )

    return champion


# -----------------------------
# MONTE CARLO
# -----------------------------

def monte_carlo(
        team_stats,
        iterations=10000):

    champions = {}

    for _ in range(iterations):

        champion = simulate_playoffs(
            team_stats
        )

        champions[champion] = (
            champions.get(
                champion,
                0
            ) + 1
        )

    return champions


# -----------------------------
# MAIN
# -----------------------------

def main():

    df = pd.read_csv(
        "nba_2025_stats.csv"
    )

    team_stats = build_team_stats(df)

    team_stats = normalize_stats(
        team_stats
    )

    results = monte_carlo(
        team_stats,
        10000
    )

    print(
        "\nChampionship Probabilities\n"
    )

    for team, wins in sorted(
            results.items(),
            key=lambda x: x[1],
            reverse=True):

        probability = (
            wins / 10000
        ) * 100

        print(
            f"{team}: "
            f"{probability:.2f}%"
        )


if __name__ == "__main__":
    main()