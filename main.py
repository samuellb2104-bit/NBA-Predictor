from nba_api.stats.endpoints import leaguedashplayerstats
import time
def main():
    print("Fetching NBA 2025-26 player stats")
    time.sleep(1)
    data = leaguedashplayerstats.LeagueDashPlayerStats(season="2025-26")
    df = data.get_data_frames()[0]
    df.to_csv("nba_2025_stats.csv", index=False)
    print("Data saved")
    print(df.columns)






if __name__ == '__main__':
    main();