# stock_checker_cloudpro.py
import os
import requests
import pandas as pd
import numpy as np
import glob
from datetime import datetime, timedelta
from tqdm import tqdm

# ==========================================
# 1. 設定 (動態路徑，完美適應 Mac 與 GitHub 雲端)
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
HISTORY_DIR = os.path.join(DATA_DIR, "history")
CONFIG_PATH = os.path.join(BASE_DIR, "config", ".env")

REV_FILE = os.path.join(HISTORY_DIR, "revenue_history.csv")
EPS_FILE = os.path.join(HISTORY_DIR, "eps_history.csv")
DIV_FILE = os.path.join(HISTORY_DIR, "dividend_history.csv")

# ==========================================
# 1.5 讀取 API Token (為了抓即時融資資料)
# ==========================================
def get_token():
    # 1. 優先讀取雲端環境變數
    env_token = os.environ.get("FINMIND_TOKEN")
    if env_token: return env_token
    
    # 2. 本機執行時從 .env 讀取
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("FINMIND_TOKEN"):
                    return line.split("=")[1].strip().strip('"').strip("'")
    return ""

TOKEN = get_token()

# ==========================================
# 2. 預載本地歷史資料庫 (零 API 消耗)
# ==========================================
def safe_load(path):
    if os.path.exists(path):
        df = pd.read_csv(path, dtype={'stock_id': str})
        df['date'] = pd.to_datetime(df['date'])
        return df.sort_values(['stock_id', 'date'])
    return pd.DataFrame()

print("📂 正在從雲端本地歷史庫預載數據 (零 API 消耗)...")
df_rev_all = safe_load(REV_FILE)
df_eps_all = safe_load(EPS_FILE)
df_div_all = safe_load(DIV_FILE)

# ==========================================
# 2.5 【新增】即時抓取融資使用率函式
# ==========================================
def get_margin_rate(stock_id):
    if not TOKEN: 
        return None
    # 往前推10天確保抓到最新交易日
    start_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    params = {
        "dataset": "TaiwanStockMarginPurchaseShortSale",
        "data_id": str(stock_id),
        "start_date": start_date,
        "token": TOKEN
    }
    try:
        url = "https://api.finmindtrade.com/api/v4/data"
        resp = requests.get(url, params=params, timeout=10)
        res = resp.json()
        if res.get("status") == 200 and res.get("data"):
            df = pd.DataFrame(res["data"])
            if not df.empty:
                latest = df.iloc[-1]
                balance = latest.get("MarginPurchaseTodayBalance", 0)
                limit = latest.get("MarginPurchaseLimit", 0)
                if limit > 0:
                    return (balance / limit) * 100
    except Exception:
        pass
    return None

# ==========================================
# 3. 核心檢核引擎
# ==========================================
def run_comprehensive_check(stock_id, stock_name, chip_data=None):
    results = {"pass": True, "reasons": [], "warnings": []}
    yoy_val = -999.0  
    original_conditions_met = True 

    # --- (此處省略中間重複的營收、EPS、股利檢核邏輯，請保持原樣) ---
    # ... 原本的 1.營收, 2.EPS, 3.股利 邏輯請保留 ...
    # [假設此處程式碼與您提供的原檔一致]
    
    # --- 關鍵判定邏輯 (YoY > 40 或 全過) ---
    # (此處需保留您原有的判定邏輯代碼)

    # 4. 法人籌碼資訊 (維持原內容)
    if chip_data is not None:
        inst_buy_ratio = chip_data.get('買超比率', chip_data.get('inst_buy_ratio', 0))
        if not pd.isna(inst_buy_ratio):
            results["reasons"].append(f"法人本日買超比{inst_buy_ratio:.2f}%")
            
    # 5. 【新增】融資使用率即時檢核
    margin_rate = get_margin_rate(stock_id)
    if margin_rate is not None:
        results["reasons"].append(f"融資率{margin_rate:.1f}%")
        if margin_rate > 20:
            results["warnings"].append(f"⚠️ 融資率大於20% ({margin_rate:.1f}%)")
    
    return results

# ==========================================
# 4. 主執行邏輯
# ==========================================
def main():
    scan_files = glob.glob(os.path.join(DATA_DIR, "scan_result_*.csv"))
    if not scan_files: return
    
    input_file = max(scan_files, key=os.path.getctime)
    print(f"🎯 讀取最新候選檔案: {os.path.basename(input_file)}")

    df_candidates = pd.read_csv(input_file)
    if df_candidates.empty: return

    col_map = {}
    for col in df_candidates.columns:
        if col in ['代號', 'stock_id']: col_map['id'] = col
        if col in ['名稱', 'name']: col_map['name'] = col
    if 'id' not in col_map: col_map['id'] = df_candidates.columns[1]
    if 'name' not in col_map: col_map['name'] = df_candidates.columns[2]

    today_str = datetime.now().strftime("%Y%m%d")
    output_file = os.path.join(DATA_DIR, f"comprehensive_check_{today_str}.csv")

    final_list = []
    # 修改 tqdm 文字提醒包含融資查詢
    for _, row in tqdm(df_candidates.iterrows(), total=len(df_candidates), desc="🚀 全面檢核(含融資)"):
        sid = str(row[col_map['id']])
        sname = str(row[col_map['name']])
        
        check = run_comprehensive_check(sid, sname, chip_data=row)
        
        inst_val = row.get('買超比率', row.get('inst_ratio_20d', 0))
        
        final_list.append({
            "代號": sid,
            "名稱": sname,
            "分類": row.get('分類', '-'),
            "狀態": "✅ 通過" if check["pass"] else "❌ 未通過",
            "檢核結果": " | ".join(check["reasons"]),
            "警示": " | ".join(check["warnings"]) if check["warnings"] else "-",
            "_pass_order": 1 if check["pass"] else 0,
            "_inst_val": inst_val
        })

    df_result = pd.DataFrame(final_list)
    df_result = df_result.sort_values(by=["_pass_order", "_inst_val"], ascending=[False, False])
    
    output_cols = ["代號", "名稱", "分類", "狀態", "檢核結果", "警示"]
    df_result[output_cols].to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n✅ 檢核完成！結果已存至：{output_file}")

if __name__ == "__main__":
    main()
