# stock_checker_pro.py
import os
import pandas as pd
import numpy as np
import glob
from datetime import datetime
from tqdm import tqdm

# ==========================================
# 1. 設定 (動態路徑，完美適應 Mac 與 GitHub 雲端)
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
HISTORY_DIR = os.path.join(DATA_DIR, "history")

REV_FILE = os.path.join(HISTORY_DIR, "revenue_history.csv")
EPS_FILE = os.path.join(HISTORY_DIR, "eps_history.csv")
DIV_FILE = os.path.join(HISTORY_DIR, "dividend_history.csv")

# ==========================================
# 2. 預載本地歷史資料庫
# ==========================================
def safe_load(path):
    """安全讀取 CSV，如果檔案不存在則回傳空 DataFrame"""
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
# 3. 核心檢核引擎 (⚠️ 100% 復刻原始邏輯，僅微調負營收文字)
# ==========================================
def run_comprehensive_check(stock_id, stock_name, chip_data=None):
    results = {"pass": True, "reasons": [], "warnings": []}
    yoy_val = -999.0  
    original_conditions_met = True 

    # 1. 營收檢核
    try:
        df_rev = df_rev_all[df_rev_all['stock_id'] == stock_id].copy()
        if not df_rev.empty and len(df_rev) >= 12:
            latest = df_rev.iloc[-1]
            prev_year = df_rev.iloc[-13] if len(df_rev) >= 13 else df_rev.iloc[-12]
            yoy = ((latest['revenue'] - prev_year['revenue']) / prev_year['revenue'] * 100)
            yoy_val = yoy
            
            if yoy <= 0:
                original_conditions_met = False
                # 🚀 這是唯一允許的修改：改回您喜歡的簡潔格式
                results["reasons"].append(f"營收YoY {yoy:.1f}%")
            else:
                results["reasons"].append(f"✓ 營收YoY成長{yoy:.1f}%")
            
            # 季增率 QoQ 邏輯 (近三月 vs 前三月)
            if len(df_rev) >= 6:
                current_q = df_rev['revenue'].iloc[-3:].sum()
                prev_q = df_rev['revenue'].iloc[-6:-3].sum()
                qoq = ((current_q - prev_q) / prev_q * 100) if prev_q > 0 else 0
                if qoq < 0:
                    results["warnings"].append(f"警示季增率QoQ為負({qoq:.1f}%)")
                else:
                    results["reasons"].append(f"季增率QoQ({qoq:.1f}%)")
            
            if latest['revenue'] >= df_rev['revenue'].max():
                results["reasons"].append("🔥 月營收創歷史新高")
    except Exception:
        original_conditions_met = False

    # 2. EPS 檢核
    try:
        df_eps = df_eps_all[df_eps_all['stock_id'] == stock_id]
        if not df_eps.empty:
            if any(df_eps.tail(20)['eps'] <= 0):
                original_conditions_met = False
                results["reasons"].append("❌ 5年內有EPS虧損")
            else:
                results["reasons"].append("✓ 5年EPS均為正")
        else:
            original_conditions_met = False
    except Exception:
        original_conditions_met = False

    # 3. 股利檢核
    try:
        df_div = df_div_all[df_div_all['stock_id'] == stock_id]
        if not df_div.empty:
            if len(df_div['date'].dt.year.unique()) < 5:
                original_conditions_met = False
                results["reasons"].append("❌ 連續發股利不滿5年")
            else:
                results["reasons"].append("✓ 連續5年發股利")
        else:
            original_conditions_met = False
    except Exception:
        original_conditions_met = False

    # --- 關鍵判定邏輯：(全過) 或 (YoY > 40%) ---
    if original_conditions_met or yoy_val > 40:
        results["pass"] = True
    else:
        results["pass"] = False

    # 4. 法人籌碼資訊 (維持原文字內容)
    if chip_data is not None:
        inst_buy_ratio = chip_data.get('買超比率', chip_data.get('inst_buy_ratio', 0))
        if not pd.isna(inst_buy_ratio):
            results["reasons"].append(f"法人本日買超比{inst_buy_ratio:.2f}%")
    
    return results

# ==========================================
# 4. 主執行邏輯 (100% 復刻您原本的流程)
# ==========================================
def main():
    scan_files = glob.glob(os.path.join(DATA_DIR, "scan_result_*.csv"))
    if not scan_files: return
    
    input_file = max(scan_files, key=os.path.getctime)
    print(f"讀取輸入檔案: {os.path.basename(input_file)}")

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
    for _, row in tqdm(df_candidates.iterrows(), total=len(df_candidates), desc="全面檢核進度"):
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
    
    # 輸出嚴格限制為這 6 個欄位
    output_cols = ["代號", "名稱", "分類", "狀態", "檢核結果", "警示"]
    df_result[output_cols].to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n✅ 檢核完成！檔案已存至：{output_file}")

if __name__ == "__main__":
    main()