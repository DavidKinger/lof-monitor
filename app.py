import streamlit as st
import pandas as pd
import akshare as ak
from datetime import datetime
import time

st.set_page_config(page_title="LOF溢价监控", layout="wide")
st.title("📈 LOF 溢价监控")

PREMIUM_THRESHOLD = 3.0
DISCOUNT_THRESHOLD = 1.5

with st.sidebar:
    st.header("设置")
    refresh_sec = st.number_input("刷新间隔（秒）", 10, 600, 30, 10)
    top_n = st.slider("显示前 N 只", 10, 100, 25, 5)
    purchase_filter = st.radio("申购状态", ["全部", "仅开放申购", "仅暂停申购"], index=0)
    manual_refresh = st.button("手动刷新")

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

@st.cache_data(ttl=600)
def get_purchase_status_df():
    try:
        df = ak.fund_purchase_em()
        df = df.rename(columns={"基金代码": "code", "申购状态": "申购状态"})
        return df[["code", "申购状态"]]
    except:
        return pd.DataFrame()

@st.cache_data(ttl=120)
def load_data():
    msgs = []
    try:
        raw = ak.fund_etf_category_sina(symbol="LOF基金")
        msgs.append(f"新浪行情获取成功：{len(raw)} 条")
    except Exception as e:
        return None, [f"新浪行情获取失败: {e}"]

    try:
        nav_df = ak.fund_open_fund_daily_em()
        msgs.append(f"天天净值获取成功：{len(nav_df)} 条")
    except Exception as e:
        return None, [f"净值获取失败: {e}"]

    status_df = get_purchase_status_df()

    records = []
    for _, row in raw.iterrows():
        code_with = row['代码']
        code = code_with[2:] if code_with.startswith(('sz','sh')) else code_with

        try:
            price = float(row['最新价']) if pd.notna(row['最新价']) else None
        except:
            price = None
        if price is None or price <= 0:
            continue

        change_pct = row.get('涨跌幅', None)
        try:
            change_pct = float(change_pct) if pd.notna(change_pct) else None
        except:
            change_pct = None

        volume = row.get('成交量', None)
        try:
            volume = float(volume) if pd.notna(volume) else None
        except:
            volume = None

        amount = row.get('成交额', None)
        try:
            amount = float(amount) if pd.notna(amount) else None
        except:
            amount = None
        amount_wan = round(amount / 10000, 2) if amount else None

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

    premiums, discounts, statuses = [], [], []
    for _, r in df.iterrows():
        p, d = calc_premium_discount(r['market_price'], r['nav_price'])
        premiums.append(p)
        discounts.append(d)
        statuses.append(get_status(p, d))
    df['溢价率(%)'] = premiums
    df['状态'] = statuses

    if not status_df.empty:
        df['code'] = df['code'].astype(str)
        status_df['code'] = status_df['code'].astype(str)
        df = df.merge(status_df, on='code', how='left')
    else:
        df['申购状态'] = '未知'
    df['申购状态'] = df['申购状态'].fillna('未知')

    return df, msgs

# ---------- 中文列名映射 ----------
CN_COL_MAP = {
    'code': '基金代码',
    'name': '基金名称',
    'market_price': '场内价格',
    'nav_price': '基金净值',
    '溢价率(%)': '溢价率(%)',
    'change_pct': '涨跌幅(%)',
    'volume': '成交量(手)',
    'amount_wan': '成交额(万元)',
    '申购状态': '申购状态',
    '状态': '状态',
}

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

            if purchase_filter == "仅开放申购":
                show = df[df["申购状态"].str.contains("开放|限制大额", na=False)]
            elif purchase_filter == "仅暂停申购":
                show = df[df["申购状态"].str.contains("暂停", na=False)]
            else:
                show = df

            show = show.sort_values('溢价率(%)', ascending=False, na_position='last').head(top_n)

            # 重命名为中文列名（只保留需要的列）
            show = show.rename(columns=CN_COL_MAP)
            display_cols = [
                '基金代码', '基金名称', '场内价格', '基金净值', '溢价率(%)',
                '涨跌幅(%)', '成交量(手)', '成交额(万元)', '申购状态', '状态'
            ]
            avail = [c for c in display_cols if c in show.columns]

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

            styled = show[avail].style \
                .format({
                    '场内价格': '{:.4f}',
                    '基金净值': '{:.4f}',
                    '溢价率(%)': '{:+.2f}%',
                    '涨跌幅(%)': '{:+.2f}%',
                    '成交量(手)': '{:,.0f}',
                    '成交额(万元)': '{:,.2f}',
                }, na_rep="N/A") \
                .map(color_status, subset=['状态'])

            st.dataframe(styled, use_container_width=True, height=600, hide_index=True)

    if manual_refresh:
        st.rerun()
    time.sleep(max(5, refresh_sec))
    st.rerun()
