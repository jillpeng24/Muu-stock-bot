import streamlit as st
import pandas as pd
import shioaji as sj
import datetime
import os
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
import requests
import io
try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False

# ==========================================
# 1. 頁面基本設定
# ==========================================
st.set_page_config(page_title="ZenTrade x TOTHEMOON", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .stApp { background-color: #FAF9F6; color: #546E7A; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; }
    [data-testid="stSidebar"] { background-color: #F0EFEB; }
    h1, h2, h3 { color: #333333 !important; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 永豐 API 連線
# ==========================================
@st.cache_resource
def init_shioaji():
    api = sj.Shioaji()
    try:
        api.login(api_key=st.secrets["shioaji"]["api_key"], secret_key=st.secrets["shioaji"]["secret_key"])
        return api
    except:
        return None

api = init_shioaji()

# ==========================================
# 3. 核心指標計算引擎
# ==========================================
def calculate_all_indicators(df, is_day_chart=True):
    if df.empty:
        return df, 0, []
    df = df.copy()

    # 均線系統
    df['ma5']  = df['Close'].rolling(5).mean()
    df['ma10'] = df['Close'].rolling(10).mean()
    df['ma20'] = df['Close'].rolling(20).mean()
    df['ma60'] = df['Close'].rolling(60).mean()

    # 1分K 用
    df['ema9']  = df['Close'].ewm(span=9,  adjust=False).mean()
    df['ema20'] = df['Close'].ewm(span=20, adjust=False).mean()

    # VWAP：先確保 ts 是 datetime，再按日期分組重置累積
    if 'ts' in df.columns:
        df['ts'] = pd.to_datetime(df['ts'])   # 關鍵：函數內部先轉換，確保 groupby 分組正確
        df['_date'] = df['ts'].dt.date
    else:
        df['_date'] = pd.to_datetime(df.index).dt.date
    df['_pv']  = df['Close'] * df['Volume']
    df['vwap'] = df.groupby('_date')['_pv'].cumsum() / df.groupby('_date')['Volume'].cumsum()
    df.drop(columns=['_date', '_pv'], inplace=True)

    # 布林帶 & BBW (正確公式: (upper-lower)/ma20)
    std = df['Close'].rolling(20).std()
    df['upper_bb'] = df['ma20'] + std * 2
    df['lower_bb'] = df['ma20'] - std * 2
    df['bbw'] = (df['upper_bb'] - df['lower_bb']) / (df['ma20'] + 0.001) * 100

    # ATR (新增，用於停損計算)
    tr = pd.concat([
        df['High'] - df['Low'],
        abs(df['High'] - df['Close'].shift()),
        abs(df['Low']  - df['Close'].shift())
    ], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()

    # ADX
    n = 14
    atr_adx = tr.rolling(n).mean()
    plus_dm  = df['High'].diff().clip(lower=0)
    minus_dm = (-df['Low'].diff()).clip(lower=0)
    df['plus_di']  = 100 * (plus_dm.rolling(n).mean()  / (atr_adx + 0.001))
    df['minus_di'] = 100 * (minus_dm.rolling(n).mean() / (atr_adx + 0.001))
    dx = 100 * (abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'] + 0.001))
    df['ADX'] = dx.rolling(n).mean()

    # KD
    low_9  = df['Low'].rolling(9).min()
    high_9 = df['High'].rolling(9).max()
    df['K'] = (100 * (df['Close'] - low_9) / (high_9 - low_9 + 0.001)).ewm(com=2, adjust=False).mean()
    df['D'] = df['K'].ewm(com=2, adjust=False).mean()

    # RSI
    delta = df['Close'].diff()
    rs = delta.clip(lower=0).ewm(13).mean() / (-delta.clip(upper=0)).ewm(13).mean()
    df['RSI'] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = df['Close'].ewm(span=12).mean()
    ema26 = df['Close'].ewm(span=26).mean()
    df['DIF']       = ema12 - ema26
    df['MACD_LINE'] = df['DIF'].ewm(span=9).mean()
    df['OSC']       = df['DIF'] - df['MACD_LINE']

    # --- 7 項技術檢核 ---
    score = 0
    check_list = []
    if is_day_chart and len(df) > 60:
        # float() 保護：避免 yfinance MultiIndex 造成 iloc[-1] 取到非純數值
        c   = df['Close'].squeeze().astype(float)
        o   = df['Open'].squeeze().astype(float)
        h   = df['High'].squeeze().astype(float)
        l   = df['Low'].squeeze().astype(float)
        v   = df['Volume'].squeeze().astype(float)
        ma5  = df['ma5'].squeeze().astype(float)
        ma20 = df['ma20'].squeeze().astype(float)
        ma60 = df['ma60'].squeeze().astype(float)
        dif_s  = df['DIF'].squeeze().astype(float)
        macd_s = df['MACD_LINE'].squeeze().astype(float)
        k_s    = df['K'].squeeze().astype(float)
        d_s    = df['D'].squeeze().astype(float)
        upper  = df['upper_bb'].squeeze().astype(float)
        bbw_s  = df['bbw'].squeeze().astype(float)

        if float(c.iloc[-1]) > float(ma5.iloc[-1]) > float(ma20.iloc[-1]) > float(ma60.iloc[-1]) and float(ma20.iloc[-1]) > float(ma20.iloc[-2]):
            score += 1; check_list.append("✓ 均線多頭排列")

        day_ret = (float(c.iloc[-1]) - float(c.iloc[-2])) / float(c.iloc[-2]) * 100
        avg_v20 = float(v.iloc[-21:-1].mean())
        if day_ret > 3 and float(v.iloc[-1]) > avg_v20 * 2:
            score += 1; check_list.append("✓ 帶量長紅突破")

        if float(dif_s.iloc[-1]) > float(macd_s.iloc[-1]) and float(dif_s.iloc[-1]) > 0:
            score += 1; check_list.append("✓ MACD零軸上金叉")

        if float(k_s.iloc[-1]) > float(d_s.iloc[-1]) and 20 < float(k_s.iloc[-1]) < 55:
            score += 1; check_list.append("✓ KD起漲區金叉")

        if float(c.iloc[-1]) > float(upper.iloc[-1]) and float(bbw_s.iloc[-1]) > float(bbw_s.iloc[-2]):
            score += 1; check_list.append("✓ 布林帶量開口")

        if float(c.iloc[-1]) >= float(h.iloc[-21:-1].max()):
            label = "✓ 突破波段頸線"
            if float(c.iloc[-1]) >= float(h.iloc[-61:-1].max()):
                label = "🔥 突破季頸線"
            score += 1; check_list.append(label)

        entity       = abs(float(c.iloc[-1]) - float(o.iloc[-1]))
        upper_shadow = float(h.iloc[-1]) - max(float(c.iloc[-1]), float(o.iloc[-1]))
        if float(v.iloc[-1]) > float(v.iloc[-2]) and day_ret > 0 and upper_shadow < entity * 0.5:
            score += 1; check_list.append("✓ 量價同步強勢")

    return df, score, check_list


# ==========================================
# 4. 精簡版繪圖引擎：3層圖表
#    日K：K線+均線+量 / KD / MACD
#    1分K：K線+VWAP+量 / KD / MACD
# ==========================================
def render_kline_chart(df, is_day_chart=True, entry_low=None, entry_high=None, stop_loss=None):
    df_plot = df.tail(120 if is_day_chart else 80).copy()

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.55, 0.22, 0.23],
        specs=[
            [{"secondary_y": True}],
            [{"secondary_y": False}],
            [{"secondary_y": False}],
        ]
    )

    # ── 第1層：K線 ──
    fig.add_trace(go.Candlestick(
        x=df_plot['ts'],
        open=df_plot['Open'], high=df_plot['High'],
        low=df_plot['Low'],   close=df_plot['Close'],
        name='K線',
        increasing_line_color='#EF5350', decreasing_line_color='#26A69A',
        increasing_fillcolor='#EF5350',  decreasing_fillcolor='#26A69A'
    ), row=1, col=1, secondary_y=False)

    if is_day_chart:
        fig.add_trace(go.Scatter(x=df_plot['ts'], y=df_plot['ma5'],  line=dict(color='#FF7043', width=1.5), name='5MA'),  row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot['ts'], y=df_plot['ma20'], line=dict(color='#29B6F6', width=2),   name='20MA'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot['ts'], y=df_plot['ma60'], line=dict(color='#FFCA28', width=1.5), name='60MA'), row=1, col=1)
    else:
        # 1分K：EMA9、EMA20 + 當天VWAP
        fig.add_trace(go.Scatter(x=df_plot['ts'], y=df_plot['ema9'],  line=dict(color='#FF7043', width=1.5), name='EMA9'),  row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot['ts'], y=df_plot['ema20'], line=dict(color='#29B6F6', width=1.5), name='EMA20'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot['ts'], y=df_plot['vwap'],  line=dict(color='#E91E63', width=2, dash='dot'), name='VWAP'), row=1, col=1)

    # 成交量（右軸縮放）
    vol_colors = ['#EF5350' if r['Close'] >= r['Open'] else '#26A69A' for _, r in df_plot.iterrows()]
    fig.add_trace(go.Bar(x=df_plot['ts'], y=df_plot['Volume'], marker_color=vol_colors, opacity=0.3, name='量'), row=1, col=1, secondary_y=True)
    fig.update_yaxes(range=[0, df_plot['Volume'].max() * 3], secondary_y=True, showgrid=False, showticklabels=False, row=1, col=1)

    # ── 第2層：KD ──
    fig.add_trace(go.Scatter(x=df_plot['ts'], y=df_plot['K'], line=dict(color='#FF9800', width=1.5), name='K'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df_plot['ts'], y=df_plot['D'], line=dict(color='#03A9F4', width=1.5), name='D'), row=2, col=1)
    fig.add_hline(y=80, line_dash="dot", line_color="red",   row=2, col=1, opacity=0.4)
    fig.add_hline(y=20, line_dash="dot", line_color="green", row=2, col=1, opacity=0.4)

    # ── 第3層：MACD ──
    osc_colors = ['#EF5350' if v > 0 else '#26A69A' for v in df_plot['OSC']]
    fig.add_trace(go.Bar(x=df_plot['ts'], y=df_plot['OSC'], marker_color=osc_colors, name='OSC'), row=3, col=1)
    fig.add_trace(go.Scatter(x=df_plot['ts'], y=df_plot['DIF'],       line=dict(color='#E91E63', width=1.5), name='DIF'),  row=3, col=1)
    fig.add_trace(go.Scatter(x=df_plot['ts'], y=df_plot['MACD_LINE'], line=dict(color='#3F51B5', width=1.5), name='MACD'), row=3, col=1)
    fig.add_hline(y=0, line_dash="dash", line_color="gray", row=3, col=1, opacity=0.4)

    # ── 日K 進場區間色塊 + 停損線 ──
    if is_day_chart and entry_low is not None and entry_high is not None:
        x0 = df_plot['ts'].iloc[0]
        x1 = df_plot['ts'].iloc[-1]
        # 進場區間：綠色半透明色塊
        fig.add_hrect(
            y0=entry_low, y1=entry_high,
            fillcolor="rgba(0,200,100,0.12)", line_width=0,
            annotation_text=f"🟢 進場區 {entry_low:.2f}~{entry_high:.2f}",
            annotation_position="top left",
            annotation_font=dict(color="#00897B", size=12),
            row=1, col=1
        )
    if is_day_chart and stop_loss is not None:
        # 停損線：紅色虛線
        fig.add_hline(
            y=stop_loss, line_dash="dash", line_color="#EF5350", line_width=1.5,
            annotation_text=f"🛑 停損 {stop_loss:.2f}",
            annotation_position="bottom right",
            annotation_font=dict(color="#EF5350", size=12),
            row=1, col=1
        )

    fig.update_layout(
        height=850,
        margin=dict(l=10, r=50, t=30, b=20),
        template="plotly_white",
        xaxis_rangeslider_visible=False,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0)
    )

    # 日K 排除非交易日（週末假日），修正K線被壓扁問題
    if is_day_chart:
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

    st.plotly_chart(fig, use_container_width=True)


# ==========================================
# 5. 主程式
# ==========================================

# ── GitHub Public Repo 設定 ──
GITHUB_USER   = "jillpeng24"
GITHUB_REPO   = "Muu-stock-bot"
GITHUB_BRANCH = "main"
GITHUB_CSV_URL = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}/data/latest_selection.csv"

