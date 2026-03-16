import streamlit as st
import pandas as pd
import datetime
import os
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
import requests
import io

# ==========================================
# 1. 頁面基本設定
# ==========================================
st.set_page_config(page_title="Stock-Track", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .stApp { background-color: #FAF9F6; color: #546E7A; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; }
    [data-testid="stSidebar"] { background-color: #F0EFEB; }
    h1, h2, h3 { color: #333333 !important; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 核心指標計算引擎（僅日K）
# ==========================================
def calculate_all_indicators(df):
    if df.empty:
        return df, 0, []
    df = df.copy()

    df['ma5']  = df['Close'].rolling(5).mean()
    df['ma10'] = df['Close'].rolling(10).mean()
    df['ma20'] = df['Close'].rolling(20).mean()
    df['ma60'] = df['Close'].rolling(60).mean()

    if 'ts' in df.columns:
        df['ts'] = pd.to_datetime(df['ts'])
        df['_date'] = df['ts'].dt.date
    else:
        df['_date'] = pd.to_datetime(df.index).dt.date
    df['_pv']  = df['Close'] * df['Volume']
    df['vwap'] = df.groupby('_date')['_pv'].cumsum() / df.groupby('_date')['Volume'].cumsum()
    df.drop(columns=['_date', '_pv'], inplace=True)

    std = df['Close'].rolling(20).std()
    df['upper_bb'] = df['ma20'] + std * 2
    df['lower_bb'] = df['ma20'] - std * 2
    df['bbw'] = (df['upper_bb'] - df['lower_bb']) / (df['ma20'] + 0.001) * 100

    tr = pd.concat([
        df['High'] - df['Low'],
        abs(df['High'] - df['Close'].shift()),
        abs(df['Low']  - df['Close'].shift())
    ], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()

    n = 14
    atr_adx = tr.rolling(n).mean()
    plus_dm  = df['High'].diff().clip(lower=0)
    minus_dm = (-df['Low'].diff()).clip(lower=0)
    df['plus_di']  = 100 * (plus_dm.rolling(n).mean()  / (atr_adx + 0.001))
    df['minus_di'] = 100 * (minus_dm.rolling(n).mean() / (atr_adx + 0.001))
    dx = 100 * (abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'] + 0.001))
    df['ADX'] = dx.rolling(n).mean()

    low_9  = df['Low'].rolling(9).min()
    high_9 = df['High'].rolling(9).max()
    df['K'] = (100 * (df['Close'] - low_9) / (high_9 - low_9 + 0.001)).ewm(com=2, adjust=False).mean()
    df['D'] = df['K'].ewm(com=2, adjust=False).mean()

    delta = df['Close'].diff()
    rs = delta.clip(lower=0).ewm(13).mean() / (-delta.clip(upper=0)).ewm(13).mean()
    df['RSI'] = 100 - (100 / (1 + rs))

    ema12 = df['Close'].ewm(span=12).mean()
    ema26 = df['Close'].ewm(span=26).mean()
    df['DIF']       = ema12 - ema26
    df['MACD_LINE'] = df['DIF'].ewm(span=9).mean()
    df['OSC']       = df['DIF'] - df['MACD_LINE']

    # 7項技術檢核
    score = 0
    check_list = []
    if len(df) > 60:
        c   = df['Close'].squeeze().astype(float)
        o   = df['Open'].squeeze().astype(float)
        h   = df['High'].squeeze().astype(float)
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
# 3. 資料轉換（週K / 月K）
# ==========================================
def resample_kline(df, freq='W'):
    """將日K資料轉成週K或月K"""
    df_r = df.copy()
    df_r.index = pd.to_datetime(df_r['ts'])
    df_r = df_r[['Open', 'High', 'Low', 'Close', 'Volume']]
    df_rs = df_r.resample(freq).agg({
        'Open':   'first',
        'High':   'max',
        'Low':    'min',
        'Close':  'last',
        'Volume': 'sum'
    }).dropna()
    df_rs['ts'] = df_rs.index

    # 重新計算均線（min_periods=1 確保資料少時也能顯示）
    df_rs['ma5']  = df_rs['Close'].rolling(5,  min_periods=1).mean()
    df_rs['ma10'] = df_rs['Close'].rolling(10, min_periods=1).mean()
    df_rs['ma20'] = df_rs['Close'].rolling(20, min_periods=1).mean()
    df_rs['ma60'] = df_rs['Close'].rolling(60, min_periods=1).mean()

    ema12 = df_rs['Close'].ewm(span=12).mean()
    ema26 = df_rs['Close'].ewm(span=26).mean()
    df_rs['DIF']       = ema12 - ema26
    df_rs['MACD_LINE'] = df_rs['DIF'].ewm(span=9).mean()
    df_rs['OSC']       = df_rs['DIF'] - df_rs['MACD_LINE']

    low_n  = df_rs['Low'].rolling(9).min()
    high_n = df_rs['High'].rolling(9).max()
    df_rs['K'] = (100 * (df_rs['Close'] - low_n) / (high_n - low_n + 0.001)).ewm(com=2, adjust=False).mean()
    df_rs['D'] = df_rs['K'].ewm(com=2, adjust=False).mean()

    return df_rs.reset_index(drop=True)


# ==========================================
# 4. 繪圖引擎（支援日K/週K/月K）
# ==========================================
def render_kline_chart(df, chart_type='日K'):
    if chart_type == '週K':
        df_plot = resample_kline(df, 'W').tail(120)
        rangebreaks = []
    elif chart_type == '月K':
        df_plot = resample_kline(df, 'ME').tail(60)
        rangebreaks = []
    else:
        df_plot = df.tail(120).copy()
        rangebreaks = [dict(bounds=["sat", "mon"])]

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

    fig.add_trace(go.Candlestick(
        x=df_plot['ts'],
        open=df_plot['Open'], high=df_plot['High'],
        low=df_plot['Low'],   close=df_plot['Close'],
        name='K線',
        increasing_line_color='#EF5350', decreasing_line_color='#26A69A',
        increasing_fillcolor='#EF5350',  decreasing_fillcolor='#26A69A'
    ), row=1, col=1, secondary_y=False)

    fig.add_trace(go.Scatter(x=df_plot['ts'], y=df_plot['ma5'],  line=dict(color='#FF7043', width=1.5), name='5MA'),  row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot['ts'], y=df_plot['ma10'], line=dict(color='#FF9800', width=1.5), name='10MA'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot['ts'], y=df_plot['ma20'], line=dict(color='#29B6F6', width=2),   name='20MA'), row=1, col=1)

    vol_colors = ['#EF5350' if r['Close'] >= r['Open'] else '#26A69A' for _, r in df_plot.iterrows()]
    fig.add_trace(go.Bar(x=df_plot['ts'], y=df_plot['Volume'], marker_color=vol_colors, opacity=0.3, name='量'), row=1, col=1, secondary_y=True)
    fig.update_yaxes(range=[0, df_plot['Volume'].max() * 3], secondary_y=True, showgrid=False, showticklabels=False, row=1, col=1)

    fig.add_trace(go.Scatter(x=df_plot['ts'], y=df_plot['K'], line=dict(color='#FF9800', width=1.5), name='K'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df_plot['ts'], y=df_plot['D'], line=dict(color='#03A9F4', width=1.5), name='D'), row=2, col=1)
    fig.add_hline(y=80, line_dash="dot", line_color="red",   row=2, col=1, opacity=0.4)
    fig.add_hline(y=20, line_dash="dot", line_color="green", row=2, col=1, opacity=0.4)

    osc_colors = ['#EF5350' if v > 0 else '#26A69A' for v in df_plot['OSC']]
    fig.add_trace(go.Bar(x=df_plot['ts'], y=df_plot['OSC'], marker_color=osc_colors, name='OSC'), row=3, col=1)
    fig.add_trace(go.Scatter(x=df_plot['ts'], y=df_plot['DIF'],       line=dict(color='#E91E63', width=1.5), name='DIF'),  row=3, col=1)
    fig.add_trace(go.Scatter(x=df_plot['ts'], y=df_plot['MACD_LINE'], line=dict(color='#3F51B5', width=1.5), name='MACD'), row=3, col=1)
    fig.add_hline(y=0, line_dash="dash", line_color="gray", row=3, col=1, opacity=0.4)

    fig.update_layout(
        height=850,
        margin=dict(l=5, r=5, t=30, b=20),
        template="plotly_white",
        xaxis_rangeslider_visible=False,
        showlegend=False,
        hovermode="x"
    )
    if rangebreaks:
        fig.update_xaxes(rangebreaks=rangebreaks)
    st.plotly_chart(fig, use_container_width=True)


# ==========================================
# 4. 主程式
# ==========================================

# ── 載入選股清單 ──
GITHUB_USER   = "jillpeng24"
GITHUB_REPO   = "Muu-stock-bot"
GITHUB_BRANCH = "main"
GITHUB_CSV_URL = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}/data/latest_selection.csv"

@st.cache_data(ttl=3600)
def load_selection_csv():
    try:
        r = requests.get(GITHUB_CSV_URL, timeout=10)
        if r.status_code == 200:
            r.encoding = 'utf-8-sig'
            df = pd.read_csv(io.StringIO(r.text))
            for col in df.columns:
                if '代號' in str(col):
                    df.rename(columns={col: '代號'}, inplace=True)
                    break
            return df
    except:
        pass
    import glob
    local_files = sorted(glob.glob("data/final_selection_*.csv"), reverse=True)
    if local_files:
        df = pd.read_csv(local_files[0], encoding='utf-8-sig')
        for col in df.columns:
            if '代號' in str(col):
                df.rename(columns={col: '代號'}, inplace=True)
                break
        return df
    return pd.DataFrame()

df_list = load_selection_csv()

with st.sidebar:
    st.title("🌿 Stock-Track")
    st.caption("台股技術分析")
    st.divider()

    source_mode = st.radio("資料來源", ["📋 選股清單", "✏️ 手動輸入"], horizontal=True)

    if source_mode == "📋 選股清單":
        if not df_list.empty:
            selected_stock = st.selectbox("請選擇標的：", df_list['代號'].astype(str) + " " + df_list['名稱'])
        else:
            st.warning("選股清單尚未載入，請改用手動輸入")
            selected_stock = st.text_input("輸入台股代號：", value="2330")
    else:
        manual_input = st.text_input("輸入台股代號：", value="2330", placeholder="例如：2330、00631L")
        selected_stock = manual_input.strip()

if selected_stock:
    code = selected_stock.split(" ")[0].strip()

    # 取得中文名稱
    if " " in selected_stock:
        stock_display = selected_stock
    else:
        stock_name = None
        # 先試 TWSE
        try:
            r = requests.get(f"https://www.twse.com.tw/zh/api/codeQuery?query={code}", timeout=5)
            if r.status_code == 200:
                data = r.json()
                suggestions = data.get('suggestions', [])
                if suggestions:
                    parts = suggestions[0].split('\t')
                    if len(parts) >= 2 and parts[0].strip() == code:
                        stock_name = parts[1].strip()
        except:
            pass
        # 備援：yfinance 取 shortName
        if not stock_name:
            try:
                info = yf.Ticker(f"{code}.TW").fast_info
                # fast_info 沒有名稱，改用 ticker info
                full_info = yf.Ticker(f"{code}.TW").info
                name_raw = full_info.get('shortName', '') or full_info.get('longName', '')
                # 過濾掉純英文（yfinance 台股名稱有時是英文）
                if name_raw and any('\u4e00' <= c <= '\u9fff' for c in name_raw):
                    stock_name = name_raw
            except:
                pass
        stock_display = f"{code} {stock_name}" if stock_name else code

    # 下載日K資料（拉5年確保週K月K有足夠資料）
    if f"df_d_{code}" not in st.session_state:
        df_d_raw = yf.download(f"{code}.TW", period="5y", progress=False)
        if df_d_raw.empty:
            df_d_raw = yf.download(f"{code}.TWO", period="5y", progress=False)
        if not df_d_raw.empty:
            if isinstance(df_d_raw.columns, pd.MultiIndex):
                df_d_raw.columns = df_d_raw.columns.get_level_values(0)
            col_map = {}
            for c in df_d_raw.columns:
                cl = c.lower().replace(' ', '_')
                if cl == 'open':   col_map[c] = 'Open'
                elif cl == 'high': col_map[c] = 'High'
                elif cl == 'low':  col_map[c] = 'Low'
                elif cl in ('close', 'adj_close'): col_map[c] = 'Close'
                elif cl == 'volume': col_map[c] = 'Volume'
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

    if not df_d_raw.empty:
        df_d, day_score, day_checks = calculate_all_indicators(df_d_raw)
    else:
        df_d = pd.DataFrame()
        day_score, day_checks = 0, []

    # 現價
    if not df_d.empty:
        _last_c = float(df_d['Close'].squeeze().iloc[-1])
        _prev_c = float(df_d['Close'].squeeze().iloc[-2])
        _chg    = _last_c - _prev_c
        _chg_pct = _chg / _prev_c * 100
        st.subheader(f"📊 {stock_display} 戰情室")
        st.metric(label="", value=f"{_last_c:.2f}", delta=f"{_chg:+.2f} ({_chg_pct:+.2f}%)")

        # ── 日K / 週K / 月K 切換 ──
        chart_type = st.radio("K線週期", ["日K", "週K", "月K"], horizontal=True, index=0)
        render_kline_chart(df_d, chart_type=chart_type)
    else:
        st.warning(f"無法取得 {code} 的資料，請確認代號是否正確。")

    # 卡片區
    st.divider()
    col1, col2 = st.columns([1, 1.6])

    with col1:
        with st.container(border=True):
            st.subheader(f"📝 技術檢核 ({day_score}/7)")
            if day_checks:
                for item in day_checks:
                    st.write(item)
            else:
                st.write("條件尚未符合或資料不足")

            # ── 基本面資料（從CSV）──
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
                last    = df_d.iloc[-1]
                curr_c  = float(last['Close'])
                atr_val = float(last['ATR'])
                rsi_val = float(last['RSI'])
                adx_val = float(last['ADX'])
                bbw_val = float(last['bbw'])
                bias_20 = (curr_c - float(last['ma20'])) / float(last['ma20']) * 100

                stop_atr     = round(curr_c - atr_val * 1.0, 2)
                stop_struct  = round(float(df_d['Low'].squeeze().iloc[-11:-1].min()), 2)
                hard_stop    = max(stop_atr, stop_struct)
                stop_pct     = round((curr_c - hard_stop) / curr_c * 100, 1)

                ma10_val   = float(last['ma10'])
                bias_10    = (curr_c - ma10_val) / ma10_val * 100
                adx_prev   = float(df_d['ADX'].squeeze().iloc[-2])
                adx_slope  = adx_val - adx_prev
                above_20ma = curr_c > float(last['ma20'])
                above_10ma = curr_c > ma10_val
                above_5ma  = curr_c > float(last['ma5'])
                vol_ratio  = float(df_d['Volume'].squeeze().iloc[-1]) / float(df_d['Volume'].squeeze().iloc[-6:-1].mean())

                def dot(level):
                    colors = {"green": "#7BAE7F", "yellow": "#C9A84C", "red": "#B56576"}
                    c = colors.get(level, "#999")
                    return f"<span style='color:{c}; font-size:1.1rem;'>●</span>"

                def row_item(dot_html, text):
                    return f"<div style='display:flex; align-items:baseline; line-height:1.7; margin-bottom:2px;'><span style='flex-shrink:0; margin-right:6px;'>{dot_html}</span><span style='font-size:0.95rem;'>{text}</span></div>"

                adx_dot   = dot("green") if adx_val > 40 else (dot("yellow") if adx_val > 25 else dot("red"))
                adx_trend = "↗ 加速" if adx_slope > 1 else ("→ 穩定" if adx_slope > -1 else "↘ 衰退")
                adx_desc  = f"{'趨勢強' if adx_val > 40 else ('成形中' if adx_val > 25 else '盤整')}　{adx_trend}"

                rsi_dot  = dot("green") if rsi_val < 65 else (dot("yellow") if rsi_val < 75 else dot("red"))
                rsi_desc = "動能正常" if rsi_val < 65 else ("略高，留意" if rsi_val < 75 else "超買，勿追")

                if not above_20ma:
                    struct_dot, struct_desc = dot("red"), "跌破20MA，結構破壞"
                elif not above_10ma:
                    struct_dot, struct_desc = dot("yellow"), "跌破10MA，開始警示"
                elif above_10ma and above_5ma:
                    struct_dot, struct_desc = dot("green"), "站上10MA與5MA，整理健康"
                else:
                    struct_dot, struct_desc = dot("yellow"), "站上10MA，5MA待確認"

                if bbw_val < 10:
                    bbw_dot, bbw_desc = dot("yellow"), "帶寬收窄，蓄勢中"
                elif adx_slope > 1:
                    bbw_dot, bbw_desc = dot("green"), "帶寬已開＋動能加速，行情正在走"
                elif adx_slope > -1:
                    bbw_dot, bbw_desc = dot("green"), "帶寬已開＋動能穩定，持續觀察"
                else:
                    bbw_dot, bbw_desc = dot("yellow"), "帶寬已開但動能衰退，行情末段，留意轉折"

                st.markdown(
                    row_item(adx_dot,    f"<b>趨勢強度</b>：ADX {adx_val:.1f} → {adx_desc}") +
                    row_item(rsi_dot,    f"<b>動能位置</b>：RSI {rsi_val:.1f} → {rsi_desc}") +
                    row_item(struct_dot, f"<b>均線結構</b>：{struct_desc}") +
                    row_item(bbw_dot,    f"<b>波動狀態</b>：BBW {bbw_val:.2f}% → {bbw_desc}"),
                    unsafe_allow_html=True
                )

                st.markdown("<div style='margin:8px 0; border-top:1px solid #eee;'></div>", unsafe_allow_html=True)

                if not above_20ma:
                    entry_html = row_item(dot("red"), "<b>進場建議</b>：跌破20MA，暫不操作")
                elif not above_10ma:
                    entry_html = row_item(dot("yellow"), "<b>進場建議</b>：跌破10MA，等待止跌確認")
                elif above_10ma and above_5ma and vol_ratio > 1.3:
                    entry_html = row_item(dot("green"), f"<b>進場建議</b>：站上5MA且量增（量比{vol_ratio:.1f}x），強勢確認可追進")
                elif above_10ma and above_5ma:
                    entry_html = row_item(dot("yellow"), f"<b>進場建議</b>：站上5MA但量未放大（量比{vol_ratio:.1f}x），等量增確認")
                elif above_10ma and abs(bias_10) < 2:
                    entry_html = row_item(dot("green"), f"<b>進場建議</b>：回踩10MA支撐（乖離{bias_10:.1f}%），相對安全進場點")
                else:
                    entry_html = row_item(dot("yellow"), "<b>進場建議</b>：整理中，等回踩10MA或量增突破5MA")

                st.markdown(
                    entry_html +
                    row_item("🛑", f"<b>停損參考</b>") +
                    f"<div style='padding-left:1.6rem; font-size:0.95rem; margin-bottom:2px;'>ATR法（較近）：{stop_atr}　距現價 -{stop_pct}%</div>" +
                    f"<div style='padding-left:1.6rem; font-size:0.95rem; margin-bottom:2px;'>10日結構低點：{stop_struct}</div>" +
                    f"<div style='padding-left:1.6rem; font-size:0.85rem; color:#999; margin-bottom:4px;'>→ 建議以ATR法為主，結構低點為極限</div>",
                    unsafe_allow_html=True
                )

                st.markdown("<div style='margin:8px 0; border-top:1px solid #eee;'></div>", unsafe_allow_html=True)

                new_exit_signals = []
                if df_d['K'].squeeze().iloc[-1] > 80 and df_d['K'].squeeze().iloc[-1] < df_d['K'].squeeze().iloc[-2]:
                    new_exit_signals.append("⚠️ KD高檔死叉，留意出場")
                if not above_10ma:
                    new_exit_signals.append("⚠️ 跌破10MA，動能轉弱，考慮減碼")
                if df_d['Volume'].squeeze().iloc[-1] < df_d['Volume'].squeeze().iloc[-2] and curr_c >= df_d['High'].squeeze().iloc[-6:-1].max():
                    new_exit_signals.append("⚠️ 量縮創高，主力出貨訊號")

                if new_exit_signals:
                    for sig in new_exit_signals:
                        icon, text = sig[:2], sig[2:]
                        st.markdown(row_item(icon, text), unsafe_allow_html=True)
                else:
                    st.markdown(row_item("✅", "<b>出場警示</b>：暫無，站上10MA可續抱"), unsafe_allow_html=True)

                st.markdown("<div style='margin:8px 0; border-top:1px solid #eee;'></div>", unsafe_allow_html=True)

                if not above_20ma:
                    conclusion = "跌破20MA，結構破壞，暫不建議操作，等待回穩再評估。"
                    c_dot = dot("red")
                elif not above_10ma:
                    conclusion = "跌破10MA開始警示，若無量縮止跌訊號，考慮先減碼觀察。"
                    c_dot = dot("yellow")
                elif above_10ma and above_5ma and vol_ratio > 1.3:
                    conclusion = f"站上5MA且量增（{vol_ratio:.1f}x），強勢確認，可追進，停損設在10MA附近。"
                    c_dot = dot("green")
                elif above_10ma and abs(bias_10) < 2:
                    conclusion = f"回踩10MA支撐，整理健康，等放量突破5MA再進場，停損 {stop_atr}。"
                    c_dot = dot("green")
                elif adx_slope < -1:
                    conclusion = "ADX斜率下降，動能衰退中，觀察是否轉為區間震盪，暫時觀望。"
                    c_dot = dot("yellow")
                else:
                    conclusion = "結構健康但尚無明確進場訊號，等待站穩5MA且量增再行動。"
                    c_dot = dot("yellow")
                st.markdown(row_item(c_dot, f"<b>結論</b>：{conclusion}"), unsafe_allow_html=True)
            else:
                st.write("資料不足，無法計算")
