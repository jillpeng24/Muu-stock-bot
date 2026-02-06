# update_data.py (GitHub 雲端通用版)
import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta

# ==========================================
# 設定：資料存放路徑 (已移除 Mac 絕對路徑)
# ==========================================
# 取得目前程式檔案所在的資料夾，無論在 Mac 還是雲端都適用
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CHIPS_FILE = os.path.join(DATA_DIR, "daily_chips_all.csv")

# ☁️ 雲端環境必備：如果 data 資料夾不存在就建立它
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
        # 初次執行：往前推 40 天
        start_date = today - timedelta(days=40)
        print(f"🚀 初次執行：補全最近資料 (從 {start_date.strftime('%Y-%m-%d')} 起)...")
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
            inst_data = []
            for r in js_inst['data']:
                sid = r[0].strip()
                if is_company_stock(sid):
                    # ⭐ 關鍵：股數除以 1000 = 張數
                    foreign_shares = clean_value(r[4]) / 1000  
                    trust_shares = clean_value(r[10]) / 1000   
                    dealer_shares = clean_value(r[11]) / 1000  
                    
                    inst_data.append({
                        'stock_id': sid,
                        'name': r[1].strip(),
                        'foreign': foreign_shares,   
                        'trust': trust_shares,       
                        'dealer': dealer_shares      
                    })
            
            df_day = pd.DataFrame(inst_data)
            
            if not df_day.empty:
                # B. 取得成交量
                url_mi = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={f_date}&type=ALLBUT0999&response=json"
                js_mi = fetch_twse_api(url_mi, f"{f_date} 成交行情")
                
                vol_map = {}
                if js_mi and js_mi.get('stat') == 'OK':
                    tables = js_mi.get('tables', [])
                    for table in tables:
                        if isinstance(table, dict):
                            data = table.get('data', [])
                            for row in data:
                                if isinstance(row, list) and len(row) >= 3:
                                    stock_id = str(row[0]).strip()
                                    if is_company_stock(stock_id):
                                        vol_map[stock_id] = clean_value(row[2]) / 1000 # 轉張數
                
                if not vol_map:
                    for idx, row in df_day.iterrows():
                        total_inst_abs = abs(row['foreign']) + abs(row['trust']) + abs(row['dealer'])
                        vol_map[row['stock_id']] = max(total_inst_abs * 3, 100)
                
                # 合併資料
                df_day['volume'] = df_day['stock_id'].map(lambda x: vol_map.get(x, 0))
                df_day['total_inst'] = df_day['foreign'] + df_day['trust'] + df_day['dealer']
                df_day['inst_buy_ratio'] = df_day.apply(
                    lambda x: round(x['total_inst'] / x['volume'] * 100, 2) if x['volume'] > 0 else 0, 
                    axis=1
                )
                df_day['date'] = current_date.strftime('%Y-%m-%d')
                new_dfs.append(df_day)
                print(f"      ✅ {f_date}: 已抓取 {len(df_day)} 檔資料")
        
        current_date += timedelta(days=1)
        time.sleep(3) # 避開證交所封鎖

    # 3. 合併、清理並儲存
    if new_dfs:
        df_new = pd.concat(new_dfs, ignore_index=True)
        df_new['date'] = pd.to_datetime(df_new['date'])
        
        df_final = pd.concat([df_old, df_new], ignore_index=True)
        df_final.drop_duplicates(subset=['date', 'stock_id'], keep='last', inplace=True)
        df_final.sort_values(['date', 'stock_id'], ascending=[True, True], inplace=True)
        
        # 限制資料庫大小，保留最近 20 個交易日
        unique_dates = sorted(df_final['date'].unique())
        if len(unique_dates) > 20:
            df_final = df_final[df_final['date'] >= unique_dates[-20]]

        df_final.to_csv(CHIPS_FILE, index=False, encoding='utf-8-sig')
        print(f"\n🎉 資料庫已更新！目前日期至: {df_final['date'].max().date()}")
    else:
        print("\nℹ️ 無新資料下載。")

if __name__ == "__main__":
    update_chips()
