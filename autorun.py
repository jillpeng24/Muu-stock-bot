import os
import pandas as pd
import yfinance as yf
import numpy as np
import glob
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"

def main():
    files = glob.glob(str(DATA_DIR / "comprehensive_check_*.csv"))
    if not files: return
    df = pd.read_csv(sorted(files)[-1], dtype={'代號': str})
    df_passed = df[df['狀態'] == '✅ 通過'].copy()
    
    final_list = []
    for _, row in df_passed.iterrows():
        sid = row['代號']
        try:
            # 支援台股兩市場
            stock = yf.Ticker(f"{sid}.TW")
            h = stock.history(period="3mo")
            if h.empty: h = yf.Ticker(f"{sid}.TWO").history(period="3mo")
            
            if not h.empty:
                score = 0
                if h['Close'].iloc[-1] > h['Close'].rolling(20).mean().iloc[-1]: score += 1
                row['技術面得分'] = f"{score}/7"
                row['技術面檢核'] = "✓ 站上月線" if score > 0 else "未達標"
                final_list.append(row.to_dict())
        except: continue
        
    if final_list:
        res_df = pd.DataFrame(final_list)
        res_df.to_csv(DATA_DIR / f"final_selection_{pd.Timestamp.now().strftime('%Y%m%d')}.csv", index=False)
        print("✅ 技術分析完成")

if __name__ == "__main__":
    main()
