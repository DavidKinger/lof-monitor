import streamlit as st
import pandas as pd
import akshare as ak
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import time
import random

st.set_page_config(page_title="LOF溢价监控", layout="wide")
st.title("📈 LOF 溢价监控（新浪行情 + 天天基金净值）")

# ---------- 配置 ----------
PREMIUM_THRESHOLD = 3.0      # 溢价告警阈值（%）
DISCOUNT_THRESHOLD = 1.5     # 折价告警阈值（%）

# ---------- 侧边栏 ----------
with st.sidebar:
    st.header("⚙️ 设置")
    refresh_sec = st.number_input("刷新间隔（秒）", 10, 600, 30, 10)
    top_n = st.slider("显示前 N 只", 10, 100, 25, 5)
    purchase_filter = st.radio("申购状态", ["全部", "仅开放申购", "仅暂停申购"], index=0)
    manual_refresh = st.button("🔄 手动刷新")
    st.divider()
    st.info("💡 价格来自新浪 | 净值来自天天基金 | 交易状态来自东方财富")

# ---------- 缓存 ----------
if "cache" not in st.session_state:
    st.session_state.cache = pd.DataFrame()
    st.session_state.cache_time = "暂无"

# ---------- 溢价/折价计算 ----------
def calc_premium_discount(market_price, nav_price):
    if market_price is None or nav_price is None or market_price == 0 or nav_price == 0:
        return None, None
    premium = (market_price - nav_price) / nav_price * 100
    discount = (nav_price - market_price) / nav_price * 100
    if premium > 0:
        return round(premium, 2), None
    elif discount > 0:
        return None, round(discount, 2)
    else:
        return 0.0, 0.0

def get_status(premium_rate, discount_rate):
    if premium_rate and premium_rate >= PREMIUM_THRESHOLD:
        return 'premium_alert'
    elif discount_rate and discount_rate >= DISCOUNT_THRESHOLD:
        return 'discount_alert'
    elif premium_rate and premium_rate > 0:
        return 'premium'
    elif discount_rate and discount_rate > 0:
        return 'discount'
    else:
        return 'normal'

