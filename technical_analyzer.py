# technical_analyzer.py (GitHub 雲端通用版)
import os
import pandas as pd
import yfinance as yf
from datetime import datetime
from tqdm import tqdm
import time
import glob

# ==========================================
# 設定：路徑設定 (對齊雲端環境)
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

def analyze_technical(df):
    """技術面打勾邏輯 (維持原邏輯)"""
    if len(df) < 60:
        return 0, ["資料不足(需60日)"]
    
    close = df['Close']
    vol = df['Volume']
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    
    score = 0
    checks = []
    
    # 1. 均線多頭排列
    if close.iloc[-1] > ma5.iloc[-1] > ma20.iloc[-1] > ma60.iloc[-1]:
        score += 1
        checks.append("✓ 均線多頭")
    
    # 2. 量價同步 (今日收紅且量增)
    if close.iloc[-1] > close.iloc[-2] and vol.iloc[-1] > vol.iloc[-2]:
        score += 1
        checks.append("✓ 量價同步")
        
    # ... (您可以根據需求在此增加更多打勾條件)
        
    return score, checks

def start_technical_analysis():
    # 1. 搜尋最新產出的基本面檢核結果 (接力 stock_checker.py)
    check_files = glob.glob(os.path.join(DATA_DIR, "comprehensive_check_*.csv"))
    if not check_files:
        print("❌ 找不到基本面檢核結果，中斷分析。")
        return

    # 讀取日期最新的那一支檔案
    report_path = sorted(check_files)[-1]
    print(f"📂 讀取待分析清單：{os.path.basename(report_path)}")
    
    df_passed = pd.read_csv(report_path)
    # 只針對「✅ 通過」的股票進行技術面掃描，節省雲端執行時間
    df_targets = df_passed[df_passed['狀態'].str.contains('通過')].copy()
    
    if df_targets.empty:
        print("ℹ️ 無通過基本面檢核之標的，無需執行技術分析。")
        return

    results = []
    for _, row in tqdm(df_targets.iterrows(), total=len(df_targets), desc="技術面掃描"):
        sid = str(row['代號'])
        df_hist = pd.DataFrame()
        
        # 嘗試台股兩種後綴 (.TW / .TWO)
        for suffix in [".TW", ".TWO"]:
            try:
                ticker = yf.Ticker(sid + suffix)
                df_hist = ticker.history(period="6mo") # 抓半年資料
                if not df_hist.empty:
                    break
            except:
                continue
        
        if not df_hist.empty:
            score, checks = analyze_technical(df_hist)
            
            res_row = row.to_dict()
            res_row.update({
                '技術面得分': f"{score}/7", # 配合您原有的格式
                '技術面檢核': " | ".join(checks) if checks else "未達標"
            })
            results.append(res_row)
        
        # ⚠️ 雲端執行建議間隔 1-2 秒，避免被封鎖
        time.sleep(1.5)

    if results:
        df_final = pd.DataFrame(results)
        # 依照得分排序
        df_final = df_final.sort_values(by="技術面得分", ascending=False)
        
        today_str = datetime.now().strftime("%Y%m%d")
        output_path = os.path.join(DATA_DIR, f"final_selection_{today_str}.csv")
        
        df_final.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"✅ 技術面分析完成！最終選股報表：{output_path}")

if __name__ == "__main__":
    start_technical_analysis()
