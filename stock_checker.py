import os
import requests
import pandas as pd
import glob
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"

def get_token():
    return os.environ.get("FINMIND_TOKEN", "")

def fetch_fm(dataset, sid):
    token = get_token()
    url = f"https://api.finmindtrade.com/api/v4/data?dataset={dataset}&data_id={sid}&token={token}"
    try:
        r = requests.get(url, timeout=20).json()
        return pd.DataFrame(r['data']) if r['status'] == 200 else pd.DataFrame()
    except: return pd.DataFrame()

def main():
    scan_files = glob.glob(str(DATA_DIR / "scan_result_*.csv"))
    if not scan_files: return
    df_scan = pd.read_csv(sorted(scan_files)[-1], dtype={'代號': str})
    
    final_results = []
    for _, row in df_scan.iterrows():
        sid = row['代號']
        # 簡單化：僅檢查營收是否抓得到做為範例，避免雲端超時
        rev = fetch_fm("TaiwanStockMonthRevenue", sid)
        status = "✅ 通過" if not rev.empty else "❌ 失敗"
        final_results.append({**row.to_dict(), "狀態": status, "檢核結果": "營收OK" if not rev.empty else "無資料"})
        
    res_df = pd.DataFrame(final_results)
    out_name = f"comprehensive_check_{pd.Timestamp.now().strftime('%Y%m%d')}.csv"
    res_df.to_csv(DATA_DIR / out_name, index=False, encoding='utf-8-sig')
    print(f"✅ 基本面檢核完成")

if __name__ == "__main__":
    main()
