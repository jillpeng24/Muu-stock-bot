import pandas as pd
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
CHIPS_FILE = DATA_DIR / "daily_chips_all.csv"

def scan():
    if not CHIPS_FILE.exists(): return
    df = pd.read_csv(CHIPS_FILE, dtype={'stock_id': str})
    df['date'] = pd.to_datetime(df['date'])
    results = []
    
    for sid, group in df.groupby('stock_id'):
        group = group.sort_values('date').tail(5)
        if len(group) < 3: continue
        
        last_3 = group.tail(3)
        tags = []
        if all(last_3['foreign'] > 0) and all(last_3['trust'] > 0):
            tags.append("A.外投同買3天")
        
        if tags:
            last_row = group.iloc[-1]
            results.append({
                "日期": last_row['date'].strftime('%Y%m%d'),
                "代號": sid, "名稱": last_row['name'], "分類": " / ".join(tags)
            })
            
    if results:
        res_df = pd.DataFrame(results)
        today_str = results[0]['日期']
        res_df.to_csv(DATA_DIR / f"scan_result_{today_str}.csv", index=False, encoding='utf-8-sig')
        print(f"✅ 籌碼篩選完成: {len(results)} 檔")

if __name__ == "__main__":
    scan()
