import streamlit as st
import pandas as pd
import cloudscraper
import akshare as ak
from datetime import datetime
import time
import random

st.set_page_config(page_title="LOF溢价监控", layout="wide")
st.title("📈 LOF 实时溢价监控（数据源：集思录）")

# ---------- 侧边栏 ----------
with st.sidebar:
    st.header("⚙️ 设置")
    refresh_sec = st.number_input("刷新间隔（秒）", 10, 600, 30, 10)
    top_n = st.slider("显示前 N 只", 10, 100, 25, 5)
    purchase_filter = st.radio("申购状态", ["全部", "仅开放申购", "仅暂停申购"], index=0)
    manual_refresh = st.button("🔄 手动刷新")
    st.divider()
    st.info("💡 行情数据来自集思录 | 申购状态来自天天基金")

# ---------- 缓存 ----------
if "cache" not in st.session_state:
    st.session_state.cache = pd.DataFrame()
    st.session_state.cache_time = "暂无"

# ---------- 创建请求会话 ----------
scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
)

# ---------- 集思录 LOF 接口 ----------
JSL_URL = "https://www.jisilu.cn/data/lof/stock_lof_list/"
JSL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://www.jisilu.cn/data/lof/",
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
}

# ---------- 获取集思录 LOF 数据 ----------
@st.cache_data(ttl=30)
def fetch_jsl_lof():
    try:
        resp = scraper.get(JSL_URL, headers=JSL_HEADERS, timeout=20)
        if resp.status_code != 200:
            st.error(f"集思录请求失败，状态码：{resp.status_code}")
            return pd.DataFrame()
        data = resp.json()
        rows = data.get("rows", [])
        if not rows:
            st.error("集思录返回空数据")
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        # 先提取原始字段
        keep_cols = {
            "fund_id": "代码",
            "fund_nm": "简称",
            "price": "最新价",
            "estimate_value": "IOPV",      # 集思录的估算净值即为 IOPV
            "discount_rt": "溢价率(%)",    # 已为百分比
            "increase_rt": "涨跌幅",       # 涨跌幅，单位 %
            "volume": "成交量",            # 单位：手
            "amount": "成交额(元)",         # 单位：元
            "turnover_rt": "换手率(%)",    # 单位 %
        }
        # 只保留存在的列
        available = {k: v for k, v in keep_cols.items() if k in df.columns}
        df = df[list(available.keys())].rename(columns=available)

        # 转换数值（直接使用新列名）
        for col in ["最新价", "IOPV", "溢价率(%)", "涨跌幅", "成交量", "成交额(元)", "换手率(%)"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 计算成交额(万元)
        if "成交额(元)" in df.columns:
            df["成交额(万元)"] = (df["成交额(元)"] / 10000).round(0)
            df = df.drop(columns=["成交额(元)"])  # 去掉原始元单位

        # 保留最终需要的列
        final_cols = ["代码", "简称", "最新价", "IOPV", "溢价率(%)", "涨跌幅", "成交量", "成交额(万元)", "换手率(%)"]
        df = df[[c for c in final_cols if c in df.columns]]
        return df
    except Exception as e:
        st.error(f"获取集思录数据异常: {e}")
        return pd.DataFrame()

# ---------- 获取申购状态（akshare）----------
@st.cache_data(ttl=3600)
def fetch_purchase_status():
    try:
        df = ak.fund_purchase_em()
        df = df.rename(columns={"基金代码": "代码", "申购状态": "申购状态"})
        return df[["代码", "申购状态"]]
    except:
        return pd.DataFrame()

# ---------- 主循环 ----------
placeholder = st.empty()

while True:
    try:
        df = fetch_jsl_lof()
        if not df.empty:
            # 合并申购状态
            status_df = fetch_purchase_status()
            if not status_df.empty:
                df = df.merge(status_df, on="代码", how="left")
            else:
                df["申购状态"] = "未知"
            df["申购状态"] = df["申购状态"].fillna("未知")
            st.session_state.cache = df
            st.session_state.cache_time = datetime.now().strftime("%H:%M:%S")
            error = False
        else:
            df = st.session_state.cache
            error = True
    except:
        df = st.session_state.cache
        error = True

    with placeholder.container():
        col1, col2, col3 = st.columns(3)
        col1.metric("数据时间", st.session_state.cache_time)
        col2.metric("LOF数量", len(df))
        if not df.empty:
            col3.metric("最高溢价", f"{df['溢价率(%)'].max():.2f}%")

        if error:
            st.warning("⚠️ 实时获取失败，显示缓存数据")

        if df.empty:
            st.info("暂无数据")
        else:
            if purchase_filter == "仅开放申购":
                show = df[df["申购状态"].str.contains("开放", na=False)]
            elif purchase_filter == "仅暂停申购":
                show = df[df["申购状态"].str.contains("暂停", na=False)]
            else:
                show = df

            show = show.sort_values("溢价率(%)", ascending=False).head(top_n)

            cols = [
                "代码", "简称", "最新价", "IOPV", "溢价率(%)",
                "涨跌幅", "成交量", "成交额(万元)", "换手率(%)", "申购状态"
            ]
            avail = [c for c in cols if c in show.columns]

            st.dataframe(
                show[avail].style.format({
                    "最新价": "{:.3f}", "IOPV": "{:.3f}",
                    "溢价率(%)": "{:+.2f}%", "涨跌幅": "{:+.2f}%",
                    "成交量": "{:,.0f}", "成交额(万元)": "{:,.0f}",
                    "换手率(%)": "{:.2f}%",
                }),
                use_container_width=True, height=600, hide_index=True
            )

    if manual_refresh:
        st.rerun()
    jitter = random.uniform(-0.2 * refresh_sec, 0.2 * refresh_sec)
    time.sleep(max(10, refresh_sec + jitter))
    st.rerun()
