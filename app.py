import streamlit as st
import pandas as pd
import akshare as ak
from datetime import datetime, time
import time as _time
import random

st.set_page_config(page_title="LOF溢价监控", layout="wide")
st.title("📈 LOF 实时溢价监控（云端版）")

def is_trading_time():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (time(9, 30) <= t <= time(11, 30)) or (time(13, 0) <= t <= time(15, 0))

with st.sidebar:
    st.header("⚙️ 设置")
    refresh_sec = st.number_input("刷新间隔（秒）", 10, 600, 30, 10)
    top_n = st.slider("显示前 N 只", 10, 100, 25, 5)
    purchase_filter = st.radio("申购状态", ["全部", "仅开放申购", "仅暂停申购"], index=0)
    manual_refresh = st.button("🔄 手动刷新")
    st.divider()
    if is_trading_time():
        st.success("🟢 交易时段 — 使用实时 IOPV")
    else:
        st.info("🔵 非交易时段 — 使用最新基金净值")

if "cache" not in st.session_state:
    st.session_state.cache = pd.DataFrame()
    st.session_state.cache_time = "暂无"

@st.cache_data(ttl=30)
def fetch_lof_data():
    spot_df = ak.fund_lof_spot_em()
    purchase_df = ak.fund_purchase_em()
    return spot_df, purchase_df

def process_data(spot_df, purchase_df):
    lof_df = spot_df[spot_df['基金类型'].str.contains('LOF', na=False)].copy()
    lof_df = lof_df.dropna(subset=['最新价', '实时参考净值'])
    purchase_df = purchase_df.rename(columns={'基金代码': '代码', '申购状态': '申购状态'})
    merged = lof_df.merge(purchase_df[['代码', '申购状态']], left_on='基金代码', right_on='代码', how='left')
    col_map = {'基金代码': '代码', '基金简称': '简称', '最新价': '最新价',
               '实时参考净值': 'IOPV', '涨跌幅': '涨跌幅', '成交量': '成交量', '成交额': '成交额(元)'}
    df = merged[list(col_map.keys())].rename(columns=col_map)
    df['最新价'] = pd.to_numeric(df['最新价'], errors='coerce')
    df['IOPV'] = pd.to_numeric(df['IOPV'], errors='coerce')
    df['成交额(元)'] = pd.to_numeric(df['成交额(元)'], errors='coerce')
    df['参考净值'] = df['IOPV']
    df['溢价率(%)'] = ((df['最新价'] - df['参考净值']) / df['参考净值'] * 100).round(2)
    df['成交额(万元)'] = (df['成交额(元)'] / 10000).round(0)
    df = df[['代码', '简称', '最新价', '参考净值', '溢价率(%)', '涨跌幅', '成交量', '成交额(万元)', '申购状态']]
    df['申购状态'] = df['申购状态'].fillna('未知')
    return df

placeholder = st.empty()

while True:
    spot_df, purchase_df = fetch_lof_data()
    if not spot_df.empty and not purchase_df.empty:
        df = process_data(spot_df, purchase_df)
        st.session_state.cache = df
        st.session_state.cache_time = datetime.now().strftime("%H:%M:%S")
        error = False
    else:
        df = st.session_state.cache
        error = True

    with placeholder.container():
        col1, col2, col3 = st.columns(3)
        col1.metric("数据时间", st.session_state.cache_time)
        col2.metric("LOF数量", len(df))
        if not df.empty:
            col3.metric("最高溢价", f"{df['溢价率(%)'].max():.2f}%")
        if not is_trading_time():
            st.info("💡 当前非交易时段，IOPV 为上一交易日净值，溢价率仅供参考")
        if error:
            st.warning("⚠️ 数据获取失败，显示缓存数据")
        if df.empty:
            st.info("暂无数据")
        else:
            if purchase_filter == "仅开放申购":
                show = df[df["申购状态"].isin(["开放申购", "限制大额申购"])]
            elif purchase_filter == "仅暂停申购":
                show = df[df["申购状态"].str.contains("暂停", na=False)]
            else:
                show = df
            show = show.sort_values("溢价率(%)", ascending=False).head(top_n)
            cols = ["代码", "简称", "最新价", "参考净值", "溢价率(%)", "涨跌幅", "成交量", "成交额(万元)", "申购状态"]
            avail = [c for c in cols if c in show.columns]
            st.dataframe(show[avail].style.format({
                "最新价": "{:.3f}", "参考净值": "{:.3f}",
                "溢价率(%)": "{:+.2f}%", "涨跌幅": "{:+.2f}%",
                "成交额(万元)": "{:,.0f}",
            }), use_container_width=True, height=600, hide_index=True)

    if manual_refresh:
        st.rerun()
    jitter = random.uniform(-0.2 * refresh_sec, 0.2 * refresh_sec)
    _time.sleep(max(10, refresh_sec + jitter))
    st.rerun()