import streamlit as st
import pandas as pd
import akshare as ak
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import time
import random

st.set_page_config(page_title="LOF溢价监控", layout="wide")
st.title("📈 LOF 溢价监控")

# ---------- 配置 ----------
PREMIUM_THRESHOLD = 3.0      # 溢价告警阈值（%）
DISCOUNT_THRESHOLD = 1.5     # 折价告警阈值（用于状态判断，但不展示折价率）

# ---------- 侧边栏 ----------
with st.sidebar:
    st.header("设置")
    refresh_sec = st.number_input("刷新间隔（秒）", 10, 600, 30, 10)
    top_n = st.slider("显示前 N 只", 10, 100, 25, 5)
    purchase_filter = st.radio("申购状态", ["全部", "仅开放申购", "仅暂停申购"], index=0)
    manual_refresh = st.button("手动刷新")

# ---------- 计算函数 ----------
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

# ---------- 申购状态缓存 ----------
if "trade_status_cache" not in st.session_state:
    st.session_state.trade_status_cache = {}

def get_trade_status(code):
    """从东方财富页面抓取交易状态，带缓存"""
    if code in st.session_state.trade_status_cache:
        return st.session_state.trade_status_cache[code]
    try:
        url = f"https://fund.eastmoney.com/{code}.html"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        resp.encoding = resp.apparent_encoding
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for item in soup.find_all("div", class_="staticItem"):
                if "交易状态" in item.text:
                    status = item.get_text(strip=True).replace("交易状态：", "")
                    st.session_state.trade_status_cache[code] = status
                    return status
    except:
        pass
    st.session_state.trade_status_cache[code] = "未知"
    return "未知"

# ---------- 数据加载 ----------
@st.cache_data(ttl=120)
def load_data():
    msgs = []
    # 1. 新浪 LOF 列表（包含实时行情）
    try:
        raw = ak.fund_etf_category_sina(symbol="LOF基金")
        msgs.append(f"新浪行情获取成功：{len(raw)} 条")
    except Exception as e:
        return None, [f"新浪行情获取失败: {e}"]

    # 2. 天天基金净值
    try:
        nav_df = ak.fund_open_fund_daily_em()
        msgs.append(f"天天净值获取成功：{len(nav_df)} 条")
    except Exception as e:
        return None, [f"净值获取失败: {e}"]

    records = []
    for _, row in raw.iterrows():
        code_with = row['代码']
        code = code_with[2:] if code_with.startswith(('sz','sh')) else code_with

        # 最新价
        try:
            price = float(row['最新价']) if pd.notna(row['最新价']) else None
        except:
            price = None
        if price is None or price <= 0:
            continue

        # 涨跌幅（新浪字段名可能是“涨跌幅”）
        change_pct = row.get('涨跌幅', None)
        try:
            change_pct = float(change_pct) if pd.notna(change_pct) else None
        except:
            change_pct = None

        # 成交量（新浪字段名可能是“成交量”）
        volume = row.get('成交量', None)
        try:
            volume = float(volume) if pd.notna(volume) else None
        except:
            volume = None

        # 成交额（元）
        amount = row.get('成交额', None)
        try:
            amount = float(amount) if pd.notna(amount) else None
        except:
            amount = None
        amount_wan = round(amount / 10000, 2) if amount else None

        # 净值
        nav_row = nav_df[nav_df['基金代码'].astype(str) == str(code)]
        if nav_row.empty:
            continue
        nav_data = nav_row.iloc[0]
        nav_cols = [c for c in nav_df.columns if '单位净值' in c]
        nav_cols.sort(reverse=True)
        nav_price = None
        for col in nav_cols:
            val = nav_data[col]
            if pd.notnull(val) and str(val).strip() not in ['', '-']:
                try:
                    nav_price = float(val)
                    break
                except ValueError:
                    continue
        if nav_price is None:
            continue

        records.append({
            'code': code,
            'name': row['名称'],
            'market_price': price,
            'nav_price': nav_price,
            'change_pct': change_pct,
            'volume': volume,
            'amount_wan': amount_wan,
        })

    if not records:
        return None, msgs + ["无有效基金（净值缺失）"]

    df = pd.DataFrame(records)

    # 计算溢价率（不再保留折价率显示，但参与状态判断）
    premiums, discounts, statuses = [], [], []
    for _, r in df.iterrows():
        p, d = calc_premium_discount(r['market_price'], r['nav_price'])
        premiums.append(p)
        discounts.append(d)
        statuses.append(get_status(p, d))
    df['溢价率(%)'] = premiums
    # 折价率仅用于状态判断，不输出到最终表格
    df['状态'] = statuses

    # 申购状态（顺序抓取，带缓存）
    for idx, code in enumerate(df['code']):
        df.at[idx, '申购状态'] = get_trade_status(code)
        time.sleep(0.15)  # 控制频率，避免被封

    return df, msgs

# ---------- 主界面 ----------
placeholder = st.empty()

while True:
    df, msgs = load_data()
    with placeholder.container():
        for m in msgs:
            st.caption(m)

        if df is None or df.empty:
            st.error("暂无有效数据")
        else:
            col1, col2, col3 = st.columns(3)
            col1.metric("LOF数量", len(df))
            max_p = df['溢价率(%)'].max()
            if pd.notna(max_p):
                col2.metric("最高溢价", f"{max_p:.2f}%")
            # 折价率不再显示，但可以提示最高折价状态
            discount_alert_count = len(df[df['状态'] == 'discount_alert'])
            if discount_alert_count > 0:
                col3.metric("折价告警", f"{discount_alert_count} 只")

            # 筛选申购状态
            if purchase_filter == "仅开放申购":
                show = df[df["申购状态"].str.contains("开放|限制大额", na=False)]
            elif purchase_filter == "仅暂停申购":
                show = df[df["申购状态"].str.contains("暂停", na=False)]
            else:
                show = df

            # 排序：溢价率降序（折价告警的也会正常排序，但折价告警本身溢价率为None，会被排到最后）
            show = show.sort_values('溢价率(%)', ascending=False, na_position='last').head(top_n)

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

            # 显示列（去掉折价率）
            display_cols = [
                'code', 'name', 'market_price', 'nav_price', '溢价率(%)',
                'change_pct', 'volume', 'amount_wan', '申购状态', '状态'
            ]
            avail = [c for c in display_cols if c in show.columns]

            styled = show[avail].style \
                .format({
                    'market_price': '{:.4f}',
                    'nav_price': '{:.4f}',
                    '溢价率(%)': '{:+.2f}%',
                    'change_pct': '{:+.2f}%',
                    'volume': '{:,.0f}',
                    'amount_wan': '{:,.2f}',
                }, na_rep="N/A") \
                .map(color_status, subset=['状态'])

            st.dataframe(styled, use_container_width=True, height=600, hide_index=True)

    if manual_refresh:
        st.rerun()
    time.sleep(max(5, refresh_sec))
    st.rerun()
