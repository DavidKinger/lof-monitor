import streamlit as st
import pandas as pd
import cloudscraper
from datetime import datetime, time
import time as _time
import random

st.set_page_config(page_title="LOF溢价监控", layout="wide")
st.title("📈 LOF 实时溢价监控")

# ---------- 交易时段判断 ----------
def is_trading_time():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (time(9, 30) <= t <= time(11, 30)) or (time(13, 0) <= t <= time(15, 0))

# ---------- 侧边栏 ----------
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

# ---------- 缓存 ----------
if "cache" not in st.session_state:
    st.session_state.cache = pd.DataFrame()
    st.session_state.cache_time = "暂无"
if "nav_cache" not in st.session_state:
    st.session_state.nav_cache = {}

# ---------- 创建 cloudscraper 会话 ----------
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'mobile': False
    }
)

# ---------- 获取 LOF 行情（使用 cloudscraper）----------
@st.cache_data(ttl=30)
def fetch_lof_list():
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    fields = "f2,f3,f4,f5,f6,f8,f12,f14,f15,f16,f17,f18,f144,f145"
    params = {
        "pn": "1", "pz": "10000", "po": "1", "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2", "invt": "2", "fid": "f3",
        "fs": "b:MK0404,b:MK0405,b:MK0406,b:MK0407",
        "fields": fields,
        "_": str(int(_time.time() * 1000))
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/center/gridlist.html",
    }
    try:
        resp = scraper.get(url, params=params, headers=headers, timeout=20)
        data = resp.json()
        if not data.get("data") or not data["data"].get("diff"):
            return pd.DataFrame()
        raw = data["data"]["diff"]
        if isinstance(raw, dict):
            records = list(raw.values())
        else:
            records = raw
        df = pd.DataFrame(records)
        col_map = {
            "f12": "代码", "f14": "简称", "f2": "最新价",
            "f145": "IOPV", "f3": "涨跌幅", "f4": "涨跌额",
            "f5": "成交量(手)", "f6": "成交额(元)", "f8": "换手率(%)",
            "f15": "最高价", "f16": "最低价", "f17": "开盘价", "f18": "昨收"
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        df["最新价"] = pd.to_numeric(df["最新价"], errors="coerce")
        df["IOPV"] = pd.to_numeric(df["IOPV"], errors="coerce")
        if "成交额(元)" in df.columns:
            df["成交额(万元)"] = (pd.to_numeric(df["成交额(元)"], errors="coerce") / 10000).round(0)
        return df
    except Exception:
        return pd.DataFrame()

# ---------- 获取最新基金净值（cloudscraper）----------
def fetch_latest_nav(code):
    if code in st.session_state.nav_cache:
        return st.session_state.nav_cache[code]
    try:
        url = "https://api.fund.eastmoney.com/f10/lsjz"
        params = {"fundCode": code, "pageIndex": 1, "pageSize": 1}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://fundf10.eastmoney.com/",
        }
        resp = scraper.get(url, params=params, headers=headers, timeout=10)
        data = resp.json()
        if data.get("Data") and data["Data"].get("LSJZList"):
            nav = float(data["Data"]["LSJZList"][0]["DWJZ"])
            st.session_state.nav_cache[code] = nav
            return nav
    except:
        pass
    return None

# ---------- 申购状态（cloudscraper）----------
def fetch_status():
    try:
        url = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNNGSGStatus"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://m.fund.eastmoney.com/",
        }
        params = {
            "pageIndex": 1, "pageSize": 10000, "type": "",
            "deviceid": "android", "plat": "Android", "version": "6.8.0",
            "product": "EFund", "ServerIndex": "FundMNNGSGStatus",
            "appType": "android", "appVersion": "6.8.0"
        }
        resp = scraper.get(url, params=params, headers=headers, timeout=15)
        data = resp.json()
        if data.get("Data"):
            rows = []
            for item in data["Data"]:
                code = item.get("FCODE", "")
                status = item.get("RZSTS", "") or item.get("SGRZ", "") or item.get("SHGZ", "")
                rows.append({"代码": code, "申购状态": status if status else "未知"})
            return pd.DataFrame(rows)
    except:
        pass
    return pd.DataFrame()

# ---------- 主循环 ----------
placeholder = st.empty()

while True:
    trading = is_trading_time()
    try:
        df = fetch_lof_list()
        if df.empty:
            raise Exception("empty")
        if trading:
            df = df.dropna(subset=["最新价", "IOPV"])
            df = df[df["IOPV"] > 0]
            df["参考净值"] = df["IOPV"]
            df["净值来源"] = "IOPV"
        else:
            codes = df["代码"].dropna().tolist()
            nav_list = []
            for code in codes:
                nav = fetch_latest_nav(code)
                nav_list.append(nav)
                if len(nav_list) % 20 == 0:
                    _time.sleep(0.2)
            df["参考净值"] = nav_list
            df["净值来源"] = "基金净值"
            df = df.dropna(subset=["最新价", "参考净值"])
            df = df[df["参考净值"] > 0]

        df["溢价率(%)"] = ((df["最新价"] - df["参考净值"]) / df["参考净值"] * 100).round(2)
        st.session_state.cache = df
        st.session_state.cache_time = datetime.now().strftime("%H:%M:%S")
        error = False
    except Exception:
        df = st.session_state.cache
        error = True

    # 申购状态
    try:
        status_df = fetch_status()
        if not status_df.empty and "代码" in df.columns:
            df = df.merge(status_df, on="代码", how="left")
    except:
        pass
    if "申购状态" not in df.columns:
        df["申购状态"] = "未知"
    df["申购状态"] = df["申购状态"].fillna("未知")

    # 渲染
    with placeholder.container():
        col1, col2, col3 = st.columns(3)
        col1.metric("数据时间", st.session_state.cache_time)
        col2.metric("LOF数量", len(df))
        if not df.empty:
            col3.metric("最高溢价", f"{df['溢价率(%)'].max():.2f}%")

        if trading:
            st.success("🟢 实时 IOPV 溢价率")
        else:
            st.info("💡 当前非交易时段，使用最新基金净值计算溢价，仅供参考")
        if error:
            st.warning("⚠️ 实时获取失败，显示缓存数据")

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

            cols = [
                "代码", "简称", "最新价", "参考净值", "溢价率(%)",
                "涨跌幅", "成交量(手)", "成交额(万元)", "换手率(%)",
                "申购状态", "净值来源"
            ]
            avail = [c for c in cols if c in show.columns]

            st.dataframe(
                show[avail].style.format({
                    "最新价": "{:.3f}", "参考净值": "{:.3f}",
                    "溢价率(%)": "{:+.2f}%", "涨跌幅": "{:+.2f}%",
                    "换手率(%)": "{:.2f}%",
                    "成交额(万元)": "{:,.0f}",
                }),
                use_container_width=True, height=600, hide_index=True
            )

    if manual_refresh:
        st.rerun()
    jitter = random.uniform(-0.2 * refresh_sec, 0.2 * refresh_sec)
    _time.sleep(max(10, refresh_sec + jitter))
    st.rerun()
