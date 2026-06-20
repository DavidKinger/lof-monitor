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
def fetch_jsl_lof():
    try:
        url = JSL_URL + f"?___t={int(time.time() * 1000)}"
        resp = scraper.get(url, headers=JSL_HEADERS, timeout=20)
    except Exception as e:
        raise Exception(f"网络请求失败: {str(e)}")

    if resp.status_code != 200:
        raise Exception(f"集思录返回状态码 {resp.status_code}")

    try:
        data = resp.json()
    except Exception as e:
        raise Exception(f"解析JSON失败: {str(e)}")

    rows = data.get("rows", [])
    if not rows:
        raise Exception("集思录返回rows为空，可能非交易时段或接口变动")

    # 检查是否是 DataTables 格式
    if rows and "cell" in rows[0]:
        # DataTables 格式：每行有 id 和 cell 数组
        # 根据集思录的列定义：基金代码, 基金简称, 现价, 估算净值(IOPV), 溢价率, 涨幅, 成交量(手), 成交额(元), 换手率
        # 实际顺序请参考返回数据，这里按常见顺序定义
        col_names = ["代码", "简称", "最新价", "IOPV", "溢价率(%)", "涨跌幅", "成交量", "成交额(元)", "换手率(%)"]
        records = []
        for row in rows:
            cells = row.get("cell", [])
            record = {}
            for i, col in enumerate(col_names):
                if i < len(cells):
                    record[col] = cells[i]
            records.append(record)
        df = pd.DataFrame(records)
    else:
        # 已经是字典格式
        df = pd.DataFrame(rows)
        keep_cols = {
            "fund_id": "代码",
            "fund_nm": "简称",
            "price": "最新价",
            "estimate_value": "IOPV",
            "discount_rt": "溢价率(%)",
            "increase_rt": "涨跌幅",
            "volume": "成交量",
            "amount": "成交额(元)",
            "turnover_rt": "换手率(%)",
        }
        available = {k: v for k, v in keep_cols.items() if k in df.columns}
        if available:
            df = df[list(available.keys())].rename(columns=available)
        else:
            raise Exception(f"未知数据格式，现有列: {df.columns.tolist()}")

    # 数值转换
    numeric_cols = ["最新价", "IOPV", "溢价率(%)", "涨跌幅", "成交量", "成交额(元)", "换手率(%)"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 成交额转万元
    if "成交额(元)" in df.columns:
        df["成交额(万元)"] = (df["成交额(元)"] / 10000).round(0)
        df = df.drop(columns=["成交额(元)"])

    final_cols = ["代码", "简称", "最新价", "IOPV", "溢价率(%)", "涨跌幅", "成交量", "成交额(万元)", "换手率(%)"]
    df = df[[c for c in final_cols if c in df.columns]]
    return df

# ---------- 获取申购状态（akshare）----------
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
    error_msg = None
    try:
        df = fetch_jsl_lof()
        if df.empty:
            error_msg = "集思录返回数据为空，可能尚未收盘或接口变动"
            raise Exception(error_msg)

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
    except Exception as e:
        error_msg = f"实时获取失败: {str(e)}"
        df = st.session_state.cache
        error = True

    with placeholder.container():
        col1, col2, col3 = st.columns(3)
        col1.metric("数据时间", st.session_state.cache_time)
        col2.metric("LOF数量", len(df))
        if not df.empty and "溢价率(%)" in df.columns:
            col3.metric("最高溢价", f"{df['溢价率(%)'].max():.2f}%")

        if error_msg:
            st.error(error_msg)
        if error:
            st.warning("⚠️ 显示的是缓存数据")

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
