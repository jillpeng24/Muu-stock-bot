# technical_analyzer.py
import os
import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime, timedelta
from tqdm import tqdm
import time

# ==========================================
# 設定
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

def get_latest_fundamental_report():
    """尋找最新一份基本面通過的名單"""
    files = [f for f in os.listdir(DATA_DIR) if f.startswith("comprehensive_check_") and f.endswith(".csv")]
    if not files:
        return None
    return os.path.join(DATA_DIR, sorted(files)[-1])

# ==========================================
# 技術指標計算邏輯
# ==========================================
def analyze_technical(df):
    """計算七大指標並回傳勾勾列表"""
    if len(df) < 60:
        return 0, []

    check_list = []
    score = 0
    
    # 準備基礎數據
    close = df['Close']
    high = df['High']
    low = df['Low']
    open_p = df['Open']
    vol = df['Volume']
    
    # 1. 均線計算
    ma5 = close.rolling(window=5).mean()
    ma20 = close.rolling(window=20).mean()
    ma60 = close.rolling(window=60).mean()
    
    # 2. KD 計算 (9, 3, 3)
    low_9 = low.rolling(window=9).min()
    high_9 = high.rolling(window=9).max()
    rsv = (close - low_9) / (high_9 - low_9) * 100
    k = rsv.ewm(com=2).mean()
    d = k.ewm(com=2).mean()
    
    # 3. MACD 計算 (12, 26, 9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    macd_line = dif.ewm(span=9, adjust=False).mean()
    
    # 4. 布林通道 (20, 2)
    std20 = close.rolling(window=20).std()
    upper_bb = ma20 + (std20 * 2)
    lower_bb = ma20 - (std20 * 2)
    bandwidth = (upper_bb - lower_bb) / (ma20 + 0.001) * 100  # BBW% 與 app.py 統一

    # --- 開始打勾檢核 (取最後一天數據) ---
    curr_c = close.iloc[-1]
    curr_v = vol.iloc[-1]
    prev_v = vol.iloc[-2]
    
    # 指標 1: 均線多頭排列
    if curr_c > ma5.iloc[-1] > ma20.iloc[-1] > ma60.iloc[-1] and ma20.iloc[-1] > ma20.iloc[-2]:
        check_list.append("✓ 均線多頭排列")
        score += 1

    # 指標 2: 帶量長紅突破
    avg_v20 = vol.iloc[-21:-1].mean()
    day_ret = (curr_c - close.iloc[-2]) / close.iloc[-2] * 100
    if day_ret > 3 and curr_v > avg_v20 * 2:
        check_list.append("✓ 帶量長紅突破")
        score += 1

    # 指標 3: MACD 零軸上金叉
    if dif.iloc[-1] > macd_line.iloc[-1] and dif.iloc[-1] > 0:
        check_list.append("✓ MACD零軸上金叉")
        score += 1

    # 指標 4: KD 起漲區金叉
    if k.iloc[-1] > d.iloc[-1] and 20 < k.iloc[-1] < 55:
        check_list.append("✓ KD起漲區金叉")
        score += 1

    # 指標 5: 布林帶量開口
    if curr_c > upper_bb.iloc[-1] and bandwidth.iloc[-1] > bandwidth.iloc[-2]:
        check_list.append("✓ 布林帶量開口")
        score += 1

    # 指標 6: 突破波段頸線 (20日高)
    if curr_c >= high.iloc[-21:-1].max():
        label = "✓ 突破波段頸線"
        if curr_c >= high.iloc[-61:-1].max():
            label = "🔥 突破季頸線"
        check_list.append(label)
        score += 1

    # 指標 7: 量價同步強勢
    entity = abs(curr_c - open_p.iloc[-1])
    upper_shadow = high.iloc[-1] - max(curr_c, open_p.iloc[-1])
    if curr_v > prev_v and day_ret > 0 and upper_shadow < entity * 0.5:
        check_list.append("✓ 量價同步強勢")
        score += 1

    return score, check_list

# ==========================================
# 主程式執行
# ==========================================
def start_technical_analysis():
    print("=== 📈 第二階段：技術面共振檢核系統 ===")
    
    report_path = get_latest_fundamental_report()
    if not report_path:
        print("❌ 找不到基本面檢核報告，請先執行第一階段程式。")
        return
    
    print(f"📂 讀取基本面通過名單: {os.path.basename(report_path)}")
    df_fund = pd.read_csv(report_path)
    
    # 僅針對基本面「✅ 通過」的標的進行分析
    df_passed = df_fund[df_fund['狀態'] == '✅ 通過'].copy()
    if df_passed.empty:
        print("⚠️ 目前沒有基本面通過的標的。")
        return

    print(f"🚀 開始分析 {len(df_passed)} 檔標的的技術面...\n")
    
    results = []
    for _, row in tqdm(df_passed.iterrows(), total=len(df_passed), desc="技術面掃描"):
        stock_id = str(row['代號'])
        name = row['名稱']
        
        try:
            # 下載 Yahoo Finance 資料 (優先嘗試 TW, 再嘗試 TWO)
            ticker = yf.Ticker(f"{stock_id}.TW")
            df_hist = ticker.history(period="6mo")
            if df_hist.empty:
                ticker = yf.Ticker(f"{stock_id}.TWO")
                df_hist = ticker.history(period="6mo")
            
            if not df_hist.empty:
                score, checks = analyze_technical(df_hist)
                
                # 合併原有資料並加入技術面結果
                res_row = row.to_dict()
                res_row['技術面得分'] = f"{score}/7"
                res_row['技術面檢核'] = " | ".join(checks) if checks else "無明顯訊號"
                res_row['_score_val'] = score # 排序用
                results.append(res_row)
            
            time.sleep(0.5) # 避開頻繁請求
        except Exception as e:
            tqdm.write(f"⚠️ {stock_id} 分析失敗: {e}")

    if not results:
        print("❌ 未能成功分析任何標的。")
        return

    # 建立 DataFrame 並排序 (得分高 -> 法人買超比高)
    df_final = pd.DataFrame(results)
    # 提取法人買超比中的數值用於排序 (假設格式為 "[籌碼] 法人買超比 1.28%")
    df_final['_inst_val'] = df_final['檢核結果'].str.extract(r'法人買超比 ([\-\d\.]+)%').astype(float)
    
    df_final = df_final.sort_values(by=['_score_val', '_inst_val'], ascending=[False, False])
    
    # 整理輸出欄位
    output_cols = ["代號", "名稱", "分類", "技術面得分", "技術面檢核", "檢核結果", "警示"]
    df_final_output = df_final[output_cols]
    
    print("\n" + "="*100)
    print(df_final_output.to_string(index=False))
    
    # 儲存結果
    out_path = os.path.join(DATA_DIR, f"final_selection_{datetime.now().strftime('%Y%m%d')}.csv")
    df_final_output.to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f"\n💾 最終選股名單已儲存: {os.path.basename(out_path)}")

if __name__ == "__main__":
    start_technical_analysis()