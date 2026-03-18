import time
import platform
import datetime
import pandas as pd
import streamlit as st
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

# ── 設定 ──────────────────────────────────────────────
DATE_START   = datetime.date(2026, 3, 18)
DATE_END     = datetime.date(2026, 11, 1)
REFRESH_SEC  = 300   # 5 分鐘
ROUTES = [
    {"origin": "RMQ", "origin_name": "台中", "dest": "KIX", "dest_name": "大阪"},
    {"origin": "TPE", "origin_name": "桃園", "dest": "KIX", "dest_name": "大阪"},
]
# ──────────────────────────────────────────────────────


def init_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=zh-TW")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/120.0.0.0 Safari/537.36")

    if platform.system() == "Linux":
        import shutil
        chrome_bin = shutil.which("chromium") or shutil.which("chromium-browser") or "/usr/bin/chromium"
        driver_bin = shutil.which("chromedriver") or "/usr/bin/chromedriver"
        options.binary_location = chrome_bin
        from selenium.webdriver.chrome.service import Service
        driver = webdriver.Chrome(service=Service(driver_bin), options=options)
    else:
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return driver


def scrape_flights(driver, origin, dest, date_str, status_text):
    """抓取單一日期、單一航線的所有班次與票價"""
    url = (
        f"https://www.starlux-airlines.com/zh-TW/booking/book-flight/search-a-flight"
        f"?origin={origin}&destination={dest}&departDate={date_str}&tripType=OW&adult=1&child=0&infant=0"
    )
    status_text(f"  載入 {origin}→{dest} {date_str}...")
    driver.get(url)
    time.sleep(5)

    wait = WebDriverWait(driver, 20)
    flights = []

    try:
        # 等待班機清單載入
        wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "[class*='flight-list'], [class*='flightList'], [class*='flight-card'], [class*='flightCard']")
        ))
        time.sleep(2)

        # 抓取所有班機卡片
        cards = driver.find_elements(By.CSS_SELECTOR,
            "[class*='flight-card'], [class*='flightCard'], [class*='flight-item'], [class*='flightItem']"
        )

        for card in cards:
            try:
                # 出發時間
                dep_els = card.find_elements(By.CSS_SELECTOR,
                    "[class*='depart-time'], [class*='departTime'], [class*='departure-time']"
                )
                dep_time = dep_els[0].text.strip() if dep_els else ""

                # 抵達時間
                arr_els = card.find_elements(By.CSS_SELECTOR,
                    "[class*='arrive-time'], [class*='arriveTime'], [class*='arrival-time']"
                )
                arr_time = arr_els[0].text.strip() if arr_els else ""

                # 飛行時間
                dur_els = card.find_elements(By.CSS_SELECTOR,
                    "[class*='duration'], [class*='flight-time']"
                )
                duration = dur_els[0].text.strip() if dur_els else ""

                # 班機號碼
                fnum_els = card.find_elements(By.CSS_SELECTOR,
                    "[class*='flight-number'], [class*='flightNumber']"
                )
                flight_no = fnum_els[0].text.strip() if fnum_els else ""

                # 票價（抓最低價）
                price_els = card.find_elements(By.CSS_SELECTOR,
                    "[class*='price'], [class*='fare'], [class*='amount']"
                )
                prices = []
                for p in price_els:
                    txt = p.text.strip().replace(",", "").replace("NT$", "").replace("$", "").replace("TWD", "").strip()
                    try:
                        prices.append(int(txt))
                    except ValueError:
                        pass
                min_price = min(prices) if prices else None

                if dep_time:
                    flights.append({
                        "日期":     date_str,
                        "航線":     f"{origin}→{dest}",
                        "班機":     flight_no,
                        "出發":     dep_time,
                        "抵達":     arr_time,
                        "飛行時間": duration,
                        "最低票價(TWD)": min_price,
                    })
            except Exception:
                continue

    except Exception as e:
        status_text(f"  {origin}→{dest} {date_str} 無班次或載入失敗：{e}")

    return flights


def run_scrape(selected_dates, status_text, progress_bar):
    driver = init_driver()
    all_flights = []
    total = len(selected_dates) * len(ROUTES)
    done = 0

    try:
        for route in ROUTES:
            for d in selected_dates:
                date_str = d.strftime("%Y-%m-%d")
                flights = scrape_flights(driver, route["origin"], route["dest"], date_str, status_text)
                all_flights.extend(flights)
                done += 1
                progress_bar.progress(done / total)
    finally:
        driver.quit()

    return all_flights


