# update_history.py
import os
import requests
import pandas as pd
import time
from datetime import datetime

# ==========================================
# 1. 設定
# ==========================================
# ⭐ 修正 1：改為動態路徑，這樣你的 Mac 和 GitHub 雲端都能完美相容！
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config", ".env")
DATA_DIR = os.path.join(BASE_DIR, "data")
HISTORY_DIR = os.path.join(DATA_DIR, "history")
CHIPS_CSV = os.path.join(DATA_DIR, "daily_chips_all.csv")   # ← 股票名單來源
FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"

os.makedirs(HISTORY_DIR, exist_ok=True)

REV_CSV = os.path.join(HISTORY_DIR, "revenue_history.csv")
EPS_CSV = os.path.join(HISTORY_DIR, "eps_history.csv")
DIV_CSV = os.path.join(HISTORY_DIR, "dividend_history.csv")

# ⭐ 修正 2：讓程式懂得先拿雲端鑰匙，拿不到再去本地找 .env
def get_token():
    # 優先從環境變數讀取 (GitHub Actions 雲端環境)
    token = os.environ.get("FINMIND_TOKEN")
    if token:
        return token
        
    # 如果環境變數沒有，再嘗試從本地的 config/.env 讀取
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("FINMIND_TOKEN"):
                    return line.split("=")[1].strip().strip('"').strip("'")
    return ""

TOKEN = get_token()

# ==========================================
# 2. 核心工具
# ==========================================
def fetch_fm(dataset, stock_id=None, start_date=None):
    """
    抓取 FinMind 資料，遇到限額自動等待重試，直到成功為止。
    """
    params = {"dataset": dataset, "token": TOKEN}
    if stock_id: params["data_id"] = stock_id
    if start_date: params["start_date"] = start_date

    while True:
        try:
            resp = requests.get(FINMIND_API_URL, params=params, timeout=30)
            res = resp.json()

            # 達到 API 限額 → 直接中斷程式，讓外層的 finally 存檔並上傳
            if "upper limit" in str(res.get("msg", "")):
                print(f"\n⏳ 達到 API 每小時限額！不再等待！")
                print("   自動觸發存檔機制，並交由 GitHub 推送上雲端！")
                import sys
                sys.exit(0) # 👈 關鍵：以「成功狀態(0)」結束程式，觸發資料存檔，並讓 GitHub 繼續執行 Push！

            data = res.get("data", [])
            return pd.DataFrame(data) if data else pd.DataFrame()

        except Exception as e:
            print(f"\n⚠️ 網路錯誤: {e}，5 秒後重試...")
            time.sleep(5)

def is_company_stock(stock_id: str) -> bool:
    """判斷是否為一般公司股票（4碼純數字且不以0開頭）"""
    stock_id = str(stock_id).strip()
    return stock_id.isdigit() and len(stock_id) == 4 and not stock_id.startswith("0")

def get_stock_list_from_chips():
    """從 daily_chips_all.csv 取得不重複的股票代號清單"""
    if not os.path.exists(CHIPS_CSV):
        print(f"❌ 找不到 {CHIPS_CSV}，請確認路徑是否正確。")
        return []

    try:
        # 讀取全部欄位，自動偵測股票代號欄位
        df = pd.read_csv(CHIPS_CSV, dtype=str, nrows=0)  # 先讀欄位名稱
        possible_cols = ['stock_id', 'StockID', 'code', 'Code', '股票代號', 'symbol']
        col = next((c for c in possible_cols if c in df.columns), None)

        if col is None:
            # 找不到預設欄位，讀第一欄
            df = pd.read_csv(CHIPS_CSV, dtype=str, usecols=[0])
            col = df.columns[0]
            print(f"⚠️  未找到標準欄位，使用第一欄: '{col}'")
        else:
            df = pd.read_csv(CHIPS_CSV, dtype=str, usecols=[col])

        raw_list = df[col].dropna().astype(str).unique().tolist()
        filtered = sorted([sid.strip() for sid in raw_list if is_company_stock(sid.strip())])
        print(f"📂 從 daily_chips_all.csv 讀取到 {len(filtered)} 檔公司股票")
        return filtered
    except Exception as e:
        print(f"❌ 讀取 CSV 失敗: {e}")
        return []

def get_finished_ids():
    if os.path.exists(REV_CSV):
        try:
            df_exist = pd.read_csv(REV_CSV, usecols=['stock_id'], dtype={'stock_id': str})
            return set(df_exist['stock_id'].unique())
        except:
            return set()
    return set()


def clean_rev(df):
    """整理月營收欄位，對應 stock_checker_pro.py 需求"""
    df = df.rename(columns={'date': 'date', 'stock_id': 'stock_id', 'revenue': 'revenue'})
    keep = [c for c in ['stock_id', 'date', 'revenue'] if c in df.columns]
    return df[keep]

