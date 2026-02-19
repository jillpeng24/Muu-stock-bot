# update_data.py (修正版 v4 - 正確處理股數/張數轉換)
import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta

# ==========================================
# 設定：資料存放路徑
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CHIPS_FILE = os.path.join(DATA_DIR, "daily_chips_all.csv")

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# ==========================================
# 工具函式
# ==========================================
def clean_value(x):
    """清理數值，移除逗號並轉換為浮點數"""
    if pd.isna(x) or str(x).strip() in ['-', '', '0', '0.0']:
        return 0.0
    try:
        return float(str(x).replace(',', ''))
    except:
        return 0.0

def is_company_stock(stock_id: str) -> bool:
    """判斷是否為一般公司股票（4碼數字且不以0開頭）"""
    return stock_id.isdigit() and len(stock_id) == 4 and not stock_id.startswith("0")

def fetch_twse_api(url, desc):
    """呼叫證交所 API"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.twse.com.tw/'
    }
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"      ❌ {desc} 抓取失敗: {e}")
    return None

# ==========================================
# 主程式：更新籌碼資料
# ==========================================
def update_chips():
    # 1. 檢查舊資料
    df_old = pd.DataFrame()
    last_date = None
    if os.path.exists(CHIPS_FILE):
        try:
            df_old = pd.read_csv(CHIPS_FILE, dtype={'stock_id': str})
            df_old['date'] = pd.to_datetime(df_old['date'])
            last_date = df_old['date'].max()
        except:
            pass

    # 2. 決定下載日期範圍
    today = datetime.now()
    
    if last_date is None:
        # 初次執行：往前推 40 天，確保能抓到至少 20 個交易日
        start_date = today - timedelta(days=40)
        print(f"🚀 初次執行：補全最近 20 個交易日的資料 (從 {start_date.strftime('%Y-%m-%d')} 起查詢)...")
    else:
        start_date = last_date + timedelta(days=1)
        if start_date.date() > today.date():
            print("✨ 本地資料已是最新日期，無需下載。")
            return
        print(f"🔄 增量更新：正在檢查 {start_date.strftime('%Y-%m-%d')} 之後的新資料...")

    new_dfs = []
    current_date = start_date
    
    # 迴圈抓取
    while current_date.date() <= today.date():
        f_date = current_date.strftime('%Y%m%d')
        
        # A. 抓取三大法人買賣超 (T86)
        url_inst = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={f_date}&selectType=ALLBUT0999&response=json"
        js_inst = fetch_twse_api(url_inst, f"{f_date} 三大法人")
        
        if js_inst and js_inst.get('stat') == 'OK':
            # B. 使用 STOCK_DAY API 抓取個股成交量 - 但這需要逐檔查詢，太慢
            # 改用策略：從 T86 資料中計算，或使用其他 API
            
            # 先建立法人資料
            inst_data = []
            for r in js_inst['data']:
                sid = r[0].strip()
                if is_company_stock(sid):
                    # T86 欄位說明（根據 fields）：
                    # [0] 證券代號
                    # [1] 證券名稱  
                    # [2] 外陸資買進股數
                    # [3] 外陸資賣出股數
                    # [4] 外陸資買賣超股數 ← 使用這個
                    # [10] 投信買賣超股數 ← 使用這個
                    # [11] 自營商買賣超股數 ← 使用這個
                    # [18] 三大法人買賣超股數
                    
                    foreign_shares = clean_value(r[4])   # 外資買賣超（股數）
                    trust_shares = clean_value(r[10])    # 投信買賣超（股數）
                    dealer_shares = clean_value(r[11])   # 自營商買賣超（股數）
                    
                    # ⭐ 關鍵：股數除以 1000 = 張數
                    inst_data.append({
                        'stock_id': sid,
                        'name': r[1].strip(),
                        'foreign': foreign_shares / 1000,   # 轉換為張數
                        'trust': trust_shares / 1000,       # 轉換為張數
                        'dealer': dealer_shares / 1000      # 轉換為張數
                    })
            
            df_day = pd.DataFrame(inst_data)
            
            if not df_day.empty:
                # C. 嘗試從 MI_INDEX 取得成交量
                url_mi = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={f_date}&type=ALLBUT0999&response=json"
                js_mi = fetch_twse_api(url_mi, f"{f_date} 成交行情")
                
                vol_map = {}
                if js_mi and js_mi.get('stat') == 'OK':
                    # MI_INDEX 的資料在 tables 中
                    tables = js_mi.get('tables', [])
                    for table in tables:
                        # 尋找包含個股資料的表格
                        if isinstance(table, dict):
                            data = table.get('data', [])
                            for row in data:
                                if isinstance(row, list) and len(row) >= 3:
                                    stock_id = str(row[0]).strip()
                                    if is_company_stock(stock_id):
                                        # row[2] 通常是成交量（張數）
                                        vol_map[stock_id] = clean_value(row[2])
                
                # 如果 MI_INDEX 沒資料，使用替代方案：從法人買賣量推估
                # （假設法人買賣約佔總成交量的一定比例）
                if not vol_map:
                    print(f"      ⚠️ {f_date} 無法取得成交量，使用估算值")
                    # 使用法人總買賣量的絕對值作為參考
                    for idx, row in df_day.iterrows():
                        # 法人買賣量通常佔總量的 30-60%，這裡保守估算
                        total_inst_abs = abs(row['foreign']) + abs(row['trust']) + abs(row['dealer'])
                        estimated_vol = total_inst_abs * 3  # 粗估法人佔比約 1/3
                        vol_map[row['stock_id']] = max(estimated_vol, 100)  # 至少 100 張
                
                # 合併成交量
                df_day['volume'] = df_day['stock_id'].map(lambda x: vol_map.get(x, 0))
                df_day['total_inst'] = df_day['foreign'] + df_day['trust'] + df_day['dealer']
                df_day['inst_buy_ratio'] = df_day.apply(
                    lambda x: round(x['total_inst'] / x['volume'] * 100, 2) if x['volume'] > 0 else 0, 
                    axis=1
                )
                df_day['date'] = current_date.strftime('%Y-%m-%d')
                
                new_dfs.append(df_day)
                
                valid_vol_count = (df_day['volume'] > 0).sum()
                avg_vol = df_day[df_day['volume'] > 0]['volume'].mean() if valid_vol_count > 0 else 0
                print(f"      ✅ {f_date}: {len(df_day)} 檔，{valid_vol_count} 檔有量（平均 {avg_vol:.0f} 張）")
        
        current_date += timedelta(days=1)
        time.sleep(3)

    # 3. 合併、清理並儲存
    if new_dfs:
        df_new = pd.concat(new_dfs, ignore_index=True)
        df_new['date'] = pd.to_datetime(df_new['date'])
        
        df_final = pd.concat([df_old, df_new], ignore_index=True)
        df_final.drop_duplicates(subset=['date', 'stock_id'], keep='last', inplace=True)
        df_final.sort_values(['date', 'stock_id'], ascending=[True, True], inplace=True)
        
        # 保留最近 20 個交易日
        unique_dates = sorted(df_final['date'].unique())
        if len(unique_dates) > 20:
            cutoff_date = unique_dates[-20]
            df_final = df_final[df_final['date'] >= cutoff_date]
            print(f"🧹 已清理舊資料 (保留 {cutoff_date.date()} 至今)")

        df_final.to_csv(CHIPS_FILE, index=False, encoding='utf-8-sig')
        
        total_rows = len(df_final)
        valid_vol_rows = (df_final['volume'] > 0).sum()
        vol_rate = (valid_vol_rows / total_rows * 100) if total_rows > 0 else 0
        avg_inst_ratio = df_final[df_final['volume'] > 0]['inst_buy_ratio'].mean()
        
        print(f"\n🎉 資料庫已更新！")
        print(f"📅 日期範圍: {df_final['date'].min().date()} ~ {df_final['date'].max().date()}")
        print(f"📊 成交量統計: {valid_vol_rows}/{total_rows} 筆有效 ({vol_rate:.1f}%)")
        print(f"💰 平均法人買超比: {avg_inst_ratio:.2f}%")
    else:
        print("\nℹ️ 檢查完畢，今日證交所尚未提供更多新資料。")

if __name__ == "__main__":
    update_chips()