@st.cache_data(ttl=3600)  # 快取1小時
def load_selection_csv():
    """從 GitHub public repo 抓 latest_selection.csv，找不到則備援本機"""
    try:
        r = requests.get(GITHUB_CSV_URL, timeout=10)
        if r.status_code == 200:
            r.encoding = 'utf-8-sig'
            df = pd.read_csv(io.StringIO(r.text))
            for col in df.columns:
                if '代號' in str(col):
                    df.rename(columns={col: '代號'}, inplace=True)
                    break
            st.sidebar.caption("📂 資料來源：GitHub")
            return df
    except Exception:
        pass

    # 備援：本機 data/ 資料夾（本機開發時使用）
    import glob
    local_files = sorted(glob.glob("data/final_selection_*.csv"), reverse=True)
    if local_files:
        df = pd.read_csv(local_files[0], encoding='utf-8-sig')
        for col in df.columns:
            if '代號' in str(col):
                df.rename(columns={col: '代號'}, inplace=True)
                break
        st.sidebar.caption(f"📂 本機：{os.path.basename(local_files[0])}")
        return df
    return pd.DataFrame()

df_list = load_selection_csv()

with st.sidebar:
    st.title("🌿 ZenTrade")

    # ── 雙模式資料來源 ──
    source_mode = st.radio("資料來源", ["📋 選股清單", "✏️ 手動輸入"], horizontal=True)

    if source_mode == "📋 選股清單":
        if not df_list.empty:
            selected_stock = st.selectbox("請選擇標的：", df_list['代號'].astype(str) + " " + df_list['名稱'])
        else:
            st.warning("選股清單尚未載入，請改用手動輸入")
            selected_stock = st.text_input("輸入股票代號（如 2330）：", value="2330")
    else:
        manual_input = st.text_input("輸入台股代號：", value="2330", placeholder="例如：2330、00631L")
        selected_stock = manual_input.strip()

    st.divider()

    # ── 1分K 自動刷新控制 ──
    st.markdown("**⚡ 1分K 自動刷新**")
    auto_refresh = st.toggle("開啟自動刷新（盤中用）", value=False)
    if auto_refresh:
        if HAS_AUTOREFRESH:
            st_autorefresh(interval=60000, key="min_k_refresh")  # 每60秒刷新
            st.caption("🔄 每 60 秒自動更新 1 分 K")
        else:
            st.caption("⚠️ 請安裝：pip install streamlit-autorefresh")