def clean_eps(df):
    """整理 EPS 欄位，將 FinMind 的 value 重命名為 eps"""
    df = df.rename(columns={'value': 'eps'})
    keep = [c for c in ['stock_id', 'date', 'eps'] if c in df.columns]
    return df[keep]

def clean_div(df):
    """整理股利欄位，根據 FinMind V4 最新官方文件"""
    if df.empty:
        return df
        
    # 官方正解：現金股利
    cash_earn = df['CashEarningsDistribution'].fillna(0) if 'CashEarningsDistribution' in df.columns else 0
    cash_stat = df['CashStatutorySurplus'].fillna(0) if 'CashStatutorySurplus' in df.columns else 0
    df['cash_dividend'] = cash_earn + cash_stat

    # 官方正解：股票股利
    stock_earn = df['StockEarningsDistribution'].fillna(0) if 'StockEarningsDistribution' in df.columns else 0
    stock_stat = df['StockStatutorySurplus'].fillna(0) if 'StockStatutorySurplus' in df.columns else 0
    df['stock_dividend'] = stock_earn + stock_stat

    # 只保留我們需要的乾淨欄位
    keep = ['stock_id', 'date', 'cash_dividend', 'stock_dividend']
    return df[[c for c in keep if c in df.columns]]


def save_append(data_list, path):
    if data_list:
        df_new = pd.concat(data_list, ignore_index=True)
        df_new.to_csv(path, mode='a', index=False,
                      header=not os.path.exists(path), encoding='utf-8-sig')

# ==========================================
# 3. 主程式
# ==========================================
def main():
    print("🚀 啟動【全自動斷點續傳版】歷史資料庫更新...")
    print(f"⚙️  股票名單來源: {CHIPS_CSV}")
    print(f"⚙️  遇到限額將自動等待 3600 秒（1小時）後繼續，無需人工介入\n")

    # 1. 從 daily_chips_all.csv 取得股票名單
    full_list = get_stock_list_from_chips()
    if not full_list:
        return

    # 2. 比對已完成的股票（斷點續傳）
    finished_ids = get_finished_ids()
    remaining_list = [sid for sid in full_list if sid not in finished_ids]

    print(f"📊 名單總計: {len(full_list)} 檔")
    print(f"✅ 已完成:   {len(finished_ids)} 檔 (自動跳過)")
    print(f"⏳ 剩餘待補: {len(remaining_list)} 檔\n")

    if not remaining_list:
        print("🎉 恭喜！資料庫已是最新狀態。")
        return

    new_revs, new_epss, new_divs = [], [], []
    BATCH_SIZE = 50  # 每抓 50 檔存一次，避免中斷遺失太多資料

    try:
        for i, sid in enumerate(remaining_list, 1):
            print(f"[{i}/{len(remaining_list)}] 正在抓取 {sid}...", end="\r")

            # --- 月營收 ---
            r = fetch_fm("TaiwanStockMonthRevenue", sid, "2017-01-01")
            if not r.empty:
                new_revs.append(r)

            # --- EPS ---
            e = fetch_fm("TaiwanStockFinancialStatements", sid, "2017-01-01")
            if isinstance(e, pd.DataFrame) and not e.empty:
                e = e[e['type'] == 'EPS']
                if not e.empty:
                    new_epss.append(e)

            # --- 股利 ---
            d = fetch_fm("TaiwanStockDividend", sid, "2017-01-01")
            if not d.empty:
                new_divs.append(d)

            time.sleep(0.3)

            # 每 BATCH_SIZE 檔自動存一次（避免程式中斷損失資料）
            if i % BATCH_SIZE == 0:
                print(f"\n💾 批次存檔中（已抓 {i} 檔）...")
                save_append([clean_rev(r) for r in new_revs], REV_CSV)
                save_append([clean_eps(e) for e in new_epss], EPS_CSV)
                save_append([clean_div(d) for d in new_divs], DIV_CSV)
                new_revs, new_epss, new_divs = [], [], []
                print(f"✅ 存檔完成，繼續抓取...\n")

    finally:
        # 程式結束或中斷時，將剩餘資料存檔
        if new_revs or new_epss or new_divs:
            print("\n💾 正在將最後一批資料寫入本地庫...")
            save_append([clean_rev(r) for r in new_revs], REV_CSV)
            save_append([clean_eps(e) for e in new_epss], EPS_CSV)
            save_append([clean_div(d) for d in new_divs], DIV_CSV)

        total_done = len(get_finished_ids())
        print(f"\n✅ 本次結束！目前總進度: {total_done}/{len(full_list)}")
        if total_done >= len(full_list):
            print("🎉 全部資料蒐集完畢！")

if __name__ == "__main__":
    main()
