# stock_checker.py (GitHub 雲端/安全強化版)
import os
import requests
import pandas as pd
import time
import glob
from datetime import datetime
from tqdm import tqdm

# ==========================================
# 設定：路徑與 API 設定 (對齊雲端環境)
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"

def get_token():
    """☁️ 雲端版專用：直接從環境變數抓取 GitHub Secrets"""
    # 這是為了保護您的 FinMind Token 不會出現在程式碼中
    return os.environ.get("FINMIND_TOKEN", "")

TOKEN = get_token()

# ==========================================
# 工具函式
# ==========================================
def fetch_fm(dataset, stock_id=None, start_date=None, end_date=None):
    """呼叫 FinMind API"""
    if not TOKEN:
        print("⚠️ 錯誤：找不到 FINMIND_TOKEN，請於 GitHub Secrets 設定")
        return pd.DataFrame()
        
    params = {"dataset": dataset, "token": TOKEN}
    if stock_id: params["data_id"] = stock_id
    if start_date: params["start_date"] = start_date
    if end_date: params["end_date"] = end_date
    
    try:
        resp = requests.get(FINMIND_API_URL, params=params, timeout=30)
        res = resp.json()
        if res.get("status") == 200:
            return pd.DataFrame(res.get("data", []))
    except Exception as e:
        print(f"      ⚠️ API 請求錯誤: {e}")
    return pd.DataFrame()

# ==========================================
# 核心檢核邏輯 (維持原邏輯，優化穩定性)
# ==========================================
def run_comprehensive_check(stock_id, stock_name, chip_data=None):
    results = {"pass": True, "reasons": [], "warnings": []}
    yoy_val = -999.0
    original_conditions_met = True

    # 1. 營收 YoY 檢核
    try:
        df_rev = fetch_fm("TaiwanStockMonthRevenue", stock_id, "2020-01-01")
        if not df_rev.empty and len(df_rev) >= 12:
            df_rev = df_rev.sort_values('date')
            latest = df_rev.iloc[-1]
            prev_year = df_rev.iloc[-13] if len(df_rev) >= 13 else df_rev.iloc[-12]
            yoy = ((latest['revenue'] - prev_year['revenue']) / prev_year['revenue'] * 100)
            yoy_val = yoy
            
            if yoy <= 0:
                original_conditions_met = False
                results["reasons"].append(f"營收YoY負({yoy:.1f}%)")
            else:
                results["reasons"].append(f"✓ 營收YoY成長({yoy:.1f}%)")
    except:
        original_conditions_met = False

    # 2. EPS 檢核
    try:
        df_fin = fetch_fm("TaiwanStockFinancialStatements", stock_id, "2019-01-01")
        if not df_fin.empty:
            df_eps = df_fin[df_fin['type'] == 'EPS']
            # 檢查最近 20 季是否有虧損
            if any(df_eps.tail(20)['value'] <= 0):
                original_conditions_met = False
                results["reasons"].append("5年內有虧損")
            else:
                results["reasons"].append("✓ 5年EPS正")
    except:
        original_conditions_met = False

    # 綜合判定條件：原條件全過 OR 營收噴發(YoY > 40)
    results["pass"] = original_conditions_met or yoy_val > 40
    
    if chip_data is not None:
        results["reasons"].append(f"法人買超比{chip_data.get('買超比率', 0):.2f}%")
        
    return results

# ==========================================
# 主程式執行
# ==========================================
def main():
    # 搜尋最新產出的籌碼篩選名單
    scan_files = glob.glob(os.path.join(DATA_DIR, "scan_result_*.csv"))
    if not scan_files:
        print("❌ 找不到籌碼篩選結果，中斷執行。")
        return
    
    # 讀取日期最新的那一支檔案
    input_file = sorted(scan_files)[-1]
    print(f"📂 讀取籌碼清單：{os.path.basename(input_file)}")
    
    df_candidates = pd.read_csv(input_file)
    final_list = []

    for _, row in tqdm(df_candidates.iterrows(), total=len(df_candidates), desc="基本面檢核"):
        sid = str(row['代號'])
        check = run_comprehensive_check(sid, row['名稱'], chip_data=row)
        
        final_list.append({
            "代號": sid,
            "名稱": row['名稱'],
            "分類": row.get('分類', '-'),
            "狀態": "✅ 通過" if check["pass"] else "❌ 未通過",
            "檢核結果": " | ".join(check["reasons"]),
            "警示": " | ".join(check["warnings"]) if check["warnings"] else "-",
            "_pass": 1 if check["pass"] else 0,
            "_inst": row.get('買超比率', 0)
        })
        time.sleep(0.5) # 避開 API 頻繁請求限制

    if final_list:
        df_result = pd.DataFrame(final_list)
        # 排序：通過標的排前面，買超比高的排前面
        df_result = df_result.sort_values(by=["_pass", "_inst"], ascending=[False, False])
        
        output_file = os.path.join(DATA_DIR, f"comprehensive_check_{datetime.now().strftime('%Y%m%d')}.csv")
        df_result.drop(columns=["_pass", "_inst"]).to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"✅ 基本面檢核存檔：{os.path.basename(output_file)}")

if __name__ == "__main__":
    main()