# ── Streamlit UI ───────────────────────────────────────
st.set_page_config(
    page_title="星宇航空 台中/桃園→大阪 票價查詢",
    page_icon="✈️",
    layout="wide"
)

st.title("✈️ 星宇航空｜台中・桃園 → 大阪 班次票價即時查詢")
st.caption("每 5 分鐘自動更新，低價優先排序")

# 初始化 session state
if "last_update" not in st.session_state:
    st.session_state.last_update = None
if "df" not in st.session_state:
    st.session_state.df = None

# ── 側邊欄設定 ──
with st.sidebar:
    st.header("查詢設定")

    route_options = ["全部", "台中(RMQ)→大阪(KIX)", "桃園(TPE)→大阪(KIX)"]
    selected_route = st.selectbox("航線", route_options)

    date_from = st.date_input("起始日期", value=DATE_START, min_value=DATE_START, max_value=DATE_END)
    date_to   = st.date_input("結束日期", value=min(DATE_START + datetime.timedelta(days=6), DATE_END),
                               min_value=DATE_START, max_value=DATE_END)

    max_price = st.number_input("最高票價篩選（TWD，0=不限）", min_value=0, value=0, step=500)

    run_btn = st.button("立即查詢", type="primary", use_container_width=True)

# ── 主畫面 ──
col1, col2 = st.columns([3, 1])
with col2:
    if st.session_state.last_update:
        st.info(f"上次更新：{st.session_state.last_update.strftime('%H:%M:%S')}")

if run_btn:
    if date_from > date_to:
        st.error("起始日期不能晚於結束日期")
    else:
        # 產生日期清單
        delta = (date_to - date_from).days + 1
        selected_dates = [date_from + datetime.timedelta(days=i) for i in range(delta)]

        # 根據航線篩選 ROUTES
        routes_to_scrape = ROUTES
        if selected_route == "台中(RMQ)→大阪(KIX)":
            routes_to_scrape = [r for r in ROUTES if r["origin"] == "RMQ"]
        elif selected_route == "桃園(TPE)→大阪(KIX)":
            routes_to_scrape = [r for r in ROUTES if r["origin"] == "TPE"]

        with st.status("爬取中...", expanded=True) as status:
            progress = st.progress(0)
            status_text = st.empty()

            all_flights = []
            driver = init_driver()
            total = len(selected_dates) * len(routes_to_scrape)
            done = 0

            try:
                for route in routes_to_scrape:
                    for d in selected_dates:
                        date_str = d.strftime("%Y-%m-%d")
                        flights = scrape_flights(driver, route["origin"], route["dest"], date_str, status_text.text)
                        all_flights.extend(flights)
                        done += 1
                        progress.progress(done / total)
            finally:
                driver.quit()

            status.update(label=f"完成！共找到 {len(all_flights)} 筆班次", state="complete")

        st.session_state.last_update = datetime.datetime.now()

        if all_flights:
            df = pd.DataFrame(all_flights)
            # 票價排序
            df = df.sort_values("最低票價(TWD)", ascending=True, na_position="last")
            # 篩選最高票價
            if max_price > 0:
                df = df[df["最低票價(TWD)"] <= max_price]
            st.session_state.df = df
        else:
            st.session_state.df = pd.DataFrame()

# ── 顯示結果 ──
if st.session_state.df is not None:
    df = st.session_state.df
    if df.empty:
        st.warning("查無班次資料，可能是網站介面有變動，請稍後再試。")
    else:
        st.success(f"共 {len(df)} 筆班次（低價優先）")
        st.dataframe(df, use_container_width=True, hide_index=True)

        csv = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button("下載 CSV", data=csv, file_name="starlux_flights.csv", mime="text/csv")

        # 票價統計
        with st.expander("票價統計"):
            col1, col2, col3 = st.columns(3)
            col1.metric("最低票價", f"NT$ {int(df['最低票價(TWD)'].min()):,}" if df['最低票價(TWD)'].notna().any() else "N/A")
            col2.metric("平均票價", f"NT$ {int(df['最低票價(TWD)'].mean()):,}" if df['最低票價(TWD)'].notna().any() else "N/A")
            col3.metric("班次總數", len(df))

# ── 5 分鐘自動重新整理 ──
if st.session_state.last_update:
    elapsed = (datetime.datetime.now() - st.session_state.last_update).seconds
    remaining = REFRESH_SEC - elapsed
    if remaining <= 0:
        st.rerun()
    else:
        st.caption(f"下次自動更新倒數：{remaining // 60} 分 {remaining % 60} 秒")
        time.sleep(1)
        st.rerun()
