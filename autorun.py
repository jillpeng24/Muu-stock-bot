
"""
完整的股票搜尋系統自動化執行腳本
依序執行：資料更新 → 籌碼掃描 → 基本面檢核 → 技術面分析
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

def run_step(script_name, description):
    """執行單一步驟並處理錯誤"""
    print(f"\n{'='*60}")
    print(f"📍 {description}")
    print(f"{'='*60}")
    try:
        # 動態導入並執行
        module_name = script_name.replace('.py', '')
        module = __import__(module_name)
        if hasattr(module, 'main'):
            module.main()
        else:
            print(f"⚠️ {script_name} 沒有 main() 函數，跳過")
        return True
    except Exception as e:
        print(f"❌ {description} 執行失敗: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("🤖 股票搜尋系統 - 完整自動化執行")
    print(f"📂 工作目錄: {BASE_DIR}")
    print(f"📁 資料目錄: {DATA_DIR}")
    
    # 檢查必要的環境變數
    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        print("⚠️ 警告: FINMIND_TOKEN 未設定，基本面檢核可能受限")
    
    # 執行流程
    steps = [
        ("update_data.py", "步驟 1: 更新每日籌碼資料"),
        ("chip_scanner.py", "步驟 2: 籌碼面掃描"),
        ("stock_checker.py", "步驟 3: 基本面檢核"),
        ("technical_analyzer.py", "步驟 4: 技術面分析")
    ]
    
    success_count = 0
    for script, desc in steps:
        if run_step(script, desc):
            success_count += 1
    
    print(f"\n{'='*60}")
    print(f"✅ 執行完成: {success_count}/{len(steps)} 個步驟成功")
    print(f"{'='*60}")
    
    # 列出生成的檔案
    if DATA_DIR.exists():
        files = sorted(DATA_DIR.glob("*.csv"))
        if files:
            print("\n📊 生成的檔案:")
            for f in files:
                size = f.stat().st_size
                print(f"  - {f.name} ({size:,} bytes)")
        else:
            print("\n⚠️ data/ 目錄中沒有生成 CSV 檔案")
    
    return success_count == len(steps)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
