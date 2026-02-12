import pandas as pd
import os

# ==========================================
# 設定：路徑與檔案名稱
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CHIPS_FILE = os.path.join(DATA_DIR, "daily_chips_all.csv")

def scan_stocks():
    print(f"🔍 正在檢查資料夾：{DATA_DIR}")
    
    # 1. 檢查原始資料檔是否存在
    if not os.path.exists(CHIPS_FILE):
        print(f"❌ 找不到資料檔：{CHIPS_FILE}")
        print("💡 提醒：請先執行 update_data.py 抓取最新籌碼資料。")
        return

    try:
        # 2. 讀取資料
        df = pd.read_csv(CHIPS_FILE, dtype={'stock_id': str})
        
        # 3. 轉換日期並排序 (確保日期是由舊到新排列，以便計算連續買超)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values(['stock_id', 'date'], ascending=[True, True])

        results = []

        # 4. 依照股票代號進行篩選
        for stock_id, group in df.groupby('stock_id'):
            # 至少需要 5 天資料才能判斷「外資連買 5 天」
            if len(group) < 3:
                continue
            
            # 取得各個長度的切片
            last_5 = group.tail(5)
            last_4 = group.tail(4)
            last_3 = group.tail(3)
            
            # 取得最新一天的基本資訊
            latest_row = group.iloc[-1]
            stock_name = latest_row['name']
            last_date_str = latest_row['date'].strftime('%Y-%m-%d')
            today_trust = latest_row['trust']
            today_foreign = latest_row['foreign']
            today_ratio = latest_row.get('inst_buy_ratio', 0) # 獲取買超比率

            tags = []
            sort_priority = 99  # 預設最低優先級

            # --- 篩選條件 A: 外資投信同買 3 天 ---
            if len(last_3) == 3:
                if all(last_3['foreign'] > 0) and all(last_3['trust'] > 0):
                    tags.append("A.外投同買3天")
                    sort_priority = min(sort_priority, 1)

            # --- 篩選條件 B: 投信連買 4 天 ---
            if len(last_4) == 4:
                if all(last_4['trust'] > 0):
                    tags.append("B.投信連買4天")
                    sort_priority = min(sort_priority, 2)

            # --- 篩選條件 C: 外資連買 5 天 ---
            if len(last_5) == 5:
                if all(last_5['foreign'] > 0):
                    tags.append("C.外資連買5天")
                    sort_priority = min(sort_priority, 3)

            # 如果符合任何一個條件，則加入結果清單
            if tags:
                results.append({
                    "日期": last_date_str,
                    "代號": stock_id,
                    "名稱": stock_name,
                    "分類": " / ".join(tags),
                    "今日投信": today_trust,
                    "今日外資": today_foreign,
                    "買超比率": today_ratio,
                    "priority": sort_priority
                })

        # 5. 處理結果、排序並匯出
        if results:
            report_df = pd.DataFrame(results)
            
            # 排序邏輯：優先按優先級 (A > B > C)，其次按今日投信買超張數
            report_df = report_df.sort_values(by=['priority', '今日投信'], ascending=[True, False])
            
            # 移除輔助排序用的欄位
            final_report = report_df.drop(columns=['priority'])
            
            # 取得基準日期作為檔名
            final_date = final_report.iloc[0]['日期']
            output_filename = f"scan_result_{final_date}.csv"
            output_path = os.path.join(DATA_DIR, output_filename)
            
            # 顯示於終端機
            print("\n" + "="*90)
            print(f"🎯 籌碼篩選掃描結果 (基準日: {final_date})")
            print("="*90)
            print(final_report.to_string(index=False))
            print("="*90)
            
            # 匯出至 CSV (不包含 Index)
            final_report.to_csv(output_path, index=False, encoding='utf-8-sig')
            print(f"💾 掃描結果已存入：{output_path}\n")
        else:
            print("\n💡 掃描完成：今日無符合篩選條件的股票。")

    except Exception as e:
        print(f"❌ 掃描過程中發生錯誤：{e}")

if __name__ == "__main__":
    scan_stocks()
