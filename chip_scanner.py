# chip_scanner.py (GitHub 雲端通用版)
import pandas as pd
import os

# ==========================================
# 設定：路徑與檔案名稱 (對齊雲端環境)
# ==========================================
# 取得目前程式所在的資料夾位置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 設定資料存放資料夾為 data
DATA_DIR = os.path.join(BASE_DIR, "data")
# 指向前一步驟產出的籌碼總表
CHIPS_FILE = os.path.join(DATA_DIR, "daily_chips_all.csv")

def scan_stocks():
    print(f"🔍 正在讀取資料檔：{CHIPS_FILE}")
    
    # 1. 檢查原始資料檔是否存在
    if not os.path.exists(CHIPS_FILE):
        print(f"❌ 錯誤：找不到資料檔 {CHIPS_FILE}，請確認 update_data.py 是否執行成功。")
        return

    try:
        # 2. 讀取資料 (強制將 stock_id 讀為字串，避免遺失開頭的 0)
        df = pd.read_csv(CHIPS_FILE, dtype={'stock_id': str})
        
        # 3. 轉換日期並確保排序正確
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values(['stock_id', 'date'], ascending=[True, True])

        results = []

        # 4. 籌碼篩選邏輯 (維持原條件)
        for stock_id, group in df.groupby('stock_id'):
            # 檢查資料長度是否足以判斷連買
            if len(group) < 3:
                continue
            
            # 取得不同區間的切片
            last_5 = group.tail(5)
            last_4 = group.tail(4)
            last_3 = group.tail(3)
            
            latest_row = group.iloc[-1]
            stock_name = latest_row['name']
            last_date_str = latest_row['date'].strftime('%Y-%m-%d')
            
            tags = []
            sort_priority = 99

            # 條件 A: 外資與投信同買 3 天
            if len(last_3) == 3:
                if all(last_3['foreign'] > 0) and all(last_3['trust'] > 0):
                    tags.append("A.外投同買3天")
                    sort_priority = min(sort_priority, 1)

            # 條件 B: 投信連買 4 天
            if len(last_4) == 4:
                if all(last_4['trust'] > 0):
                    tags.append("B.投信連買4天")
                    sort_priority = min(sort_priority, 2)

            # 條件 C: 外資連買 5 天
            if len(last_5) == 5:
                if all(last_5['foreign'] > 0):
                    tags.append("C.外資連買5天")
                    sort_priority = min(sort_priority, 3)

            # 若符合任一條件，加入結果清單
            if tags:
                results.append({
                    "日期": last_date_str,
                    "代號": stock_id,
                    "名稱": stock_name,
                    "分類": " / ".join(tags),
                    "今日投信": latest_row['trust'],
                    "今日外資": latest_row['foreign'],
                    "買超比率": latest_row.get('inst_buy_ratio', 0),
                    "priority": sort_priority
                })

        # 5. 排序並輸出掃描結果
        if results:
            report_df = pd.DataFrame(results)
            # 優先級高的排前面，同優先級則按投信買超量排序
            report_df = report_df.sort_values(by=['priority', '今日投信'], ascending=[True, False])
            
            # 移除排序用的隱藏欄位
            final_report = report_df.drop(columns=['priority'])
            
            # 以最新日期作為檔名，方便後續 stock_checker.py 識別
            final_date = final_report.iloc[0]['日期'].replace("-", "")
            output_path = os.path.join(DATA_DIR, f"scan_result_{final_date}.csv")
            
            # 匯出 CSV (使用 utf-8-sig 確保 Excel 開啟不亂碼)
            final_report.to_csv(output_path, index=False, encoding='utf-8-sig')
            print(f"✅ 籌碼篩選完成！產出檔案：{output_path}")
        else:
            print("💡 掃描完畢，今日無符合條件之標的。")

    except Exception as e:
        print(f"❌ 掃描過程發生錯誤：{e}")

if __name__ == "__main__":
    scan_stocks()
