import pandas as pd
import requests
import os
from datetime import datetime, timedelta
from pathlib import Path
import time

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CHIPS_FILE = DATA_DIR / "daily_chips_all.csv"

def fetch_twse_data(date_str):
    """抓取台灣證券交易所三大法人買賣超資料"""
    url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_str}&selectType=ALLBUT0999&response=json"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    try:
        print(f"  正在抓取 {date_str} 的資料...")
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        if data.get("stat") == "OK" and data.get("data"):
            df = pd.DataFrame(data["data"], columns=data["fields"])
            df['date'] = pd.to_datetime(date_str, format='%Y%m%d')
            print(f"  ✓ 成功抓取 {len(df)} 筆資料")
            return df
        else:
            print(f"  ⚠️ {date_str} 無交易資料 (可能是假日)")
            return None
            
    except requests.Timeout:
        print(f"  ❌ 連線逾時")
        return None
    except requests.RequestException as e:
        print(f"  ❌ 網路錯誤: {e}")
        return None
    except Exception as e:
        print(f"  ❌ 未知錯誤: {e}")
        return None

def main():
    print(f"🚀 開始更新籌碼資料")
    
    # 嘗試抓取今日資料
    today = datetime.now()
    new_data = []
    
    # 如果今天抓不到，往前嘗試最近 3 天（處理週末的情況）
    for days_ago in range(0, 4):
        target_date = today - timedelta(days=days_ago)
        date_str = target_date.strftime("%Y%m%d")
        
        df = fetch_twse_data(date_str)
        if df is not None:
            new_data.append(df)
            break
        
        if days_ago < 3:
            time.sleep(2)  # 避免請求過快
    
    if not new_data:
        print("❌ 無法抓取任何新資料（可能是連續假期）")
        return False
    
    # 合併新資料
    new_df = pd.concat(new_data, ignore_index=True)
    
    # 清理欄位名稱並選取需要的欄位
    if '證券代號' in new_df.columns:
        new_df = new_df[['date', '證券代號', '證券名稱', '外資買賣超股數', '投信買賣超股數']]
        new_df.columns = ['date', 'stock_id', 'name', 'foreign', 'trust']
        
        # 轉換數值欄位（移除逗號）
        new_df['foreign'] = pd.to_numeric(new_df['foreign'].astype(str).str.replace(',', ''), errors='coerce')
        new_df['trust'] = pd.to_numeric(new_df['trust'].astype(str).str.replace(',', ''), errors='coerce')
        new_df['stock_id'] = new_df['stock_id'].astype(str)
    else:
        print("❌ 資料格式不符")
        return False
    
    # 合併歷史資料
    if CHIPS_FILE.exists():
        print(f"📂 載入歷史資料: {CHIPS_FILE}")
        old_df = pd.read_csv(CHIPS_FILE, dtype={'stock_id': str})
        old_df['date'] = pd.to_datetime(old_df['date'])
        
        combined_df = pd.concat([old_df, new_df], ignore_index=True)
        # 去除重複（同一天同一股票）
        combined_df = combined_df.drop_duplicates(subset=['date', 'stock_id'], keep='last')
        combined_df = combined_df.sort_values(['stock_id', 'date'])
        
        # 保留最近 60 天的資料
        cutoff_date = datetime.now() - timedelta(days=60)
        combined_df = combined_df[combined_df['date'] >= cutoff_date]
        
        print(f"  合併後共 {len(combined_df)} 筆資料")
    else:
        print("📝 建立新的資料檔")
        combined_df = new_df
    
    # 儲存
    combined_df.to_csv(CHIPS_FILE, index=False)
    print(f"✅ 資料已儲存至 {CHIPS_FILE}")
    print(f"   最新日期: {combined_df['date'].max().strftime('%Y-%m-%d')}")
    print(f"   股票數量: {combined_df['stock_id'].nunique()}")
    
    return True

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