if selected_stock:
    code = selected_stock.split(" ")[0].strip()

    # ── 取得股票名稱（手動輸入時從yfinance抓，選股清單時從selected_stock取）──
    if " " in selected_stock:
        stock_display = selected_stock  # 選股清單：已有「代號 名稱」
    else:
        # 手動輸入：嘗試從yfinance取名稱
        @st.cache_data(ttl=86400)
        def get_stock_name(c):
            try:
                info = yf.Ticker(f"{c}.TW").info
                name = info.get('longName') or info.get('shortName', '')
                if not name:
                    info = yf.Ticker(f"{c}.TWO").info
                    name = info.get('longName') or info.get('shortName', c)
                return name
            except:
                return c
        stock_name = get_stock_name(code)
        stock_display = f"{code} {stock_name}"

    # ── Bug Fix：用 session_state 儲存日K資料，避免 tab 切換失去變數 ──
    if f"df_d_{code}" not in st.session_state:
        df_d_raw = yf.download(f"{code}.TW", period="180d", progress=False)
        if df_d_raw.empty:
            df_d_raw = yf.download(f"{code}.TWO", period="180d", progress=False)
        if not df_d_raw.empty:
            # 修正 yfinance 新版 MultiIndex 欄位問題
            if isinstance(df_d_raw.columns, pd.MultiIndex):
                df_d_raw.columns = df_d_raw.columns.get_level_values(0)
            # 統一欄位名稱（相容新舊版 yfinance）
            col_map = {}
            for c in df_d_raw.columns:
                cl = c.lower().replace(' ', '_')
                if cl == 'open':             col_map[c] = 'Open'
                elif cl == 'high':           col_map[c] = 'High'
                elif cl == 'low':            col_map[c] = 'Low'
                elif cl in ('close', 'adj_close'): col_map[c] = 'Close'
                elif cl == 'volume':         col_map[c] = 'Volume'
            df_d_raw.rename(columns=col_map, inplace=True)
            required = ['Open', 'High', 'Low', 'Close', 'Volume']
            if all(c in df_d_raw.columns for c in required):
                df_d_raw = df_d_raw[required].copy()
                df_d_raw.dropna(inplace=True)
                df_d_raw['ts'] = df_d_raw.index
                st.session_state[f"df_d_{code}"] = df_d_raw
            else:
                st.session_state[f"df_d_{code}"] = pd.DataFrame()
        else:
            st.session_state[f"df_d_{code}"] = pd.DataFrame()

    df_d_raw = st.session_state[f"df_d_{code}"]

    # 計算指標
    if not df_d_raw.empty:
        df_d, day_score, day_checks = calculate_all_indicators(df_d_raw, is_day_chart=True)
    else:
        df_d = pd.DataFrame()
        day_score, day_checks = 0, []

    st.subheader(f"📊 {stock_display} 戰情室")
    tab1, tab2 = st.tabs(["📅 日K 趨勢", "⚡ 1分K 狙擊"])

    # ── Tab1：日K趨勢 + 進出場參考卡片 ──
    with tab1:
        if not df_d.empty:
            _last    = df_d.iloc[-1]
            _curr_c  = float(_last['Close'])
            _atr     = float(_last['ATR'])
            _struct  = float(df_d['Low'].squeeze().iloc[-6:-1].min())
            _stop    = min(round(_curr_c - _atr, 2), round(_struct, 2))
            _e_high  = round(_curr_c - _atr * 0.5, 2)
            _e_low   = round(_curr_c - _atr, 2)
            render_kline_chart(df_d, is_day_chart=True, entry_low=_e_low, entry_high=_e_high, stop_loss=_stop)
        else:
            st.warning(f"無法取得 {code} 的日K資料。")

        # ── 診斷卡片區（日K頁） ──
        st.divider()
        col1, col2 = st.columns([1, 1.6])

        with col1:
            with st.container(border=True):
                st.subheader(f"📝 7 項技術檢核 ({day_score}/7)")
                if day_checks:
                    for item in day_checks:
                        st.write(item)
                else:
                    st.write("條件尚未符合或資料不足")

                # ── 基本面資料（從CSV的檢核結果欄位）──
                if not df_list.empty and code in df_list['代號'].astype(str).values:
                    stock_row = df_list[df_list['代號'].astype(str) == code].iloc[0]
                    if '檢核結果' in stock_row and pd.notna(stock_row['檢核結果']):
                        st.divider()
                        st.subheader("📋 基本面檢核")
                        for item in str(stock_row['檢核結果']).split(' | '):
                            st.write(item.strip())
                    if '警示' in stock_row and pd.notna(stock_row['警示']) and stock_row['警示'] != '-':
                        st.divider()
                        st.subheader("⚠️ 警示")
                        for w in str(stock_row['警示']).split(' | '):
                            st.write(w.strip())

        with col2:
            with st.container(border=True):
                st.subheader("🎯 進出場參考")
                if not df_d.empty:
                    last = df_d.iloc[-1]
                    curr_c  = float(last['Close'])
                    atr_val = float(last['ATR'])
                    rsi_val = float(last['RSI'])
                    adx_val = float(last['ADX'])
                    bbw_val = float(last['bbw'])

                    bias_5  = (curr_c - float(last['ma5']))  / float(last['ma5'])  * 100
                    bias_20 = (curr_c - float(last['ma20'])) / float(last['ma20']) * 100

                    stop_atr    = round(curr_c - atr_val * 1.0, 2)
                    stop_struct = round(float(df_d['Low'].squeeze().iloc[-6:-1].min()), 2)
                    hard_stop   = min(stop_atr, stop_struct)
                    stop_pct    = round((curr_c - hard_stop) / curr_c * 100, 1)
                    entry_high_v = round(curr_c - atr_val * 0.5, 2)
                    entry_low_v  = round(curr_c - atr_val * 1.0, 2)

                    exit_signals = []
                    if df_d['K'].iloc[-1] > 80 and df_d['K'].iloc[-1] < df_d['K'].iloc[-2]:
                        exit_signals.append("⚠️ KD高檔死叉，留意出場")
                    if bias_20 > 10:
                        exit_signals.append("⚠️ 20MA乖離 >10%，考慮減碼")
                    if df_d['Volume'].iloc[-1] < df_d['Volume'].iloc[-2] and curr_c >= df_d['High'].iloc[-6:-1].max():
                        exit_signals.append("⚠️ 量縮創高，主力出貨訊號")

                    # ── 和風色系燈號定義 ──
                    # 若草（綠）#7BAE7F　山吹（黃）#C9A84C　緋（紅）#B56576
                    def dot(level):
                        colors = {"green": "#7BAE7F", "yellow": "#C9A84C", "red": "#B56576"}
                        c = colors.get(level, "#999")
                        return f"<span style='color:{c}; font-size:1.1rem;'>●</span>"

                    adx_dot  = dot("green") if adx_val > 40 else (dot("yellow") if adx_val > 25 else dot("red"))
                    adx_desc = "趨勢強，適合波段" if adx_val > 40 else ("趨勢成形中" if adx_val > 25 else "盤整，暫不適合波段")
                    rsi_dot  = dot("green") if rsi_val < 65 else (dot("yellow") if rsi_val < 75 else dot("red"))
                    rsi_desc = "未超買，可考慮進場" if rsi_val < 65 else ("略高，建議等回調" if rsi_val < 75 else "超買，追高風險大")
                    bbw_dot  = dot("yellow") if bbw_val < 10 else dot("green")
                    bbw_desc = "帶寬收窄，蓄勢中" if bbw_val < 10 else "帶寬已開，行情進行中"
                    bias_dot = dot("red") if abs(bias_20) > 10 else (dot("yellow") if abs(bias_20) > 6 else dot("green"))
                    bias_desc = "乖離過大，注意回落" if abs(bias_20) > 10 else ("略偏高，稍微注意" if abs(bias_20) > 6 else "合理範圍")

                    rows = [
                        f"{adx_dot} <b>趨勢強度</b>：ADX {adx_val:.1f} → {adx_desc}",
                        f"{rsi_dot} <b>動能位置</b>：RSI {rsi_val:.1f} → {rsi_desc}",
                        f"{bbw_dot} <b>波動狀態</b>：BBW {bbw_val:.2f}% → {bbw_desc}",
                        f"{bias_dot} <b>乖離狀況</b>：20MA {bias_20:.2f}% → {bias_desc}",
                    ]
                    st.markdown("<div style='line-height:1.7; font-size:0.95rem;'>" + "<br>".join(rows) + "</div>", unsafe_allow_html=True)

                    st.divider()

                    # ── 進出場數值 ──
                    entry_rows = [
                        f"🛒 <b>建議進場區</b>：{entry_low_v} ~ {entry_high_v}",
                        f"🛑 <b>停損設在</b>：{hard_stop:.2f}　（距現價 -{stop_pct}%）",
                        f"<span style='color:#999; font-size:0.85rem;'>　結構低: {stop_struct} / ATR法: {stop_atr}</span>",
                    ]
                    st.markdown("<div style='line-height:1.7; font-size:0.95rem;'>" + "<br>".join(entry_rows) + "</div>", unsafe_allow_html=True)

                    st.divider()

                    # ── 出場警示 ──
                    if exit_signals:
                        st.markdown("<div style='line-height:1.7; font-size:0.95rem;'>" + "<br>".join(exit_signals) + "</div>", unsafe_allow_html=True)
                    else:
                        st.markdown("<div style='font-size:0.95rem;'>✅ <b>出場警示</b>：暫無，持續觀察</div>", unsafe_allow_html=True)

                    st.divider()

                    # ── 結論 ──
                    if adx_val > 25 and rsi_val < 65 and abs(bias_20) < 10:
                        conclusion = f"趨勢明確且動能正常，等回調至 {entry_low_v}~{entry_high_v} 附近進場，停損 {hard_stop:.2f}，風險報酬合理。"
                        c_dot = dot("green")
                    elif adx_val > 25 and rsi_val >= 65:
                        conclusion = "趨勢強但動能偏高，建議等 RSI 回落至 60 以下再進場，勿追高。"
                        c_dot = dot("yellow")
                    elif adx_val <= 25:
                        conclusion = "趨勢尚未成形，目前盤整中，建議觀望等待方向明確。"
                        c_dot = dot("red")
                    else:
                        conclusion = "綜合指標混合訊號，建議保守觀望。"
                        c_dot = dot("yellow")
                    st.markdown(f"<div style='font-size:0.95rem;'>{c_dot} <b>結論</b>：{conclusion}</div>", unsafe_allow_html=True)
                else:
                    st.write("資料不足，無法計算")

    # ── Tab2：1分K狙擊 + 盤中建議 ──
    with tab2:
        if api:
            kbars = api.kbars(
                api.Contracts.Stocks[code],
                start=(datetime.date.today() - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
            )
            df_m, _, _ = calculate_all_indicators(pd.DataFrame({**kbars}), is_day_chart=False)
            render_kline_chart(df_m, is_day_chart=False)

            if len(df_m) > 20:
                st.divider()
                with st.container(border=True):
                    st.subheader("⚡ 盤中進出場建議")
                    last_m  = df_m.iloc[-1]
                    curr_p  = float(last_m['Close'])
                    vwap_p  = float(last_m['vwap'])
                    ema9_p  = float(last_m['ema9'])
                    ema20_p = float(last_m['ema20'])
                    rsi_m   = float(last_m['RSI'])
                    k_m     = float(last_m['K'])
                    d_m     = float(last_m['D'])
                    macd_m  = float(last_m['OSC'])

                    last_ts = pd.to_datetime(last_m['ts'])
                    st.caption(f"最後更新：{last_ts.strftime('%H:%M')}　{'🔄 自動刷新中' if auto_refresh else '手動模式'}")

                    # ── 和風燈號（與日K卡片共用同一色系）──
                    def dot(level):
                        colors = {"green": "#7BAE7F", "yellow": "#C9A84C", "red": "#B56576"}
                        c = colors.get(level, "#999")
                        return f"<span style='color:{c}; font-size:1.1rem;'>●</span>"

                    vwap_dot  = dot("green") if curr_p > vwap_p else dot("red")
                    vwap_desc = "站上VWAP，買方強勢" if curr_p > vwap_p else "跌破VWAP，賣方主導"

                    if curr_p > ema9_p > ema20_p:
                        ema_dot, ema_desc = dot("green"), "多頭排列，短線偏多"
                    elif curr_p < ema9_p < ema20_p:
                        ema_dot, ema_desc = dot("red"), "空頭排列，短線偏空"
                    else:
                        ema_dot, ema_desc = dot("yellow"), "EMA糾結，方向不明"

                    rsi_dot  = dot("green") if rsi_m < 65 else (dot("yellow") if rsi_m < 75 else dot("red"))
                    rsi_desc = "動能正常" if rsi_m < 65 else ("略高注意" if rsi_m < 75 else "短線超買")

                    if k_m > d_m and k_m < 50:
                        kd_dot, kd_desc = dot("green"), "低檔金叉，短線買訊"
                    elif k_m > d_m and k_m >= 50:
                        kd_dot, kd_desc = dot("yellow"), "中高檔持多，留意"
                    elif k_m < d_m and k_m > 70:
                        kd_dot, kd_desc = dot("red"), "高檔死叉，短線賣訊"
                    else:
                        kd_dot, kd_desc = dot("yellow"), "觀望"

                    macd_dot  = dot("green") if macd_m > 0 else dot("red")
                    macd_desc = "動能偏多" if macd_m > 0 else "動能偏空"

                    m_rows = [
                        f"{vwap_dot} <b>VWAP</b>：現價 {curr_p:.2f} vs {vwap_p:.2f} → {vwap_desc}",
                        f"{ema_dot} <b>EMA排列</b>：{ema_desc}",
                        f"{rsi_dot} <b>RSI</b>：{rsi_m:.1f} → {rsi_desc}",
                        f"{kd_dot} <b>KD</b>：K={k_m:.1f} D={d_m:.1f} → {kd_desc}",
                        f"{macd_dot} <b>MACD動能</b>：{macd_m:.4f} → {macd_desc}",
                    ]
                    st.markdown("<div style='line-height:1.7; font-size:0.95rem;'>" + "<br>".join(m_rows) + "</div>", unsafe_allow_html=True)

                    st.divider()

                    buy_conditions  = sum([curr_p > vwap_p, curr_p > ema9_p > ema20_p, rsi_m < 65, k_m > d_m and k_m < 50, macd_m > 0])
                    sell_conditions = sum([curr_p < vwap_p, curr_p < ema9_p, rsi_m > 75, k_m < d_m and k_m > 70, macd_m < 0])

                    if buy_conditions >= 4:
                        st.success("● 進場訊號：多項指標同步偏多，可考慮買進")
                    elif sell_conditions >= 4:
                        st.error("● 出場訊號：多項指標同步偏空，考慮減碼或出場")
                    elif buy_conditions >= 3:
                        st.info("● 偏多觀望：條件尚未全部到位，等待更明確訊號")
                    else:
                        st.warning("● 觀望：訊號混合，暫不操作")
        else:
            st.warning("永豐 API 未連線，無法顯示 1 分 K。")


