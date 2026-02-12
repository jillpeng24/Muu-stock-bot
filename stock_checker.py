
# stock_checkerN.py
import os
import requests
import pandas as pd
import time
import glob
from datetime import datetime
from tqdm import tqdm

# ==========================================
# 設定 (完整保留您的路徑與 API 設定)
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config", ".env")
DATA_DIR = os.path.join(BASE_DIR, "data")
FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"

def get_token():
    # 優先讀取環境變數 (GitHub Actions Secrets)
    env_token = os.environ.get("FINMIND_TOKEN")
    if env_token:
        return env_token
    # 本機執行時從 config/.env 讀取
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("FINMIND_TOKEN"):
                    return line.split("=")[1].strip().strip('"').strip("'")
    return ""

TOKEN = get_token()

# ==========================================
# API 工具函式
# ==========================================
def fetch_fm(dataset, stock_id=None, start_date=None, end_date=None):
    if not TOKEN: 
        return pd.DataFrame()
    params = {"dataset": dataset, "token": TOKEN}
    if stock_id: params["data_id"] = stock_id
    if start_date: params["start_date"] = start_date
    if end_date: params["end_date"] = end_date
    try:
        resp = requests.get(FINMIND_API_URL, params=params, timeout=30)
        res = resp.json()
        if res.get("status") == 200 and res.get("msg") == "success":
            return pd.DataFrame(res.get("data", []))
    except Exception as e:
        print(f"      ⚠️ API 錯誤: {e}")
    return pd.DataFrame()

# ==========================================
# 核心檢核引擎 (YoY > 40% 或 原始條件全過 即通過)
# ==========================================
def run_comprehensive_check(stock_id, stock_name, chip_data=None):
    results = {"pass": True, "reasons": [], "warnings": []}
    yoy_val = -999.0  # 紀錄營收成長率
    original_conditions_met = True # 紀錄是否滿足原始三項條件

    # 1. 營收檢核
    try:
        df_rev = fetch_fm("TaiwanStockMonthRevenue", stock_id, "2020-01-01")
        if not df_rev.empty and len(df_rev) >= 12:
            df_rev['date'] = pd.to_datetime(df_rev['date'])
            df_rev = df_rev.sort_values('date')
            latest = df_rev.iloc[-1]
            prev_year = df_rev.iloc[-13] if len(df_rev) >= 13 else df_rev.iloc[-12]
            yoy = ((latest['revenue'] - prev_year['revenue']) / prev_year['revenue'] * 100)
            yoy_val = yoy
            
            if yoy <= 0:
                original_conditions_met = False
                results["reasons"].append(f"營收YoY為負({yoy:.1f}%)")
            else:
                results["reasons"].append(f"✓ 營收YoY成長{yoy:.1f}%")
            
            if len(df_rev) >= 6:
                current_q = df_rev['revenue'].iloc[-3:].sum()
                prev_q = df_rev['revenue'].iloc[-6:-3].sum()
                qoq = ((current_q - prev_q) / prev_q * 100)
                if qoq < 0:
                    results["warnings"].append(f"警示季增率QoQ為負({qoq:.1f}%)")
                else:
                    results["reasons"].append(f"季增率QoQ({qoq:.1f}%)")
            
            if latest['revenue'] >= df_rev['revenue'].max():
                results["reasons"].append("🔥 月營收創歷史新高")
    except Exception as e:
        results["warnings"].append(f"營收資料查詢失敗: {e}")
        original_conditions_met = False

    # 2. EPS 檢核
    try:
        df_fin = fetch_fm("TaiwanStockFinancialStatements", stock_id, "2019-01-01")
        if not df_fin.empty:
            df_eps = df_fin[df_fin['type'] == 'EPS'].copy()
            if not df_eps.empty:
                df_eps['date'] = pd.to_datetime(df_eps['date'])
                df_eps = df_eps.sort_values('date')
                if any(df_eps.tail(20)['value'] <= 0):
                    original_conditions_met = False
                    results["reasons"].append("❌ 5年內有EPS虧損")
                else:
                    results["reasons"].append("✓ 5年EPS均為正")
    except Exception as e:
        results["warnings"].append(f"財報資料查詢失敗: {e}")
        original_conditions_met = False

    # 3. 股利檢核
    try:
        df_div = fetch_fm("TaiwanStockDividend", stock_id, "2019-01-01")
        if not df_div.empty:
            df_div['date'] = pd.to_datetime(df_div['date'])
            if len(df_div['date'].dt.year.unique()) < 5:
                original_conditions_met = False
                results["reasons"].append("❌ 連續發股利不滿5年")
            else:
                results["reasons"].append("✓ 連續5年發股利")
    except Exception as e:
        results["warnings"].append(f"股利資料查詢失敗: {e}")
        original_conditions_met = False

    # --- 關鍵判定邏輯：(全過) 或 (YoY > 40%) ---
    if original_conditions_met or yoy_val > 40:
        results["pass"] = True
    else:
        results["pass"] = False

    # 4. 法人籌碼資訊 (維持原輸出內容)
    if chip_data is not None:
        # 自動識別欄位名稱
        inst_buy_ratio = chip_data.get('買超比率', chip_data.get('inst_buy_ratio', 0))
        if not pd.isna(inst_buy_ratio):
            results["reasons"].append(f"法人本日買超比{inst_buy_ratio:.2f}%")
    
    return results

# ==========================================
# 主執行邏輯
# ==========================================
def main():
    # 搜尋最新的 scan_result_*.csv
    scan_files = glob.glob(os.path.join(DATA_DIR, "scan_result_*.csv"))
    if not scan_files:
        print(f"❌ 在 {DATA_DIR} 找不到任何 scan_result_*.csv 檔案")
        return
    
    input_file = max(scan_files, key=os.path.getctime)
    print(f"讀取輸入檔案: {os.path.basename(input_file)}")

    df_candidates = pd.read_csv(input_file)
    if df_candidates.empty:
        print("⚠️ 候選清單為空。")
        return

    # --- 修正: 自動識別 CSV 欄位名稱 ---
    col_map = {}
    for col in df_candidates.columns:
        if col in ['代號', 'stock_id']: col_map['id'] = col
        if col in ['名稱', 'name']: col_map['name'] = col
    
    # 檢查必要欄位
    if 'id' not in col_map:
        col_map['id'] = df_candidates.columns[1] # 若沒找到，預設取第二欄(通常是代號)
        print(f"⚠️ 找不到 '代號' 欄位，自動使用 '{col_map['id']}'")
    if 'name' not in col_map:
        col_map['name'] = df_candidates.columns[2]

    # 決定輸出檔名
    today_str = datetime.now().strftime("%Y%m%d")
    output_file = os.path.join(DATA_DIR, f"comprehensive_check_{today_str}.csv")

    final_list = []
    for _, row in tqdm(df_candidates.iterrows(), total=len(df_candidates), desc="全面檢核進度"):
        sid = str(row[col_map['id']])
        sname = str(row[col_map['name']])
        
        check = run_comprehensive_check(sid, sname, chip_data=row)
        
        # 排序參考值 (優先用 買超比率)
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
        time.sleep(0.5)

    df_result = pd.DataFrame(final_list)
    # 排序：通過的排前面，再按買超比率排
    df_result = df_result.sort_values(by=["_pass_order", "_inst_val"], ascending=[False, False])
    
    output_cols = ["代號", "名稱", "分類", "狀態", "檢核結果", "警示"]
    df_result[output_cols].to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n✅ 檢核完成！輸出至：{output_file}")

if __name__ == "__main__":
    main()
