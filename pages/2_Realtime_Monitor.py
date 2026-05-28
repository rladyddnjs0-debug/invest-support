import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Real-time Market Monitor", layout="wide")

def tradingview_widget(symbol, height=400, interval="5"):
    """TradingView Advanced Real-time Chart Widget"""
    widget_html = f"""
    <div class="tradingview-widget-container" style="height:{height}px;width:100%;">
      <div id="tv_chart_{symbol.replace(':', '_')}" style="height:{height}px;"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "autosize": true,
        "symbol": "{symbol}",
        "interval": "{interval}",
        "timezone": "Asia/Seoul",
        "theme": "dark",
        "style": "1",
        "locale": "kr",
        "toolbar_bg": "#f1f3f6",
        "enable_publishing": false,
        "hide_side_toolbar": false,
        "allow_symbol_change": true,
        "container_id": "tv_chart_{symbol.replace(':', '_')}"
      }});
      </script>
    </div>
    """
    components.html(widget_html, height=height)

st.title("🚀 실시간 마켓 모니터 (5분봉)")
st.markdown("TradingView 실시간 엔진을 활용한 초정밀 시장 모니터링 보드입니다.")

# --- 1섹션: 지수 선물 (Futures) ---
st.subheader("📊 주요 지수 선물")
col1, col2, col3 = st.columns(3)

with col1:
    st.info("나스닥 100 선물 (NQ)")
    tradingview_widget("CME_MINI:NQ1!", height=450)

with col2:
    st.info("S&P 500 선물 (ES)")
    tradingview_widget("CME_MINI:ES1!", height=450)

with col3:
    st.info("다우 30 선물 (YM)")
    tradingview_widget("CBOT:YM1!", height=450)

# --- 2섹션: 매크로 및 공포 지수 ---
st.markdown("---")
st.subheader("🌐 실시간 매크로 & 공포 지수")
col4, col5, col6 = st.columns(3)

with col4:
    st.warning("미국채 10년물 수익률 (10Y)")
    tradingview_widget("TVC:US10Y", height=400)

with col5:
    st.warning("미국채 2년물 수익률 (2Y)")
    tradingview_widget("TVC:US02Y", height=400)

with col6:
    st.error("변동성 지수 (VIX)")
    tradingview_widget("CBOE:VIX", height=400)

# --- 3섹션: 통화 및 원자재 ---
st.markdown("---")
st.subheader("💱 외환 및 핵심 지표")
col7, col8, col9 = st.columns(3)

with col7:
    st.success("원/달러 환율 (USDKRW)")
    tradingview_widget("FX_IDC:USDKRW", height=400)

with col8:
    st.success("달러 인덱스 (DXY)")
    tradingview_widget("TVC:DXY", height=400)

with col9:
    st.success("비트코인 (BTC/USD)")
    tradingview_widget("BINANCE:BTCUSDT", height=400)

st.sidebar.markdown("---")
if st.sidebar.button("🏠 홈으로 돌아가기", use_container_width=True):
    st.switch_page("app.py")

st.sidebar.info("""
**💡 모니터링 팁**
- 차트 상단의 인터벌을 눌러 분봉 단위를 변경할 수 있습니다.
- TradingView 실시간 데이터는 원본 시장 데이터와 0~15분 정도의 차이가 있을 수 있으나, 대부분의 지수 선물은 실시간에 가깝게 제공됩니다.
""")
