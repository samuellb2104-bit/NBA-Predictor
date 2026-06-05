import pandas as pd
from matplotlib import pyplot as plt


def main():
    df = pd.read_csv("nba_2025_stats.csv")

    playoffteams = ["DET", "NYK", "BOS", "CLE", "TOR", "ATL", "PHI", "ORL",
                     "OKC", "SAS", "DEN", "LAL", "HOU", "MIN", "POR", "PHX" ]
    for head, teamStats in df.iterrows():
        if teamStats["TEAM_ABBREVIATION"] in playoffteams:
            print("Name: ", teamStats["PLAYER_NAME"], "- Age: ", teamStats["AGE"], "- FGM: ", teamStats["FGM"], "- FGA:",
                  teamStats["FGA"], " - FG%: ", teamStats["FG_PCT"], " NBA TEAM: ", teamStats["TEAM_ABBREVIATION"])
    print(averageAge(df, "LAL"))
    teams_fg = fieldGoalPerecentage(df, playoffteams)
    for index, values in teams_fg.items():
        print(index, ": ", values)
    plot_fg(teams_fg, "NBA TEAM FIELD GOAL PROCENTIGE", "%")


def averageAge(df, team):
    team_data = df[df["TEAM_ABBREVIATION"] == team]
    return team_data["AGE"].mean() if not team_data.empty else None


def fieldGoalPerecentage(df, playoffteams):
    teamFieldGoals = {}
    procentFieldGoals = {}
    for index, teamStats in df.iterrows():
        if teamStats["TEAM_ABBREVIATION"] in playoffteams:
            if teamStats["TEAM_ABBREVIATION"] not in teamFieldGoals:
                teamFieldGoals[teamStats["TEAM_ABBREVIATION"]] = {"FGM": 0, "FGA": 0}
            teamFieldGoals[teamStats["TEAM_ABBREVIATION"]]["FGM"] += teamStats["FGM"]
            teamFieldGoals[teamStats["TEAM_ABBREVIATION"]]["FGA"] += teamStats["FGA"]
    for team, stats in teamFieldGoals.items():
        if stats["FGA"] != 0:
            fg_pct = stats["FGM"] / stats["FGA"]
            procentFieldGoals[team] = fg_pct
        else:
            print("ERROR DEVIDED BY 0")
    return procentFieldGoals

def plot_fg(procentFieldGoals, title, label):
    # Sort teams by FG%
    sorted_teams = sorted(procentFieldGoals.items(), key=lambda x: x[1], reverse=True)
    teams, fg_pct = zip(*sorted_teams)
    # Plotting the field goal percentage
    plt.figure(figsize=(10, 6))
    plt.barh(teams, fg_pct, color='skyblue')
    plt.xlabel(label)
    plt.title(title)
    plt.xlim(0, 1)  # FG% is between 0 and 1
    plt.gca().invert_yaxis()  # Highest FG% will appear at the top
    plt.show()

if __name__ == '__main__':
    main()