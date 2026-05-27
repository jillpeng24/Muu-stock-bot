import os
import subprocess
import pandas as pd
import requests
from pathlib import Path
from datetime import datetime, timedelta, timezone

# ==========================================
# 設定與路徑 (完全對齊 GitHub 工作目錄)
# ==========================================
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
LINE_API_URL = "https://api.line.me/v2/bot/message/push"

def is_market_open_today():
    """透過證交所 MIS 即時系統檢查今天台股是否有開市"""
    # 🌟 強制使用台灣時間 (UTC+8) 避免 GitHub 伺服器時區誤判
    tw_tz = timezone(timedelta(hours=8))
    today = datetime.now(tw_tz)
    today_str = today.strftime("%Y%m%d")
    
    # 週末直接判定休市，不發送網路請求
    if today.weekday() >= 5:
        return False
        
    url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            latest_trade_date = data["msgArray"][0]["d"]
            # 如果大盤最新交易日等於今天，代表有開市
            return latest_trade_date == today_str
        else:
            print(f"⚠️ 證交所 MIS API 異常 (狀態碼: {response.status_code})，預設繼續執行。")
            return True
    except Exception as e:
        print(f"⚠️ 判斷開市狀態時發生網路錯誤 ({e})，預設視為有開市。")
        return True

def load_config():
    """從 GitHub Secrets (環境變數) 讀取設定"""
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")
    return token, user_id

def run_step(script_name):
    """執行子腳本並確認是否成功"""
    print(f"\n🚀 正在執行: {script_name}")
    try:
        # GitHub Actions 環境中使用 python 即可
        subprocess.run(["python", script_name], check=True)
        return True
    except subprocess.CalledProcessError:
        print(f"❌ {script_name} 執行失敗，中斷後續流程。")
        return False

def send_line_request(token, user_id, text):
    """傳送 LINE 訊息請求"""
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": text}]
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    try:
        r = requests.post(LINE_API_URL, headers=headers, json=payload, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"⚠️ LINE 發送錯誤: {e}")

def push_optimized_results(final_csv):
    """將所有股票結果整合進長訊息發送"""
    token, user_id = load_config()

    if not token or not user_id:
        print("❌ 找不到 GitHub Secrets 中的 LINE 設定，取消推播。")
        return

    # 讀取 CSV
    df = pd.read_csv(final_csv)
    # 保持原有的排序邏輯
    if "技術面得分" in df.columns:
        df = df.sort_values(by="技術面得分", ascending=False)
    
    # 🌟 確保報表上的日期是台灣時間
    tw_tz = timezone(timedelta(hours=8))
    today = datetime.now(tw_tz).strftime("%Y-%m-%d")
    header = f"🏆 籌碼+技術面最終選股報表\n📅 日期：{today}\n📊 總計：{len(df)} 檔\n"
    header += "══════════════\n"
    
    all_msg = header
    for _, row in df.iterrows():
        stock_info = (
            f"【{row['代號']} {row['名稱']}】({row.get('技術面得分', '-')})\n"
            f"● 分類：{row.get('分類', '-')}\n"
            f"● 技術面：{row.get('技術面檢核', '-')}\n"
            f"● 基本面：{row.get('檢核結果', '-')}\n"
            f"● 警示：{row.get('警示', '-')}\n"
            f"────────────────\n"
        )
        
        if len(all_msg) + len(stock_info) > 4500:
            send_line_request(token, user_id, all_msg)
            all_msg = "續前則報表：\n"
            
        all_msg += stock_info

    send_line_request(token, user_id, all_msg)
    print(f"✅ 已完成 {len(df)} 檔股票的合併推播。")

def main():
    tw_tz = timezone(timedelta(hours=8))
    print(f"=== ⚙️ GitHub 自動化排程啟動 ({datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M')}) ===")
    
    # 🌟 檢查今天台股是否有開市
    if not is_market_open_today():
        print("📅 經 MIS 系統確認今日台股休市，系統自動停止後續動作。")
        return
        
    # 確保 data 資料夾存在
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # 依序執行四個核心腳本 (路徑對齊 GitHub 根目錄)
    scripts = [
        "update_data.py",
        "chip_scanner.py",
        "stock_checker_cloudpro.py",
        "technical_analyzer.py"
    ]

    for script in scripts:
        script_path = BASE_DIR / script
        if not run_step(str(script_path)):
            return

    # 搜尋最新產出的結果檔
    final_files = list(DATA_DIR.glob("final_selection_*.csv"))
    if final_files:
        latest_file = sorted(final_files)[-1]
        push_optimized_results(latest_file)
    else:
        print("⚠️ 找不到最終選股檔案。")

    print("\n✨ GitHub Actions 任務已完成！")

if __name__ == "__main__":
    main()
