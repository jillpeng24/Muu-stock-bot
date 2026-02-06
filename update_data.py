import pandas as pd
import requests
import os
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CHIPS_FILE = DATA_DIR / "daily_chips_all.csv"

def fetch_twse_data(date_str):
    url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_str}&selectType=ALLBUT0999&response=json"
    try:
        resp = requests.get(url, timeout=20)
        data = resp.json()
        if data.get("stat") == "OK":
            df = pd.DataFrame(data["data"], columns=data["fields"])
            df['date'] = pd.to_datetime(date_str)
            return df
    except:
        return None

def main():
    today = datetime.now().strftime("%Y%m%d")
    print(f"🚀 開始抓取今日資料: {today}")
    new_df = fetch_twse_data(today)
    
    if new_df is not None:
        # 清理欄位
        new_df = new_df[['date', '證券代號', '證券名稱', '外資買賣超股數', '投信買賣超股數']]
        new_df.columns = ['date', 'stock_id', 'name', 'foreign', 'trust']
        
        if CHIPS_FILE.exists():
            old_df = pd.read_csv(CHIPS_FILE)
            combined_df = pd.concat([old_df, new_df]).drop_duplicates(subset=['date', 'stock_id'])
            # 保持最近 60 天資料
            combined_df = combined_df.sort_values('date').tail(50000)
            combined_df.to_csv(CHIPS_FILE, index=False)
        else:
            new_df.to_csv(CHIPS_FILE, index=False)
        print("✅ 資料更新成功")
    else:
        print("ℹ️ 今日無交易資料或抓取失敗")

if __name__ == "__main__":
    main()
