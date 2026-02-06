# autorun.py (GitHub 雲端/多人推播優化版)
import os
import subprocess
import pandas as pd
import requests
from pathlib import Path
from datetime import datetime

# ==========================================
# 設定與路徑 (雲端通用相對路徑)
# ==========================================
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
LINE_API_URL = "https://api.line.me/v2/bot/message/push"

# 確保雲端環境中有 data 資料夾
DATA_DIR.mkdir(parents=True, exist_ok=True)

def get_line_config():
    """優先抓取 GitHub Secrets 環境變數"""
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user_id_string = os.environ.get("LINE_USER_ID")
    return token, user_id_string

def run_step(script_name):
    """執行子腳本並確認是否成功"""
    print(f"\n🚀 正在執行: {script_name}")
    try:
        # GitHub Actions 統一使用 python 指令
        subprocess.run(["python", script_name], check=True)
        return True
    except Exception as e:
        print(f"❌ {script_name} 執行失敗: {e}")
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
        print(f"⚠️ 對 ID {user_id} 發送錯誤: {e}")

def push_optimized_results(final_csv):
    """支援多收件人的推播邏輯"""
    token, user_id_string = get_line_config()

    if not token or not user_id_string:
        print("❌ 找不到 LINE 設定，取消推播。")
        return

    # 關鍵修改：支援以逗號分隔的多個 ID
    user_ids = [uid.strip() for uid in user_id_string.split(",") if uid.strip()]

    # 讀取 CSV 並排序
    if not os.path.exists(final_csv):
        print(f"⚠️ 找不到檔案: {final_csv}")
        return
        
    df = pd.read_csv(final_csv)
    if df.empty:
        print("ℹ️ 今日無符合選股。")
        return

    df = df.sort_values(by="技術面得分", ascending=False)
    
    today = datetime.now().strftime("%Y-%m-%d")
    header = f"🏆 籌碼+技術面選股報表\n📅 日期：{today}\n📊 總計：{len(df)} 檔\n"
    header += "══════════════\n"
    
    all_msg = header
    for _, row in df.iterrows():
        stock_info = (
            f"【{row['代號']} {row['名稱']}】({row['技術面得分']})\n"
            f"● 分類：{row['分類']}\n"
            f"● 技術面：{row['技術面檢核']}\n"
            f"● 基本面：{row['檢核結果']}\n"
            f"● 警示：{row.get('警示', '-')}\n"
            f"────────────────\n"
        )
        
        # LINE 單則訊息上限 5000 字
        if len(all_msg) + len(stock_info) > 4500:
            for uid in user_ids:
                send_line_request(token, uid, all_msg)
            all_msg = "續前則報表：\n"
            
        all_msg += stock_info

    # 最終發送給所有人
    for uid in user_ids:
        send_line_request(token, uid, all_msg)
        print(f"✅ 已完成推播至 ID: {uid}")

def main():
    print(f"=== ⚙️ 自動化排程啟動 ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")
    
    # 依序執行四個核心腳本
    scripts = [
        "update_data.py",
        "chip_scanner.py",
        "stock_checker.py",
        "technical_analyzer.py"
    ]

    for script in scripts:
        if not run_step(script):
            return

    # 搜尋最新產出的結果檔並推播
    final_files = list(DATA_DIR.glob("final_selection_*.csv"))
    if final_files:
        latest_file = sorted(final_files)[-1]
        push_optimized_results(str(latest_file))
    else:
        print("⚠️ 找不到最終選股檔案。")

    print("\n✨ 全部分析與推播任務已完成！")

if __name__ == "__main__":
    main()