# ---------- 数据获取 ----------
@st.cache_data(ttl=60)
def fetch_lof_list_sina():
    """从新浪获取 LOF 基金列表及实时价格"""
    try:
        raw = ak.fund_etf_category_sina(symbol="LOF基金")
        records = []
        for _, row in raw.iterrows():
            code_with = row['代码']
            if code_with.startswith('sz'):
                market = 'sz'
                code = code_with[2:]
            elif code_with.startswith('sh'):
                market = 'sh'
                code = code_with[2:]
            else:
                market = ''
                code = code_with
            try:
                price = float(row['最新价']) if pd.notna(row['最新价']) else None
            except (ValueError, TypeError):
                price = None
            records.append({
                'code': code,
                'name': row['名称'],
                'market': market,
                'market_price': price
            })
        df = pd.DataFrame(records)
        df = df[df['market_price'].notna() & (df['market_price'] > 0)]
        return df
    except Exception as e:
        st.error(f"获取LOF列表失败: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=120)
def fetch_all_fund_nav():
    """获取全市场基金最新净值（天天基金）"""
    try:
        nav_df = ak.fund_open_fund_daily_em()
        return nav_df
    except Exception as e:
        st.error(f"获取净值数据失败: {e}")
        return pd.DataFrame()

def get_latest_nav_value(fund_code, nav_df):
    """从净值DataFrame中提取指定基金最新净值"""
    row = nav_df[nav_df['基金代码'].astype(str) == str(fund_code)]
    if row.empty:
        return None, None
    row_data = row.iloc[0]
    nav_cols = [c for c in nav_df.columns if '单位净值' in c]
    nav_cols.sort(reverse=True)
    for col in nav_cols:
        val = row_data[col]
        if pd.notnull(val) and str(val).strip() not in ['', '-']:
            try:
                return float(val), col.split('-单位净值')[0]
            except ValueError:
                continue
    return None, None

def parse_trade_state(code):
    """从东方财富页面获取交易状态"""
    try:
        url = f"https://fund.eastmoney.com/{code}.html"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        resp.encoding = resp.apparent_encoding
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for item in soup.find_all("div", class_="staticItem"):
                if "交易状态" in item.text:
                    return item.get_text(strip=True).replace("交易状态：", "")
    except:
        pass
    return "未知"

# ---------- 主循环 ----------
placeholder = st.empty()

while True:
    start_time = time.time()
    try:
        # 获取行情列表
        fund_df = fetch_lof_list_sina()
        if fund_df.empty:
            raise Exception("LOF列表为空")

        # 获取净值
        nav_df = fetch_all_fund_nav()
        if nav_df.empty:
            raise Exception("净值数据为空")

        # 筛选有效代码
        valid_codes = set(fund_df['code'].astype(str))
        nav_df = nav_df[nav_df['基金代码'].astype(str).isin(valid_codes)]

        # 合并数据
        data = []
        for _, row in fund_df.iterrows():
            code = row['code']
            name = row['name']
            market_price = row['market_price']
            nav_price, nav_date = get_latest_nav_value(code, nav_df)
            if nav_price is None:
                continue
            data.append({
                'code': code,
                'name': name,
                'market_price': market_price,
                'nav_price': nav_price,
                'nav_date': nav_date or '--',
            })

        df = pd.DataFrame(data)
        if df.empty:
            raise Exception("没有有效的净值数据")

        # 计算溢价/折价
        premiums, discounts, statuses = [], [], []
        for _, r in df.iterrows():
            p, d = calc_premium_discount(r['market_price'], r['nav_price'])
            premiums.append(p)
            discounts.append(d)
            statuses.append(get_status(p, d))
        df['溢价率(%)'] = premiums
        df['折价率(%)'] = discounts
        df['状态'] = statuses

        # 获取交易状态（分批，避免请求太快）
        states = {}
        for code in df['code'].unique():
            states[code] = parse_trade_state(code)
            time.sleep(0.2)
        df['申购状态'] = df['code'].map(states)

        # 缓存
        st.session_state.cache = df
        st.session_state.cache_time = datetime.now().strftime("%H:%M:%S")
        error = False

    except Exception as e:
        st.error(f"数据获取异常: {e}")
        df = st.session_state.cache
        error = True

    # 渲染
    with placeholder.container():
        col1, col2, col3 = st.columns(3)
        col1.metric("数据时间", st.session_state.cache_time)
        col2.metric("LOF数量", len(df))
        if not df.empty:
            max_prem = df['溢价率(%)'].max()
            max_disc = df['折价率(%)'].max()
            if pd.notna(max_prem):
                col3.metric("最高溢价", f"{max_prem:.2f}%")
            elif pd.notna(max_disc):
                col3.metric("最高折价", f"{max_disc:.2f}%")
            else:
                col3.metric("最高溢价", "0%")

        if error:
            st.warning("⚠️ 显示的是缓存数据")

        if df.empty:
            st.info("暂无数据")
        else:
            # 筛选申购状态
            if purchase_filter == "仅开放申购":
                show = df[df["申购状态"].str.contains("开放", na=False)]
            elif purchase_filter == "仅暂停申购":
                show = df[df["申购状态"].str.contains("暂停", na=False)]
            else:
                show = df

            # 排序
            sort_col = "溢价率(%)" if show["溢价率(%)"].notna().any() else "折价率(%)"
            show = show.sort_values(sort_col, ascending=False, na_position='last').head(top_n)

            # 列定义
            cols = [
                "code", "name", "market_price", "nav_price", "溢价率(%)", "折价率(%)",
                "状态", "申购状态"
            ]
            avail = [c for c in cols if c in show.columns]

            # 状态颜色
            def color_status(val):
                if val == 'premium_alert':
                    return 'background-color: #ffcccc; font-weight: bold'
                elif val == 'discount_alert':
                    return 'background-color: #ccffcc; font-weight: bold'
                elif val == 'premium':
                    return 'background-color: #ffe0e0'
                elif val == 'discount':
                    return 'background-color: #e0ffe0'
                return ''

            formatted = show[avail].style.format({
                "market_price": "{:.4f}",
                "nav_price": "{:.4f}",
                "溢价率(%)": "{:+.2f}%",
                "折价率(%)": "{:+.2f}%",
            }, na_rep="N/A").applymap(color_status, subset=["状态"])

            st.dataframe(formatted, use_container_width=True, height=600, hide_index=True)

    if manual_refresh:
        st.rerun()

    # 等待下次刷新
    elapsed = time.time() - start_time
    sleep_time = max(1, refresh_sec - elapsed)
    time.sleep(sleep_time)
    st.rerun()
