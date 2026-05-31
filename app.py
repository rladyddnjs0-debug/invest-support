import streamlit as st
import pandas as pd
import numpy as np
import os
import plotly.graph_objects as go
import plotly.express as px
from modules.data_loader import DataLoader
from modules.models import AnalysisModel, QuantScreener
from modules.ai_reporter import AIReporter
from modules.backtester import QuantBacktester
from datetime import datetime
from dotenv import load_dotenv
from modules.config import settings
from modules.logger import logger

# 환경 변수 로드
load_dotenv()

# 페이지 설정
st.set_page_config(page_title="Invest Support Dashboard", layout="wide")

# 인스턴스 초기화
loader = DataLoader()
engine = AnalysisModel()
reporter = AIReporter()
screener = QuantScreener()
backtester = QuantBacktester(loader)

# --- 유틸리티 함수 ---
import streamlit.components.v1 as components

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

# --- 상세 분석 팝업 함수 ---
@st.dialog("📊 종목 상세 분석", width="large")
def show_stock_details(ticker):
    """
    종목 상세 분석 팝업. 
    내부에 @st.fragment를 사용하여 하위 분석 버튼 클릭 시 팝업이 닫히지 않도록 설계함.
    """
    st.write(f"### {ticker} 상세 리서치")
    
    # 1. TradingView 심볼 매핑 (캐시)
    if f"tv_symbol_{ticker}" not in st.session_state:
        tv_symbol = ticker
        if ".KS" in ticker or ".KQ" in ticker:
            tv_symbol = ticker.replace(".KS", "").replace(".KQ", "")
        else:
            try:
                import yfinance as yf
                stock_info = yf.Ticker(ticker).fast_info
                exchange = stock_info.exchange
                clean_ticker = ticker.replace("-", ".")
                if exchange == "NYQ": tv_symbol = f"NYSE:{clean_ticker}"
                elif exchange in ["NMS", "NGM", "NCM"]: tv_symbol = f"NASDAQ:{clean_ticker}"
                elif exchange == "ASE": tv_symbol = f"AMEX:{clean_ticker}"
                elif exchange == "PCX": tv_symbol = f"ARCA:{clean_ticker}"
                else: tv_symbol = clean_ticker
            except Exception as e:
                logger.debug(f"TradingView symbol resolution failed for {ticker}: {e}")
                tv_symbol = f"NASDAQ:{ticker.replace('-', '.')}"
        st.session_state[f"tv_symbol_{ticker}"] = tv_symbol
    
    tv_symbol = st.session_state[f"tv_symbol_{ticker}"]

    # TradingView 위젯
    tv_id = f"tv_chart_{ticker.replace('.', '_').replace('-', '_')}"
    tv_html = f"""
    <div class="tradingview-widget-container" style="height:600px;width:100%;">
      <div id="{tv_id}" style="height:600px;"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "autosize": true, "symbol": "{tv_symbol}", "interval": "W", "timezone": "Asia/Seoul",
        "theme": "dark", "style": "1", "locale": "kr", "toolbar_bg": "#f1f3f6",
        "enable_publishing": false, "allow_symbol_change": true, "container_id": "{tv_id}",
        "studies": ["MASimple@tv-basicstudies", "BB@tv-basicstudies"],
        "studies_overrides": {{"moving average.length": 120, "moving average.precision": 2}}
      }});
      </script>
    </div>
    """
    import streamlit.components.v1 as components
    st.subheader("📈 실시간 기술적 분석 (TradingView)")
    components.html(tv_html, height=600)
    st.markdown("---")

    # 세션 상태 초기화 (팝업 내 데이터 유지용)
    if f"lppl_{ticker}" not in st.session_state: st.session_state[f"lppl_{ticker}"] = None
    if f"news_{ticker}" not in st.session_state: st.session_state[f"news_{ticker}"] = None
    if f"ai_report_{ticker}" not in st.session_state: st.session_state[f"ai_report_{ticker}"] = None

    # 데이터 로드
    data = loader.get_market_history(ticker, period="2y")
    if data is None or data.empty:
        st.error("데이터를 가져올 수 없습니다.")
        if st.button("닫기"):
            st.session_state.active_ticker = None
            st.rerun()
        return

    prices = data['Close']

    # --- 분석 구역 (Fragment로 감싸서 부분 리렌더링 지원) ---
    @st.fragment
    def render_analysis_section(key=None):
        lppl_res = st.session_state[f"lppl_{ticker}"]
        
        col_chart, col_side = st.columns([2, 1])
        with col_chart:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=prices.index, y=prices.values, mode='lines', name='Price', line=dict(color='white')))
            if lppl_res and 'fitted' in lppl_res:
                all_dates = pd.date_range(start=prices.index[0], periods=len(lppl_res['fitted']), freq='D')
                fig.add_trace(go.Scatter(x=all_dates, y=lppl_res['fitted'], mode='lines', name='LPPL Fit', line=dict(color='cyan', dash='dot')))
                if 'tc_date' in lppl_res:
                    fig.add_vline(x=lppl_res['tc_date'], line_width=1, line_dash="dash", line_color="red")
                y_min, y_max = prices.min() * 0.8, prices.max() * 1.2
                fig.update_yaxes(range=[y_min, y_max])
            fig.update_layout(template="plotly_dark", height=400, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        
        with col_side:
            st.write("#### 🛡️ LPPL 리스크 진단")
            if lppl_res:
                st.metric("위험 점수", f"{lppl_res['danger_score']:.2f} / 100")
                if 'tc_date' in lppl_res:
                    st.metric("예상 임계점(Tc)", lppl_res['tc_date'].strftime('%Y-%m-%d'))
                else:
                    st.info("패턴 미감지로 임계점 산출 불가")
                status = "🚨 위험" if lppl_res['danger_score'] >= settings.lppl.bubble_threshold else "⚠️ 경계" if lppl_res['danger_score'] >= settings.lppl.warning_threshold else "✅ 정상"
                st.info(f"상태: **{status}**")
            
            if st.button("🔍 LPPL 정밀 분석 실행", width="stretch", type="primary"):
                with st.spinner('계산 중...'):
                    st.session_state[f"lppl_{ticker}"] = engine.run_lppl_fit(prices)
                    st.rerun() # Fragment만 리런

            # --- Milestone 01: 펀더멘털 시나리오 분석 ---
            st.markdown("---")
            st.write("#### 💎 펀더멘털 가치 평가")
            
            # 관심 종목에 대한 시나리오 계산
            fund_df = loader.get_stock_fundamentals([ticker], market_name="us" if ".KS" not in ticker and ".KQ" not in ticker else "kr")
            if not fund_df.empty:
                row = fund_df.iloc[0]
                fwd_eps = row.get('ForwardEPS', 0)
                curr_price = row.get('Price', 0)
                
                scenarios = engine.calculate_valuation_scenarios(ticker, fwd_eps, curr_price)
                if scenarios:
                    s = scenarios['scenarios']
                    pos = scenarios['position_pct']
                    
                    st.write(f"**현재 위치: {pos:.1f}% (Bear ↔ Bull)**")
                    # 프로그레스 바 형태로 위치 시각화
                    st.progress(pos / 100.0)
                    
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Bear", f"{s['bear']:,.1f}")
                    c2.metric("Base", f"{s['base']:,.1f}")
                    c3.metric("Bull", f"{s['bull']:,.1f}")
                    
                    st.caption(f"12M Forward EPS: {fwd_eps:,.2f} 기준")
                    
                    if curr_price <= s['bear']:
                        st.success("🎯 **매수 기회:** 주가가 Bear Case 이하로 저평가 상태입니다.")
                    elif curr_price >= s['bull']:
                        st.error("🚫 **매수 금지:** 주가가 Bull Case 이상으로 고평가 상태입니다.")
                else:
                    st.info("해당 종목의 밸류에이션 매트릭스 정보가 없습니다.")
            else:
                st.info("재무 데이터를 불러올 수 없습니다.")

        st.markdown("---")
        # 뉴스 섹션
        st.subheader("📰 최근 소식 및 AI 분석")
        if st.session_state[f"news_{ticker}"]:
            st.markdown(st.session_state[f"news_{ticker}"])
        
        if st.button(f"{ticker} 최신 뉴스 분석", width="stretch"):
            with st.spinner('뉴스 수집 및 분석 중...'):
                import yfinance as yf
                news = yf.Ticker(ticker).news
                if news:
                    news_text = ""
                    for item in news[:5]:
                        c = item.get('content', item)
                        t_str = c.get('title', '제목 없음').replace("[", "(").replace("]", ")")
                        l = c.get('canonicalUrl', {}).get('url', '#')
                        p = c.get('provider', {}).get('displayName', 'N/A')
                        news_text += f"- **[{t_str}]({l})** ({p})\n"
                    
                    if reporter.model:
                        try:
                            prompt = f"다음 뉴스들을 분석하여 투자 영향을 한국어로 요약하라:\n" + "\n".join([n.get('content', n).get('title', '') for n in news[:5]])
                            summary = reporter.model.generate_content(prompt).text
                            news_text += f"\n---\n#### 💡 AI 인사이트\n{summary}"
                        except Exception as e:
                            logger.error(f"AI News summary generation failed: {e}")
                    st.session_state[f"news_{ticker}"] = news_text
                    st.rerun() # Fragment 리런

        st.markdown("---")
        # AI 리포트
        if st.session_state[f"ai_report_{ticker}"]:
            st.info("🤖 AI 종합 전략 리포트")
            st.markdown(st.session_state[f"ai_report_{ticker}"])
        
        if reporter.model:
            if st.button(f"🤖 AI 종합 전략 리포트 생성", width="stretch"):
                with st.spinner('생성 중...'):
                    l_res = st.session_state[f"lppl_{ticker}"]
                    prompt = f"{ticker}의 최근 가격 흐름과 LPPL 위험 점수({l_res['danger_score'] if l_res else 'N/A'})를 바탕으로 투자 의견을 요약하라."
                    try:
                        st.session_state[f"ai_report_{ticker}"] = reporter.model.generate_content(prompt).text
                        st.rerun() # Fragment 리런
                    except Exception as e:
                        logger.error(f"AI Report generation failed: {e}")
        else:
            st.info("🤖 AI 전략 리포트 기능은 준비 중입니다.")

    # 분석 섹션 렌더링 (티커별 고유 키 부여하여 강제 갱신)
    render_analysis_section(key=f"analysis_{ticker.replace('.', '_')}")

    st.markdown("---")
    if st.button("🚪 분석 종료 및 닫기", width="stretch"):
        st.session_state.active_ticker = None
        st.rerun() # 전체 앱 리런하여 팝업 제거

# --- 사이드바 내비게이션 ---
st.sidebar.title("🚀 Invest Support")

if 'menu' not in st.session_state:
    st.session_state.menu = "🌍 시장 지수 분석"

if st.sidebar.button("🌍 시장 지수 분석", width="stretch", 
                     type="primary" if st.session_state.menu == "🌍 시장 지수 분석" else "secondary"):
    st.session_state.menu = "🌍 시장 지수 분석"
    st.session_state.active_ticker = None # 메뉴 이동 시 팝업 닫기
    st.rerun()

if settings.portfolio.show_portfolio:
    if st.sidebar.button("💼 나의 포트폴리오", width="stretch",
                         type="primary" if st.session_state.menu == "💼 나의 포트폴리오" else "secondary"):
        st.session_state.menu = "💼 나의 포트폴리오"
        st.session_state.active_ticker = None # 메뉴 이동 시 팝업 닫기
        st.rerun()

if st.sidebar.button("🔍 종목 스크리너", width="stretch",
                     type="primary" if st.session_state.menu == "🔍 종목 스크리너" else "secondary"):
    st.session_state.menu = "🔍 종목 스크리너"
    st.session_state.active_ticker = None # 메뉴 이동 시 팝업 닫기
    st.rerun()

if st.sidebar.button("💎 펀더멘털 가치평가", width="stretch",
                     type="primary" if st.session_state.menu == "💎 펀더멘털 가치평가" else "secondary"):
    st.session_state.menu = "💎 펀더멘털 가치평가"
    st.session_state.active_ticker = None
    st.rerun()

if st.sidebar.button("🚀 실시간 마켓 모니터", width="stretch",
                     type="primary" if st.session_state.menu == "🚀 실시간 마켓 모니터" else "secondary"):
    st.session_state.menu = "🚀 실시간 마켓 모니터"
    st.session_state.active_ticker = None
    st.rerun()

if st.sidebar.button("🛠️ 관리자 시스템 로그", width="stretch",
                     type="primary" if st.session_state.menu == "🛠️ 관리자 시스템 로그" else "secondary"):
    st.session_state.menu = "🛠️ 관리자 시스템 로그"
    st.session_state.active_ticker = None
    st.rerun()

menu = st.session_state.menu
st.sidebar.markdown("---")

# --- 지연된 상태 초기화 (StreamlitAPIException 방지 패턴) ---
if st.session_state.get('should_clear_portfolio'):
    if "portfolio_main_table" in st.session_state:
        st.session_state["portfolio_main_table"] = {"selection": {"rows": [], "columns": []}}
    st.session_state.should_clear_portfolio = False

if st.session_state.get('should_clear_screener'):
    if "screener_main_table" in st.session_state:
        st.session_state["screener_main_table"] = {"selection": {"rows": [], "columns": []}}
    st.session_state.should_clear_screener = False

# --- 공통 데이터 로드 (메뉴 로직 전 수행) ---
usd_krw_data = loader.get_market_history("USD_KRW", period="1mo")
current_usd_krw = usd_krw_data['Close'].iloc[-1] if usd_krw_data is not None else 1350.0

# --- 메뉴별 로직 ---

if menu == "🌍 시장 지수 분석":
    try:
        st.sidebar.header("🔍 분석 설정")
        market_name = st.sidebar.selectbox("기준 시장 지수", ["S&P500", "NASDAQ", "KOSPI", "KOSDAQ"])
        period = st.sidebar.select_slider("데이터 기간", options=["1y", "2y", "3y", "5y"], value="2y")

        st.title(f"🌍 {market_name} 시장 분석")
        st.markdown("---")

        with st.spinner('시장 데이터를 불러오는 중...'):
            data = loader.get_market_history(market_name, period=period)
            spread = loader.get_yield_spread(period=period)

            # Phase 2: 추가 데이터 수집 (유동성 및 Breadth)
            sector_df = loader.get_sector_data(period=period)
            dxy_data = loader.get_market_history("DXY", period=period)
            us10y_data = loader.get_market_history("US10Y", period=period)
            vix_data = loader.get_market_history("VIX", period=period)
            hyg_data = loader.get_market_history("HYG", period=period)
            ief_data = loader.get_market_history("IEF", period=period)
            gold_data = loader.get_market_history("GOLD", period=period)
            btc_data = loader.get_market_history("BTC", period=period)

        if data is not None and not data.empty:
            prices = data['Close']
            with st.spinner('분석 엔진 가동 중...'):
                # Phase 6-6: 유동성 및 Credit Spread 통합 분석
                breadth_score = engine.calculate_breadth_score(sector_df)
                liquidity_score = engine.calculate_liquidity_score(dxy_data, us10y_data, gold_data, btc_data, vix=vix_data)

                credit_spread_df = None
                if hyg_data is not None and ief_data is not None:
                    credit_spread_df = pd.DataFrame({'HYG': hyg_data['Close'], 'IEF': ief_data['Close']}).ffill()

                lppl_res = engine.run_lppl_fit(prices)
                attr_res = engine.calculate_attractiveness(prices, spread, liquidity_score, breadth_score, credit_spread_df)

            col_score, col_metrics = st.columns([1, 2])
            with col_score:
                if attr_res:
                    score = attr_res['score']
                    w = attr_res['weights']
                    rs = attr_res['raw_scores']

                    tooltip_lines = [
                        f"**최종 점수 산출 근거**",
                        f"- 추세(Trend): {rs['Trend']}점 × {w['trend']*100:.0f}%",
                        f"- 매크로(Macro): {rs['Macro']}점 × {w['macro']*100:.0f}%",
                        f"- 신용(Credit): {rs.get('Credit', 50)}점 × {w.get('credit', 0)*100:.0f}%",
                        f"- 유동성(Liquidity): {rs['Liquidity']}점 × {w.get('liquidity', 0)*100:.0f}%",
                        f"- Breadth: {rs['Breadth']}점 × {w.get('breadth', 0)*100:.0f}%",
                        f"- 심리(Sentiment): {rs['Sentiment']}점 × {w['sentiment']*100:.0f}%",
                        f"---",
                        f"현재 시장 국면: {attr_res['regime']}"
                    ]
                    st.markdown("##### 시장 매력도 점수", help="\n".join(tooltip_lines))

                    fig_gauge = go.Figure(go.Indicator(
                        mode = "gauge+number", value = score,
                        domain = {'x': [0, 1], 'y': [0, 1]},
                        gauge = {'axis': {'range': [None, 100]}, 'bar': {'color': "white"},
                                 'steps': [{'range': [0, 40], 'color': "red"}, {'range': [40, 75], 'color': "gray"}, {'range': [75, 100], 'color': "green"}]}
                    ))
                    fig_gauge.update_layout(height=200, margin=dict(l=20, r=20, t=20, b=20), template="plotly_dark")
                    st.plotly_chart(fig_gauge, width="stretch")

                # Phase 4: 추천 투자 비중 게이지 추가
                if lppl_res and attr_res:
                    target_weight = engine.calculate_target_weight(attr_res['score'], lppl_res['danger_score'])
                    st.markdown("##### 권장 주식 투자 비중", help="시장 매력도와 LPPL 버블 위험을 결합한 기계적 배분 지침입니다.")
                    fig_target = go.Figure(go.Indicator(
                        mode = "gauge+number", value = target_weight,
                        domain = {'x': [0, 1], 'y': [0, 1]},
                        number = {'suffix': "%", 'font': {'size': 24}},
                        gauge = {'axis': {'range': [None, 100]}, 'bar': {'color': "cyan"},
                                 'steps': [{'range': [0, 30], 'color': "gray"}, {'range': [30, 70], 'color': "darkslategray"}]}
                    ))
                    fig_target.update_layout(height=180, margin=dict(l=20, r=20, t=20, b=20), template="plotly_dark")
                    st.plotly_chart(fig_target, width="stretch")

            with col_metrics:
                m_col1, m_col2 = st.columns(2)
                if len(prices) >= 2:
                    current_price = prices.iloc[-1]
                    prev_price = prices.iloc[-2]
                    price_diff = ((current_price - prev_price) / prev_price) * 100
                    m_col1.metric(f"현재 {market_name}", f"{current_price:,.2f}", f"{price_diff:+.2f}%")
                else:
                    m_col1.metric(f"현재 {market_name}", f"{prices.iloc[-1]:,.2f}")
                
                if attr_res:
                    m_col2.metric("리스크 수준", attr_res['risk_level'], 
                                 help="시장 변동성, 매크로, 유동성을 결합한 종합 리스크 등급입니다.")

                    st.markdown("---")
                    sc1, sc2, sc3, sc4, sc5, sc6 = st.columns(6)
                    sc1.metric("추세", f"{rs['Trend']:.0f}", 
                              help="200일 이동평균선과의 이격도(Z-Score) 기반. 수치가 높을수록 단기 과열, 낮을수록 저평가 국면을 의미합니다.")
                    sc2.metric("매크로", f"{rs['Macro']:.0f}", 
                              help="미국 국채 장단기 금리차(10Y-2Y)의 수준과 변화율을 반영합니다. 금리차가 확대되거나 양수일 때 높은 점수를 부여합니다.")
                    sc3.metric("신용", f"{rs.get('Credit', 50):.0f}", 
                              help="하이일드 채권(HYG) 대 국채(IEF) 비율의 상대적 강세입니다. 높을수록 기업들의 부도 위험이 낮고 신용 시장이 건강함을 의미합니다.")
                    sc4.metric("유동성", f"{liquidity_score:+.1f}", 
                              help="달러, 금리, 금, 비트코인, VIX의 모멘텀을 종합합니다. 달러/금리/VIX 하락 및 금/비트코인 상승 시 유동성이 풍부한 것으로 판단합니다.")
                    sc5.metric("Breadth", f"{breadth_score:.0f}%", 
                              help="주요 11개 섹터 ETF 중 50일 이동평균선 위에 있는 종목의 비율입니다. 시장 상승의 질(내부 체력)을 측정합니다.")
                    sc6.metric("심리", f"{rs['Sentiment']:.0f}", 
                              help="RSI 지표의 스무딩 값을 활용합니다. 극심한 과매도 구간(공포)일수록 반등 매력도가 높아집니다.")

                    st.success(f"**추천 행동:** {attr_res['action']}")
                    st.info(f"**현재 시장 국면:** {attr_res['regime']}")

            # LPPL 버블 진단 섹션
            st.markdown("---")
            st.subheader(f"📊 {market_name} LPPL 버블 진단", help="로그 주기적 전력 법칙(LPPL)을 이용한 추세 한계점 예측 모델입니다.")
            
            with st.expander("📖 LPPL 분석 모델 상세 가이드 (필독)", expanded=False):
                st.markdown(r"""
                **1. 로그 주기적 전력 법칙 (LPPL) 모델이란?**
                자산 가격이 단순히 상승하는 것을 넘어 '초지수적(Super-exponential)'으로 가속화될 때 발생하는 특이 패턴을 분석합니다. 투자자들의 모방 행동(Herd Behavior)이 극에 달할 때 나타나는 '미세한 진동'과 '상승 가속'을 수학적으로 포착합니다.
                
                **2. 핵심 파라미터 해석**
                - **위험 점수 (Danger Score)**: $B < 0$ (가속), $0.1 < m < 0.9$ (성장 구조), $6 < \omega < 13$ (진동 패턴), $R^2 > 0.8$ (신뢰도) 등 4대 조건을 합산합니다. 70점 이상은 강력한 버블 신호입니다.
                - **예상 임계점 (Tc)**: 가격 가속이 수학적으로 한계에 도달하는 시점입니다. 반드시 폭락을 의미하진 않으나, 이 시점 전후로 '추세 반전' 확률이 극대화됩니다.
                - **결정계수 (R²)**: 실제 가격이 모델과 얼마나 일치하는지 나타냅니다. 0.8 이상일 때 신뢰도가 매우 높습니다.
                """)
            
            if lppl_res:
                l1, l2, l3, l4 = st.columns(4)
                d_score = lppl_res['danger_score']
                if d_score >= settings.lppl.bubble_threshold:
                    l_status = "🚨 버블 붕괴 임박"
                elif d_score >= settings.lppl.warning_threshold:
                    l_status = "⚠️ 투기적 과열"
                else:
                    l_status = "✅ 정상 추세"
                    
                l1.metric("위험 점수", f"{d_score:.4f} / 100", 
                         help="""
                         **위험 점수 산출 근거 (4대 핵심 팩터)**
                         1. **B < 0**: 가격 가속화 여부 (+20)
                         2. **0.1 < m < 0.9**: 초지수적 성장 구조 (+30)
                         3. **6 < omega < 13**: 로그 주기적 진동 패턴 (+30)
                         4. **R² > 0.8**: 통계적 신뢰도 (+20)
                         """)
                l2.metric("위험 등급", l_status)
                if 'tc_date' in lppl_res:
                    l3.metric("예상 임계점(Tc)", lppl_res['tc_date'].strftime('%Y-%m-%d'), 
                             help="수학적으로 계산된 잠재적 가격 한계점입니다. 이 시점 전후로 급격한 추세 반전 확률이 높습니다.")
                else:
                    l3.metric("예상 임계점(Tc)", "N/A")
                l4.metric("모델 신뢰도(R²)", f"{lppl_res.get('r_squared', 0):.4f}", 
                         help="실제 가격이 모델과 일치하는 정도입니다. 0.8 이상일 때 신호가 강력합니다.")
                
                if d_score >= 40 and 'tc_date' in lppl_res:
                    st.warning(f"**주의:** {market_name} 시장에서 버블 형성 징후가 감지되었습니다. Tc({lppl_res['tc_date'].strftime('%Y-%m-%d')}) 전후 변동성에 유의하세요.")
            else:
                st.info("현재 시장에서는 유의미한 버블 패턴(LPPL)이 감지되지 않았습니다. 추세가 안정적이거나 신호가 약한 상태입니다.")

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=prices.index, y=prices.values, mode='lines', name='Actual Price', line=dict(color='white')))
            if lppl_res and 'fitted' in lppl_res:
                # 미래 30일까지 포함된 데이터이므로 날짜 범위를 다시 계산
                # prices.index[0]부터 시작하여 fitted의 길이만큼 날짜 생성
                all_dates = pd.date_range(start=prices.index[0], periods=len(lppl_res['fitted']), freq='D')
                fig.add_trace(go.Scatter(x=all_dates, y=lppl_res['fitted'], mode='lines', name='LPPL Prediction', line=dict(color='cyan', dash='dot')))
                if 'tc_date' in lppl_res:
                    fig.add_vline(x=lppl_res['tc_date'], line_width=1, line_dash="dash", line_color="red")
                
                # y축 범위를 실제 가격 범위에 맞춤 (fitted 값이 튈 경우 대비)
                y_min, y_max = prices.min() * 0.8, prices.max() * 1.2
                fig.update_yaxes(range=[y_min, y_max])
            
            fig.update_layout(template="plotly_dark", height=400, margin=dict(l=20, r=20, t=30, b=20))
            st.plotly_chart(fig, width="stretch")

            if spread is not None:
                st.subheader("📉 글로벌 매크로 가이드: 미국 국채 금리 및 장단기 스프레드", help="장기 금리와 단기 금리의 차이 및 각 만기별 금리 추이를 통해 경기 순환 국면을 판단합니다.")
                
                with st.expander("📖 매크로 지표 분석 상세 가이드 (필독)", expanded=False):
                    st.markdown("""
                    **1. 수익률 곡선(Yield Curve)의 의미**
                    통상 장기 금리는 미래 위험을 반영해 단기 금리보다 높습니다. 하지만 경기 침체 우려가 커지면 단기 금리가 더 높아지는 '역전' 현상이 발생합니다.
                    
                    **2. 국면별 판정 기준**
                    - **✅ 정상 (Normal, > 0.5%)**: 경제가 선순환하며 성장하고 있는 건강한 상태입니다.
                    - **⚠️ 평탄화 (Flattening, 0 ~ 0.5%)**: 성장 둔화의 초기 신호입니다. 금리 인상기나 경기 정점에서 관찰됩니다.
                    - **🚨 역전 (Inverted, < 0%)**: 강력한 경기 침체 예고 지표입니다. 역사적으로 역전 후 12~18개월 내에 침체가 발생했습니다.
                    
                    **3. 만기별 금리의 의미**
                    - **2년물 (단기)**: 중앙은행의 통화 정책(금리 인상/인하)에 가장 민감하게 반응합니다.
                    - **10년물 (중기)**: 시장의 미래 성장성과 인플레이션 기대를 반영하는 벤치마크 금리입니다.
                    - **30년물 (장기)**: 초장기 성장 전망과 보험/연금 등 장기 자본의 수요를 반영합니다.
                    """)
                
                # 뷰 선택 (장기 vs 인트라데이)
                view_col1, view_col2 = st.columns([1, 2])
                with view_col1:
                    yield_view = st.radio("보기 설정", ["장기 추세 (5년)", "실시간 추세 (5분봉)"], horizontal=True, key="yield_view_radio")
                
                # 데이터 수집 (선택된 뷰에 따라)
                if yield_view == "장기 추세 (5년)":
                    u_period, u_interval = "5y", "1d"
                    u_title_suffix = "(5년)"
                else:
                    u_period, u_interval = "1d", "5m"
                    u_title_suffix = "(5분봉)"
                
                with st.spinner(f"미국채 {u_title_suffix} 데이터 로드 중..."):
                    us2y = loader.get_market_history("US2Y", period=u_period, interval=u_interval)
                    us10y = loader.get_market_history("US10Y", period=u_period, interval=u_interval)
                    us30y = loader.get_market_history("US30Y", period=u_period, interval=u_interval)
                
                m1, m2, m3 = st.columns(3)
                
                # 현재 스프레드 및 매크로 상태 (10Y-2Y 기준)
                # 스프레드 데이터는 항상 1일 단위 기반으로 계산된 것을 사용 (안정성)
                curr_spread = spread['Spread'].iloc[-1]
                prev_spread = spread['Spread'].iloc[-20] if len(spread) >= 20 else spread['Spread'].iloc[0]
                spread_change = curr_spread - prev_spread
                
                if curr_spread < 0:
                    spread_status = "🚨 수익률 곡선 역전"
                elif curr_spread < 0.5:
                    spread_status = "⚠️ 곡선 평탄화"
                else:
                    spread_status = "✅ 정상 추세"

                m1.metric("장단기 금리차 (10Y-2Y)", f"{curr_spread:.3f}%", f"{spread_change:+.3f}% (MoM)")
                m2.metric("매크로 상태", spread_status)
                m3.metric("매크로 모멘텀", "개선 중" if spread_change > 0 else "악화 중")
                
                # 만기별 현재 금리 표시
                st.markdown(f"#### 🏛️ 미국 국채 만기별 현재 수익률 {u_title_suffix}")
                y1, y2, y3 = st.columns(3)
                if us2y is not None:
                    y2_change = us2y['Close'].iloc[-1] - us2y['Close'].iloc[-2] if len(us2y) > 1 else 0
                    y1.metric("US 2Y (단기)", f"{us2y['Close'].iloc[-1]:.3f}%", f"{y2_change:+.3f}%")
                if us10y is not None:
                    y10_change = us10y['Close'].iloc[-1] - us10y['Close'].iloc[-2] if len(us10y) > 1 else 0
                    y2.metric("US 10Y (중기)", f"{us10y['Close'].iloc[-1]:.3f}%", f"{y10_change:+.3f}%")
                if us30y is not None:
                    y30_change = us30y['Close'].iloc[-1] - us30y['Close'].iloc[-2] if len(us30y) > 1 else 0
                    y3.metric("US 30Y (장기)", f"{us30y['Close'].iloc[-1]:.3f}%", f"{y30_change:+.3f}%")
                
                # 금리 추이 통합 차트
                fig_yields = go.Figure()
                if us2y is not None:
                    fig_yields.add_trace(go.Scatter(x=us2y.index, y=us2y['Close'], name='US 2Y', line=dict(color='#00d1b2')))
                if us10y is not None:
                    fig_yields.add_trace(go.Scatter(x=us10y.index, y=us10y['Close'], name='US 10Y', line=dict(color='#3273dc')))
                if us30y is not None:
                    fig_yields.add_trace(go.Scatter(x=us30y.index, y=us30y['Close'], name='US 30Y', line=dict(color='#ff3860')))
                
                fig_yields.update_layout(title=f"미국 국채 만기별 금리 추이 {u_title_suffix}", template="plotly_dark", height=400, 
                                        margin=dict(l=10, r=10, t=40, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                st.plotly_chart(fig_yields, width="stretch")
                
                # 금리차 차트 (별도 표시)
                fig_spread = px.area(spread, x=spread.index, y='Spread', title="장단기 금리차 (10Y-2Y) 추이", 
                                    template="plotly_dark", height=300, color_discrete_sequence=['#ffdd57'])
                fig_spread.add_hline(y=0, line_dash="dash", line_color="red")
                fig_spread.update_layout(margin=dict(l=10, r=10, t=40, b=10))
                st.plotly_chart(fig_spread, width="stretch")

                # --- 글로벌 매크로 4대 지표 (DXY, BEI, Gold, Oil) ---
                st.markdown("---")
                st.subheader("🌐 글로벌 매크로 가이드", 
                            help="달러 강도, 물가 전망, 원자재 흐름은 글로벌 자산 배분의 핵심 변수입니다.")
                
                with st.spinner('글로벌 매크로 데이터 로드 중...'):
                    dxy = loader.get_market_history("DXY", period="1y")
                    tip = loader.get_market_history("TIP", period="1y")
                    ief = loader.get_market_history("IEF", period="1y")
                    gold = loader.get_market_history("GOLD", period="1y")
                    oil = loader.get_market_history("OIL", period="1y")
                    
                # 1행: 달러 인덱스와 기대 인플레이션
                g1, g2 = st.columns(2)
                with g1:
                    if dxy is not None:
                        curr_dxy = dxy['Close'].iloc[-1]
                        dxy_mom = ((curr_dxy - dxy['Close'].iloc[-20]) / dxy['Close'].iloc[-20] * 100) if len(dxy) >= 20 else 0
                        st.metric("달러 인덱스 (DXY)", f"{curr_dxy:.2f}", f"{dxy_mom:+.2f}% (1Mo)",
                                 help="주요 6개국 통화 대비 달러 가치입니다. 달러 강세 시 주식과 신흥국 자산은 약세를 보입니다.")
                        fig_dxy = px.line(dxy, y='Close', template="plotly_dark", height=180)
                        fig_dxy.update_layout(margin=dict(l=10, r=10, t=10, b=10), xaxis_title=None, yaxis_title=None)
                        st.plotly_chart(fig_dxy, width="stretch")

                with g2:
                    if tip is not None and ief is not None:
                        bei_proxy = tip['Close'] / ief['Close']
                        curr_bei = bei_proxy.iloc[-1]
                        bei_mom = ((curr_bei - bei_proxy.iloc[-20]) / bei_proxy.iloc[-20] * 100) if len(bei_proxy) >= 20 else 0
                        st.metric("기대 인플레이션 (BEI Proxy)", f"{curr_bei:.3f}", f"{bei_mom:+.2f}% (1Mo)",
                                 help="물가연동채(TIP)와 일반국채(IEF)의 가격 비율입니다. 수치 상승은 시장의 인플레이션 우려를 의미합니다.")
                        fig_bei = px.line(bei_proxy, template="plotly_dark", height=180)
                        fig_bei.update_layout(margin=dict(l=10, r=10, t=10, b=10), xaxis_title=None, yaxis_title=None)
                        st.plotly_chart(fig_bei, width="stretch")

                # 2행: 금과 유가
                st.markdown("<br>", unsafe_allow_html=True) # 줄바꿈 간격 조정
                g3, g4 = st.columns(2)
                with g3:
                    if gold is not None:
                        curr_gold = gold['Close'].iloc[-1]
                        gold_mom = ((curr_gold - gold['Close'].iloc[-20]) / gold['Close'].iloc[-20] * 100) if len(gold) >= 20 else 0
                        st.metric("금 선물 (Gold)", f"${curr_gold:,.1f}/oz", f"{gold_mom:+.2f}% (1Mo)",
                                 help="전통적인 인플레이션 방어 및 안전 자산입니다. 시스템 위기 시 가치가 상승합니다.")
                        fig_gold = px.line(gold, y='Close', template="plotly_dark", height=180)
                        fig_gold.update_traces(line_color="gold")
                        fig_gold.update_layout(margin=dict(l=10, r=10, t=10, b=10), xaxis_title=None, yaxis_title=None)
                        st.plotly_chart(fig_gold, width="stretch")
                        
                with g4:
                    if oil is not None:
                        curr_oil = oil['Close'].iloc[-1]
                        oil_mom = ((curr_oil - oil['Close'].iloc[-20]) / oil['Close'].iloc[-20] * 100) if len(oil) >= 20 else 0
                        st.metric("WTI 유가 (Oil)", f"${curr_oil:,.2f}/bbl", f"{oil_mom:+.2f}% (1Mo)",
                                 help="공급측 인플레이션 압력의 핵심 지표입니다. 유가 급등은 기업 마진을 압박합니다.")
                        fig_oil = px.line(oil, y='Close', template="plotly_dark", height=180)
                        fig_oil.update_traces(line_color="orangered")
                        fig_oil.update_layout(margin=dict(l=10, r=10, t=10, b=10), xaxis_title=None, yaxis_title=None)
                        st.plotly_chart(fig_oil, width="stretch")

                # 3행: VIX와 비트코인
                st.markdown("<br>", unsafe_allow_html=True)
                g5, g6 = st.columns(2)
                with g5:
                    if vix_data is not None:
                        curr_vix = vix_data['Close'].iloc[-1]
                        vix_mom = ((curr_vix - vix_data['Close'].iloc[-20]) / vix_data['Close'].iloc[-20] * 100) if len(vix_data) >= 20 else 0
                        st.metric("변동성 지표 (VIX)", f"{curr_vix:.2f}", f"{vix_mom:+.2f}% (1Mo)",
                                 help="S&P 500 옵션 가격을 기반으로 한 시장의 공포 지수입니다. 20 이하는 안정, 30 이상은 공포 구간입니다.")
                        fig_vix = px.line(vix_data, y='Close', template="plotly_dark", height=180)
                        fig_vix.update_traces(line_color="mediumpurple")
                        fig_vix.update_layout(margin=dict(l=10, r=10, t=10, b=10), xaxis_title=None, yaxis_title=None)
                        st.plotly_chart(fig_vix, width="stretch")
                
                with g6:
                    if btc_data is not None:
                        curr_btc = btc_data['Close'].iloc[-1]
                        btc_mom = ((curr_btc - btc_data['Close'].iloc[-20]) / btc_data['Close'].iloc[-20] * 100) if len(btc_data) >= 20 else 0
                        st.metric("비트코인 (BTC)", f"${curr_btc:,.0f}", f"{btc_mom:+.2f}% (1Mo)",
                                 help="최근 위험 선호도 및 글로벌 유동성을 나타내는 선행 지표로 활용됩니다.")
                        fig_btc = px.line(btc_data, y='Close', template="plotly_dark", height=180)
                        fig_btc.update_traces(line_color="orange")
                        fig_btc.update_layout(margin=dict(l=10, r=10, t=10, b=10), xaxis_title=None, yaxis_title=None)
                        st.plotly_chart(fig_btc, width="stretch")

            st.markdown("---")
            st.header("🤖 AI 투자 전략 리포트")
            if st.button("AI 종합 리포트 생성 (Gemini)"):
                with st.spinner('헤지펀드 리스크 매니저가 분석 중...'):
                    # 매크로 데이터 취합
                    curr_dxy = dxy['Close'].iloc[-1] if 'dxy' in locals() and dxy is not None else "N/A"
                    curr_bei = bei_proxy.iloc[-1] if 'bei_proxy' in locals() and bei_proxy is not None else "N/A"
                    curr_spread = spread['Spread'].iloc[-1] if spread is not None else "N/A"
                    curr_gold = gold['Close'].iloc[-1] if 'gold' in locals() and gold is not None else "N/A"
                    curr_oil = oil['Close'].iloc[-1] if 'oil' in locals() and oil is not None else "N/A"
                    
                    macro_info = {
                        'dxy': curr_dxy,
                        'bei': curr_bei,
                        'spread': curr_spread,
                        'gold': curr_gold,
                        'oil': curr_oil,
                        'vix': vix_data['Close'].iloc[-1] if (vix_data is not None and not vix_data.empty) else "N/A"
                    }
                    
                    report = reporter.generate_report(market_name, lppl_res, attr_res, macro_data=macro_info)
                    st.markdown(report)
    except Exception as e:
        st.error(f"⚠️ 시장 분석 중 오류가 발생했습니다. 데이터 연결 상태를 확인해주세요.")
        with st.expander("상세 오류 정보 (개발자용)"):
            st.exception(e)

elif menu == "💼 나의 포트폴리오":
    st.title("💼 나의 포트폴리오 관리")
    st.markdown("---")
    
    portfolio_data = loader.load_portfolio()
    if portfolio_data:
        st.sidebar.subheader("📈 포트폴리오 요약")
        st.sidebar.write(f"보유 종목 수: {len(portfolio_data)}개")
    
    with st.expander("➕ 새 종목 추가/수정", expanded=not portfolio_data):
        c1, c2, c3, c4 = st.columns([2, 1, 2, 1])
        in_ticker = c1.text_input("티커 (예: AAPL, 005930.KS)").upper()
        in_qty = c2.number_input("보유 수량", min_value=0.0, step=1.0)
        in_price = c3.number_input("평균 단가", min_value=0.0, step=0.01)
        in_currency = c4.selectbox("통화", ["USD", "KRW"])
        
        if st.button("포트폴리오에 반영"):
            if in_ticker:
                existing = next((item for item in portfolio_data if item['Ticker'] == in_ticker), None)
                if existing:
                    existing.update({'Quantity': in_qty, 'AvgPrice': in_price, 'Currency': in_currency})
                else:
                    portfolio_data.append({'Ticker': in_ticker, 'Quantity': in_qty, 'AvgPrice': in_price, 'Currency': in_currency})
                loader.save_portfolio(portfolio_data)
                st.rerun()

    if portfolio_data:
        with st.spinner('실시간 데이터 분석 중...'):
            tickers = [item['Ticker'] for item in portfolio_data]
            rows = []
            total_value_krw = 0
            total_invested_krw = 0
            
            for item in portfolio_data:
                ticker = item['Ticker']
                qty = item['Quantity']
                avg_p = item['AvgPrice']
                curr = item['Currency']
                
                # 데이터 한 번만 로드하여 효율성 제고
                stock_history_2y = loader.get_market_history(ticker, period="2y")
                
                if stock_history_2y is not None and not stock_history_2y.empty:
                    curr_p = stock_history_2y['Close'].iloc[-1]
                    # 포트폴리오 개요에서는 계산 속도를 위해 5회 시뮬레이션만 수행 (Quick Check)
                    lppl_res = engine.run_lppl_fit(stock_history_2y['Close'], num_iterations=5)
                    danger_score = lppl_res['danger_score'] if lppl_res else 0
                else:
                    curr_p = avg_p
                    danger_score = 0
                
                inv_val = qty * avg_p
                curr_val = qty * curr_p
                profit_pct = (curr_val - inv_val) / inv_val * 100 if inv_val > 0 else 0
                
                rate = current_usd_krw if curr == "USD" else 1.0
                total_value_krw += (curr_val * rate)
                total_invested_krw += (inv_val * rate)
                
                # --- 동적 변동사항(Notes) 생성 로직 ---
                dynamic_notes = []
                
                if stock_history_2y is not None and len(stock_history_2y) >= 2:
                    # 1. 전일 대비 주가 변동
                    last_price = stock_history_2y['Close'].iloc[-1]
                    prev_price = stock_history_2y['Close'].iloc[-2]
                    day_change = (last_price - prev_price) / prev_price * 100
                    
                    if day_change >= 3: dynamic_notes.append(f"🚀 당일 급등 ({day_change:+.1f}%)")
                    elif day_change <= -3: dynamic_notes.append(f"📉 당일 급락 ({day_change:+.1f}%)")
                    elif abs(day_change) > 0.5: dynamic_notes.append(f"주가 {day_change:+.1f}%")

                    # 2. 리스크 상태 알림
                    if danger_score >= settings.lppl.bubble_threshold: dynamic_notes.append("🚨 고위험(버블)")
                    elif danger_score >= settings.lppl.warning_threshold: dynamic_notes.append("⚠️ 과열 주의")
                    
                    # 3. 수익률 마일스톤
                    if profit_pct >= 30: dynamic_notes.append("💰 수익 극대화 중")
                    elif profit_pct <= -15: dynamic_notes.append("🩹 손절 검토 필요")
                    
                    # 4. 특이 사항 (과거 수동 메모와 결합 가능하나 여기서는 자동 생성 위주)
                    manual_note = item.get('Notes', '')
                    if "매도" in manual_note or "매수" in manual_note:
                        dynamic_notes.append(f"({manual_note.split('/')[0].strip()})")
                
                final_note = " / ".join(dynamic_notes) if dynamic_notes else "변동성 낮음"
                
                name = item.get('Name', ticker)
                rows.append({
                    '종목명': name,
                    'Ticker': ticker, 
                    '수량': qty, 
                    '평단가': avg_p, 
                    '현재가': curr_p, 
                    '통화': curr, 
                    '수익률': profit_pct, 
                    '평가금액(KRW)': curr_val * rate, 
                    '위험점수': danger_score, 
                    '변동사항': final_note
                })
            
            df_portfolio = pd.DataFrame(rows)
            df_portfolio['비중(%)'] = (df_portfolio['평가금액(KRW)'] / total_value_krw * 100)

        total_profit_krw = total_value_krw - total_invested_krw
        total_profit_pct = (total_profit_krw / total_invested_krw * 100) if total_invested_krw > 0 else 0
        
        s1, s2, s3 = st.columns(3)
        s1.metric("총 평가금액", f"{total_value_krw:,.0f} 원")
        s2.metric("총 수익", f"{total_profit_krw:,.0f} 원", f"{total_profit_pct:+.2f}%")
        
        avg_risk = df_portfolio['위험점수'].mean()
        s3.metric("포트폴리오 위험도", f"{avg_risk:.4f} / 100",
                 help="보유 종목별 LPPL 위험 점수의 산술 평균값입니다. 전체 자산이 버블 붕괴 위기에 얼마나 노출되어 있는지 나타냅니다.")

        with st.expander("🛡️ 포트폴리오 위험 점수 산출 및 대응 가이드", expanded=False):
            st.markdown(r"""
            ### 1. 점수 산출 방식
            - **개별 종목 점수**: 각 종목의 최근 2년 가격 데이터를 LPPL(로그 주기적 전력 법칙) 모델로 분석하여 산출합니다. 
            - **포트폴리오 총점**: 현재 보유한 모든 종목의 위험 점수를 **산술 평균**한 값입니다. (개별 종목의 가속도, 진동 패턴, 통계적 신뢰도 반영)

            ### 2. 점수별 리스크 등급 및 영향
            - **🟢 0 ~ 40 (안정)**: 포트폴리오 전반이 안정적인 상승 또는 박스권에 있습니다. 자산 배분 원칙을 유지하며 보유하기 적합한 구간입니다.
            - **🟡 40 ~ 70 (주의)**: 일부 주력 종목에서 **투기적 과열**이 감지됩니다. 추가 매수보다는 수익 실현을 고민하거나, 현금 비중 확대를 검토해야 하는 시점입니다.
            - **🔴 70 ~ 100 (위험)**: 포트폴리오 내 다수 종목이 **수학적 한계점(Tc)**에 근접했습니다. 급격한 추세 반전이나 폭락의 위험이 매우 높으므로, 적극적인 리스크 관리(분할 매도, 헤징)가 권장됩니다.

            ### 3. 대응 전략 제안
            - **위험 점수 급증 시**: 개별 종목 상세 리서치를 통해 어떤 종목이 점수를 끌어올리고 있는지 확인하세요.
            - **Tc(임계점) 확인**: 고득점 종목의 예상 임계점이 현재 날짜와 가까울수록 대응의 시급성이 높습니다.
            """)

        # 1. 자산 비중 현황 (상단 배치)
        fig_pie = px.pie(df_portfolio, values='평가금액(KRW)', names='종목명', title="자산 비중 현황", hole=0.4, template="plotly_dark")
        fig_pie.update_traces(textposition='inside', textinfo='label+percent')
        st.plotly_chart(fig_pie, width="stretch")

        # 2. 보유 종목 상세 (하단 배치, 가로 꽉 채우기)
        st.subheader("📋 보유 종목 상세")
        
        with st.expander("❓ 종목별 위험 점수는 어떻게 결정되나요?", expanded=False):
            st.markdown("""
            개별 종목의 **위험 점수(0-100)**는 LPPL 모델의 4가지 핵심 통계 지표를 복합적으로 평가합니다:
            1. **B < 0 (가격 가속도)** / 2. **0.1 < m < 0.9 (성장 구조)** / 3. **진동 패턴** / 4. **R² (신뢰도)**
            **💡 팁:** 70점 이상은 '수학적 과열 상태'를 의미합니다. 표의 행을 클릭하면 상세 분석이 가능합니다.
            """)

        # 인터랙티브 데이터프레임으로 변경 (행/셀 클릭 지원)
        display_portfolio = df_portfolio[['종목명', 'Ticker', '수익률', '평가금액(KRW)', '위험점수', '변동사항']].copy()
        
        event_p = st.dataframe(
            display_portfolio.style.format({
                '수익률': '{:+.2f}%',
                '평가금액(KRW)': '{:,.0f}',
                '위험점수': '{:.4f}'
            }).background_gradient(subset=['위험점수'], cmap='Reds'),
            width="stretch",
            column_config={
                "종목명": st.column_config.TextColumn("종목명", width="medium"),
                "Ticker": st.column_config.TextColumn("티커", width="small"),
                "수익률": st.column_config.NumberColumn("수익률", help="매수 평단가 대비 수익률"),
                "평가금액(KRW)": st.column_config.NumberColumn("평가금액", help="현재가 기준 원화 환산 가치"),
                "위험점수": st.column_config.NumberColumn("위험도", help="LPPL 기반 버블 위험 지수"),
                "변동사항": st.column_config.TextColumn("특이사항", width="large")
            },
            on_select="rerun",
            selection_mode="single-row",
            key="portfolio_main_table"
        )
        
        # 행 선택 시 상세 분석 트리거
        if event_p and len(event_p.selection.rows) > 0:
            # 선택된 행의 데이터 추출
            selected_row_idx = event_p.selection.rows[0]
            selected_ticker = display_portfolio.iloc[selected_row_idx]['Ticker']
            selected_name = display_portfolio.iloc[selected_row_idx]['종목명']
            
            # 1. 티커 관련 상태 강제 초기화
            st.session_state[f"lppl_{selected_ticker}"] = None
            st.session_state[f"news_{selected_ticker}"] = None
            st.session_state[f"ai_report_{selected_ticker}"] = None
            if f"tv_symbol_{selected_ticker}" in st.session_state:
                del st.session_state[f"tv_symbol_{selected_ticker}"]
            
            # 2. 글로벌 팝업 티커 설정
            st.session_state.active_ticker = selected_ticker
            
            # 3. 테이블 선택 상태 지연 초기화 설정 (API 예외 방지)
            st.session_state.should_clear_portfolio = True
            
            # 안내 및 재실행
            st.success(f"📍 {selected_name} 분석 준비 중...")
            st.rerun()
            
        st.caption("💡 표의 행이나 셀을 클릭하면 해당 종목의 상세 분석 팝업이 열립니다.")

        st.markdown("---")
        if 'rebal_df' not in st.session_state:
            st.session_state.rebal_df = None

        if st.button("AI 리스크 매니저 종합 진단 시작"):
            with st.spinner('검토 중...'):
                report = reporter.generate_portfolio_report(df_portfolio, st.session_state.rebal_df)
                st.markdown(report)

        # --- 리밸런싱 가이드 섹션 ---
        st.markdown("---")
        st.header("🔄 포트폴리오 리밸런싱 가이드")
        st.markdown("""
        현재 시장 리스크(LPPL)와 종목별 위험도를 분석하여, 최적의 비중으로 자산을 재조정하기 위한 지침을 제공합니다.
        """)
        
        rebal_market = st.selectbox("기준 시장 지수 (리스크 측정용)", ["S&P500", "KOSPI"])
        
        if st.button("⚖️ 리밸런싱 시뮬레이션 실행", width="stretch"):
            with st.spinner('시장 및 종목 리스크 분석 중...'):
                # 1. 기준 시장 분석 (전체 비중 도출)
                ref_index = "^GSPC" if rebal_market == "S&P500" else "^KS11"
                ref_data = loader.get_market_history(ref_index, period="2y")
                
                if ref_data is not None:
                    ref_prices = ref_data['Close']
                    ref_lppl = engine.run_lppl_fit(ref_prices)
                    
                    # 시장 매력도 및 레짐 분석
                    ref_attr = engine.calculate_attractiveness(ref_prices, None)
                    curr_regime = ref_attr['regime'] if ref_attr else "Transition (국면 전환)"
                    
                    # 전체 주식 비중 결정 (매력도 반영)
                    total_target_weight = engine.calculate_target_weight(
                        ref_attr['score'] if ref_attr else 50, 
                        ref_lppl['danger_score'] if ref_lppl else 0
                    )
                    
                    # 2. 리밸런싱 계산 (레짐 정보 전달)
                    rebal_df = screener.calculate_rebalancing(df_portfolio, total_target_weight, loader, curr_regime)
                    st.session_state.rebal_df = rebal_df
                    
                    # 3. 결과 시각화 및 전략 제안
                    st.subheader("📊 리밸런싱 실행 전략")
                    
                    # A. 핵심 지표 요약
                    curr_equity_weight = df_portfolio['비중(%)'].sum()
                    s1, s2 = st.columns(2)
                    with s1:
                        fig_rebal = go.Figure()
                        fig_rebal.add_trace(go.Indicator(
                            mode = "gauge+number", value = total_target_weight,
                            title = {'text': "권장 주식 비중"},
                            number = {'suffix': "%"},
                            gauge = {'axis': {'range': [None, 100]}, 'bar': {'color': "cyan"}}
                        ))
                        fig_rebal.update_layout(height=250, margin=dict(l=20, r=20, t=50, b=20), template="plotly_dark")
                        st.plotly_chart(fig_rebal, width="stretch")
                    
                    with s2:
                        st.info(f"현재 총 주식 비중: **{curr_equity_weight:.1f}%**")
                        if curr_equity_weight > total_target_weight:
                            st.warning(f"⚠️ 권장치 대비 **{curr_equity_weight - total_target_weight:.1f}%** 과다 보유 중입니다. 현금 확보(매도)가 권장됩니다.")
                        else:
                            st.success(f"✅ 권장 비중 범위 내에 있습니다. 여유 현금 **{total_target_weight - curr_equity_weight:.1f}%**를 활용하여 추가 매수가 가능합니다.")

                    # B. 전후 비중 비교 차트 (Grouped Bar)
                    rebal_df['현재비중(%)'] = (rebal_df['평가금액(KRW)'] / df_portfolio['평가금액(KRW)'].sum() * 100)
                    fig_compare = go.Figure()
                    fig_compare.add_trace(go.Bar(name='현재 비중', x=rebal_df['종목명'], y=rebal_df['현재비중(%)'], marker_color='gray'))
                    fig_compare.add_trace(go.Bar(name='목표 비중', x=rebal_df['종목명'], y=rebal_df['TargetWeight'], marker_color='cyan'))
                    fig_compare.update_layout(title="종목별 비중 조정 계획 (%)", barmode='group', template="plotly_dark", height=350,
                                             xaxis_title=None, yaxis_title="비중 (%)")
                    st.plotly_chart(fig_compare, width="stretch")

                    # C. 실행 지침 및 조정 사유 테이블
                    st.markdown("#### ⚖️ 구체적 매매 지침")
                    
                    def get_rebal_action(qty):
                        if qty > 0.5: return "🟢 매수"
                        elif qty < -0.5: return "🔴 매도"
                        else: return "⚪ 유지"
                    
                    def get_rebal_reason(row):
                        reasons = []
                        if row['DangerScore'] >= settings.lppl.bubble_threshold: reasons.append("🚨 LPPL 버블 위험")
                        if row['TargetWeight'] > row['현재비중(%)'] + 2: reasons.append("📈 비중 확대")
                        if row['TargetWeight'] < row['현재비중(%)'] - 2: reasons.append("📉 과다 보유 조정")
                        return " / ".join(reasons) if reasons else "비중 적정"

                    rebal_df['액션'] = rebal_df['TradeQty'].apply(get_rebal_action)
                    rebal_df['조정 사유'] = rebal_df.apply(get_rebal_reason, axis=1)
                    
                    display_rebal = rebal_df[['종목명', '현재비중(%)', 'TargetWeight', 'TradeQty', '액션', '조정 사유']].copy()
                    display_rebal.columns = ['종목명', '현재(%)', '목표(%)', '조정 수량', '액션', '사유']
                    
                    st.dataframe(
                        display_rebal.style.format({
                            '현재(%)': '{:.1f}%',
                            '목표(%)': '{:.1f}%',
                            '조정 수량': '{:+.1f}'
                        }).apply(lambda x: ['color: lightgreen' if '매수' in str(v) else 'color: lightcoral' if '매도' in str(v) else '' for v in x], axis=1),
                        width="stretch"
                    )
                    
                    # D. AI 리스크 매니저 전략 코멘트
                    if reporter.model:
                        with st.expander("🤖 AI 리스크 매니저의 전략적 조언", expanded=True):
                            with st.spinner('리밸런싱 계획 검토 중...'):
                                rebal_context = rebal_df[['종목명', 'TradeQty', 'DangerScore']].to_string()
                                prompt = f"""너는 헤지펀드 리스크 매니저다. 다음 리밸런싱 계획을 검토하고 투자자에게 실행 조언을 하라:
                                {rebal_context}
                                1. 이번 리밸런싱의 핵심 목적 요약 (예: 고위험 자산 축소 및 균형 재잡기)
                                2. 가장 시급하게 처리해야 할 종목 1~2개와 이유
                                3. 현재 시장 리스크와 연계된 최종 조언
                                한국어로 답변하라."""
                                rebal_advice = reporter.model.generate_content(prompt).text
                                st.markdown(rebal_advice)
                else:
                    st.error("시장 데이터를 가져올 수 없습니다.")

        st.markdown("---")
        if st.button("포트폴리오 초기화"):
            loader.save_portfolio([])
            st.rerun()

elif menu == "🔍 종목 스크리너":
    st.title("🔍 퀀트 종목 스크리너")
    st.markdown("---")
    
    st.sidebar.header("⚙️ 스크리닝 설정")
    market_type = st.sidebar.radio("대상 시장", ["US (S&P500)", "KR (KOSPI 200)"])
    
    # 레짐 수동 선택 또는 자동 연동 (여기선 간단히 선택지로 제공)
    regime_choice = st.sidebar.selectbox("현재 시장 레짐 (가중치 반영)", 
                                        ["Risk-on (안정 성장)", "Risk-off (위험 관리)", "Transition (국면 전환)"])
    
    market_name_key = "us"
    if market_type == "US (S&P500)":
        with st.spinner('S&P 500 종목 리스트를 가져오는 중...'):
            target_tickers = loader.get_sp500_tickers()
            market_name_key = "us"
    elif market_type == "KR (KOSPI 200)":
        with st.spinner('KOSPI 200 종목 리스트를 가져오는 중...'):
            target_tickers = loader.get_kospi200_tickers()
            market_name_key = "kr"
        
    st.subheader(f"📊 {market_type} 주요 종목 분석")
    
    # 데이터 수집 진행률 표시를 위한 자리 만들기
    progress_bar = st.progress(0)
    status_text = st.empty()

    def update_progress(current, total, ticker):
        progress = min(current / total, 1.0)
        progress_bar.progress(progress)
        status_text.text(f"데이터 수집 중: {ticker} ({current}/{total})")

    with st.spinner('종목 기본적 분석 데이터를 불러오는 중...'):
        fund_df = loader.get_stock_fundamentals(target_tickers, progress_callback=update_progress, market_name=market_name_key)
        # 수집 완료 후 UI 정리
        progress_bar.empty()
        status_text.empty()
        
    if not fund_df.empty:
        # 스크리닝 결과 캐싱 (클릭 시 rerun 대응)
        cache_key = f"screened_{market_type}_{regime_choice}"
        if cache_key not in st.session_state:
            with st.spinner('팩터 스코어링 및 랭킹 산출 중...'):
                st.session_state[cache_key] = screener.run_screening(fund_df, regime_choice)
        
        screened_df = st.session_state[cache_key]
            
        # 결과 표시
        st.write(f"**현재 레짐:** {regime_choice}")
        st.info(f"선택된 레짐에 따라 {'성장성/모멘텀' if 'Risk-on' in regime_choice else '퀄리티/밸류' if 'Risk-off' in regime_choice else '밸류/퀄리티'} 가중치가 높게 적용되었습니다.")
        
        with st.expander("📊 퀀트 점수 산출 로직 상세 가이드", expanded=False):
            st.markdown(f"""
            ### 1. 모멘텀 점수 (Momentum Score)
            - **계산 방식**: 분석 대상 전체 종목의 최근 수익률(미국 1년, 한국 6개월)을 비교하여 **백분위 순위(Percentile)**를 매깁니다.
            - **의미**: 100점에 가까울수록 해당 시장 내에서 가장 강한 상승 추세를 보이는 종목입니다.
            
            ### 2. 종합 점수 (Final Score)
            - **개요**: 4대 핵심 팩터 점수를 현재 시장 레짐인 **'{regime_choice}'**에 최적화된 가중치로 합산한 점수입니다.
            - **팩터 구성**:
                - **Value**: PER, PBR의 백분위 합산 (적자 기업은 최하위 페널티 부여)
                - **Quality**: ROE, 영업이익률의 백분위 합산
                - **Growth**: 매출 성장률의 백분위 순위
                - **Momentum**: 가격 상승 강도의 백분위 순위
            - **현재 레짐 가중치**:
                - 퀄리티: `{screener.weights[regime_choice]['quality']*100:.0f}%` / 밸류: `{screener.weights[regime_choice]['value']*100:.0f}%`
                - 성장성: `{screener.weights[regime_choice]['growth']*100:.0f}%` / 모멘텀: `{screener.weights[regime_choice]['momentum']*100:.0f}%`
            """)

        # 표시용 컬럼 안전하게 선택 (컬럼이 없을 경우를 대비)
        available_cols = screened_df.columns.tolist()
        requested_cols = ['Ticker', 'Name', 'Sector', 'FinalScore', 'PER', 'PBR', 'ROE', 'Momentum']
        display_cols = [c for c in requested_cols if c in available_cols]
        
        # 포맷팅할 컬럼들도 존재하는 것만 추려냄
        format_dict = {
            'FinalScore': '{:.1f}',
            'PER': '{:.2f}',
            'PBR': '{:.2f}',
            'ROE': '{:.1f}%',
            'Momentum': '{:+.1f}%'
        }
        actual_format = {k: v for k, v in format_dict.items() if k in display_cols}

        # 행 선택 기능이 통합된 데이터프레임
        event = st.dataframe(
            screened_df[display_cols].style.format(actual_format).background_gradient(
                subset=[c for c in ['FinalScore', 'Momentum'] if c in display_cols], 
                cmap='RdYlGn'
            ),
            width="stretch",
            column_config={
                "FinalScore": st.column_config.NumberColumn("종합 점수", help="레짐별 가중치가 적용된 0~100점 사이의 최종 퀀트 점수입니다."),
                "PER": st.column_config.NumberColumn("PER", help="주가수익비율. 적자 기업은 랭킹에서 페널티를 받습니다."),
                "PBR": st.column_config.NumberColumn("PBR", help="주가순자산비율. 자산 가치 대비 저평가 여부를 나타냅니다."),
                "ROE": st.column_config.NumberColumn("ROE", help="자기자본이익률. 기업의 자본 효율성을 측정합니다."),
                "Momentum": st.column_config.NumberColumn("모멘텀", help="최근 수익률의 백분위 순위가 반영된 점수입니다.")
            },
            on_select="rerun",
            selection_mode="single-row",
            key="screener_main_table"
        )
        
        # 테이블에서 선택된 티커 확인
        if event and len(event.selection.rows) > 0:
            selected_row_idx = event.selection.rows[0]
            selected_ticker = screened_df.iloc[selected_row_idx]['Ticker']
            selected_name = screened_df.iloc[selected_row_idx]['Name']
            
            # 1. 티커 관련 상태 강제 초기화
            st.session_state[f"lppl_{selected_ticker}"] = None
            st.session_state[f"news_{selected_ticker}"] = None
            st.session_state[f"ai_report_{selected_ticker}"] = None
            if f"tv_symbol_{selected_ticker}" in st.session_state:
                del st.session_state[f"tv_symbol_{selected_ticker}"]
            
            # 2. 글로벌 팝업 티커 설정
            st.session_state.active_ticker = selected_ticker
            
            # 3. 테이블 선택 상태 지연 초기화 설정
            st.session_state.should_clear_screener = True
            
            # 안내 및 재실행
            st.success(f"📍 {selected_name} ({selected_ticker}) 분석 중...")
            st.rerun()

        st.caption("💡 표의 행이나 셀을 클릭하면 해당 종목의 상세 분석 팝업이 열립니다.")

        # Phase 4: 추천 포지션 사이징 섹션 (실전화 개편)
        st.markdown("---")
        st.subheader("🎯 실전 포지션 사이징 가이드")
        st.markdown("""
        선정된 상위 종목들에 대해 **리스크 패리티(Risk Parity)**와 **LPPL 버블 위험**을 결합하여 최적의 투자 설계도를 제공합니다.
        - **리스크 패리티**: 변동성(위험)이 큰 종목은 비중을 줄이고, 변동성이 낮은 종목은 늘려 전체 포트폴리오의 리스크를 균등하게 맞춥니다.
        - **매수 설계**: 입력하신 예산에 맞춰 실제 매수 수량과 손절/목표가를 계산합니다.
        """)
        
        # 투자 예산 입력
        currency_unit = "원" if market_name_key == "kr" else "달러"
        default_cap = 10000000 if market_name_key == "kr" else 10000
        total_capital = st.number_input(f"💰 총 투자 예산 ({currency_unit})", min_value=0, value=default_cap, step=100000 if market_name_key == "kr" else 100)
        
        if st.button("⚖️ 실전 매수 가이드 산출", width="stretch"):
            with st.spinner('종목별 변동성 및 리스크 정밀 분석 중...'):
                # 1. 현재 시장 환경 분석 (전체 비중 도출)
                ref_index = "^GSPC" if market_name_key == "us" else "^KS11"
                ref_data = loader.get_market_history(ref_index, period="2y")
                
                if ref_data is not None:
                    ref_prices = ref_data['Close']
                    ref_lppl = engine.run_lppl_fit(ref_prices, num_iterations=20)
                    ref_attr = engine.calculate_attractiveness(ref_prices, None)
                    
                    total_weight_pct = engine.calculate_target_weight(
                        ref_attr['score'] if ref_attr else 50,
                        ref_lppl['danger_score'] if ref_lppl else 0
                    )
                    
                    # 2. 개별 종목 실전 비중 및 수량 계산
                    # 상위 10개 종목 대상
                    weighted_df = screener.calculate_stock_weights(screened_df.head(10), total_weight_pct, loader, total_capital)
                    
                    # 3. 결과 표시
                    st.success(f"현재 시장 환경 기준 권장 주식 총 비중: **{total_weight_pct}%** (총 {total_capital * total_weight_pct / 100:,.0f} {currency_unit} 투입)")
                    
                    # 시각적 가이드 컬럼 구성
                    display_rebal = weighted_df[['Ticker', 'Name', 'RecWeight', 'Shares', 'StopLoss', 'TargetPrice', 'DangerScore']].copy()
                    display_rebal.columns = ['티커', '종목명', '추천비중', '매수수량', '손절가', '목표가', '위험도']
                    
                    st.dataframe(
                        display_rebal.style.format({
                            '추천비중': '{:.1f}%',
                            '매수수량': '{:,.0f}주',
                            '손절가': '{:,.2f}',
                            '목표가': '{:,.2f}',
                            '위험도': '{:.0f}'
                        }).background_gradient(subset=['위험도'], cmap='Reds').background_gradient(subset=['추천비중'], cmap='Blues'),
                        width="stretch"
                    )
                    
                    st.caption(f"💡 **손절가**: 최근 변동성의 2배 하락 시점 / **목표가**: 리스크 대비 보상비 1:2 기준 (예상가)")
                else:
                    st.error("시장 지수 데이터를 가져올 수 없어 비중을 산출하지 못했습니다.")

        # 팩터별 분석 차트
        st.markdown("---")
        st.subheader("📈 다차원 시각화 분석")
        
        # 종목 식별 개선: 이름 뒤에 티커 병기 (중복 방지)
        # Name이나 Ticker 컬럼이 없을 경우를 대비해 방어적으로 생성
        if 'Name' not in screened_df.columns:
            screened_df['Name'] = screened_df['Ticker'] if 'Ticker' in screened_df.columns else "Unknown"
        if 'Ticker' not in screened_df.columns:
            screened_df['Ticker'] = "Unknown"
            
        screened_df['DisplayName'] = screened_df['Name'].astype(str) + " (" + screened_df['Ticker'].astype(str) + ")"
        
        # 1. 섹터별 분포 트리맵 (Top-Down View)
        st.markdown("#### 🏗️ 섹터별 점수 및 시총 분포")
        
        # 결측치 처리 (Plotly Treemap 오류 방지)
        tree_df = screened_df.copy()
        required_vis_cols = ['Sector', 'MarketCap', 'FinalScore', 'PER', 'ROE', 'Momentum']
        for col in required_vis_cols:
            if col not in tree_df.columns:
                tree_df[col] = 0 if col != 'Sector' else 'Unknown Sector'
            
        tree_df['Sector'] = tree_df['Sector'].fillna('Unknown Sector').replace('', 'Unknown Sector')
        tree_df['MarketCap'] = pd.to_numeric(tree_df['MarketCap'], errors='coerce').fillna(0)
        tree_df['FinalScore'] = pd.to_numeric(tree_df['FinalScore'], errors='coerce').fillna(0)

        fig_tree = px.treemap(tree_df, 
                             path=[px.Constant("Market"), 'Sector', 'DisplayName'], 
                             values='MarketCap',
                             color='FinalScore', 
                             hover_data=[c for c in ['PER', 'ROE', 'Momentum'] if c in tree_df.columns],
                             color_continuous_scale='RdYlGn',
                             title="섹터/종목별 점수 분포 (박스 크기: 시가총액)",
                             template="plotly_dark")
        fig_tree.update_layout(margin=dict(t=30, l=10, r=10, b=10))
        st.plotly_chart(fig_tree, width="stretch")

        c1, c2 = st.columns([1.2, 1])
        
        with c1:
            # 2. 상위 종목 팩터 레이더 차트 (Competitive Analysis)
            st.markdown("#### 🎯 상위 3개 종목 팩터 프로필")
            top_3 = screened_df.head(3)
            categories = ['Value', 'Quality', 'Growth', 'Momentum']
            
            fig_radar = go.Figure()
            for i, row in top_3.iterrows():
                fig_radar.add_trace(go.Scatterpolar(
                    r=[row['score_value'], row['score_quality'], row['score_growth'], row['score_momentum']],
                    theta=categories,
                    fill='toself',
                    name=row['DisplayName']
                ))
            
            fig_radar.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                showlegend=True,
                template="plotly_dark",
                height=400,
                margin=dict(t=40, b=40, l=40, r=40)
            )
            st.plotly_chart(fig_radar, width="stretch")
            
        with c2:
            # 3. 종합 점수 랭킹 바 차트
            st.markdown("#### 🏆 종합 점수 랭킹 (Top 15)")
            fig_bar = px.bar(screened_df.head(15).sort_values('FinalScore'), 
                            x='FinalScore', y='DisplayName', orientation='h',
                            color='FinalScore', color_continuous_scale='Greens',
                            template="plotly_dark", height=400)
            fig_bar.update_layout(margin=dict(t=20, b=20, l=10, r=10), yaxis_title=None)
            st.plotly_chart(fig_bar, width="stretch")

        # 4. 효율성 평면 (Scatter)
        st.markdown("#### 📊 가치 vs 효율성 평면")
        
        # Plotly Express 데이터 전처리 (결측치 및 0 이하 값 처리)
        scatter_df = screened_df.copy()
        for col in ['PER', 'ROE', 'MarketCap', 'Sector', 'DisplayName']:
            if col not in scatter_df.columns:
                scatter_df[col] = 0 if col != 'Sector' and col != 'DisplayName' else 'Unknown'
            else:
                if col in ['PER', 'ROE', 'MarketCap']:
                    scatter_df[col] = pd.to_numeric(scatter_df[col], errors='coerce').fillna(0)
        
        # Plotly size 파라미터는 반드시 양수여야 함
        scatter_df['SizeDisplay'] = scatter_df['MarketCap'].apply(lambda x: max(x, 1e-6))
        
        fig_scatter = px.scatter(scatter_df, x='PER', y='ROE', size='SizeDisplay', color='Sector', 
                                hover_name='DisplayName', title="PER vs ROE (버블 사이즈: 시총)",
                                template="plotly_dark", height=500)
        # 축 범위 조정 (이상치 영향 최소화)
        per_max = scatter_df['PER'].quantile(0.95)
        roe_max = scatter_df['ROE'].quantile(0.95)
        fig_scatter.update_xaxes(range=[0, per_max * 1.2] if per_max > 0 else None)
        fig_scatter.update_yaxes(range=[scatter_df['ROE'].min(), roe_max * 1.2] if roe_max > 0 else None)
        
        st.plotly_chart(fig_scatter, width="stretch")

        # --- 백테스트 시뮬레이션 섹션 ---
        st.markdown("---")
        st.subheader("📊 퀀트 전략 과거 성과 시뮬레이션")
        st.markdown("""
        현재 선택된 **레짐 가중치**를 바탕으로, **정확히 1년 전**에 선정된 상위 10개 종목에 투자했을 때의 성과를 확인합니다.
        (한국: 펀더멘털+모멘텀 복합 / 미국: 모멘텀 중심)
        """)
        
        if st.button("🚀 1년 전 성과 백테스트 실행", width="stretch"):
            with st.spinner('1년 전 시장 데이터를 분석하고 성과를 계산 중...'):
                top_10_hist, perf_df = backtester.run_backtest(market_type, regime_choice)
                
                if top_10_hist is not None and perf_df is not None:
                    # 리스크 메트릭 계산
                    def calculate_metrics(series):
                        returns = series.pct_change().dropna()
                        sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() != 0 else 0
                        
                        cumulative = series
                        peak = cumulative.cummax()
                        drawdown = (cumulative - peak) / peak
                        mdd = drawdown.min() * 100
                        return sharpe, mdd

                    p_sharpe, p_mdd = calculate_metrics(perf_df['Portfolio'])
                    b_sharpe, b_mdd = calculate_metrics(perf_df['Benchmark'])
                    
                    # 성과 요약
                    final_perf = perf_df.iloc[-1]
                    port_ret = (final_perf['Portfolio'] - 1) * 100
                    bm_ret = (final_perf['Benchmark'] - 1) * 100
                    alpha = port_ret - bm_ret
                    
                    st.markdown("#### 📈 성과 및 리스크 분석 요약")
                    m1, m2, m3 = st.columns(3)
                    m1.metric("누적 수익률", f"{port_ret:+.2f}%", f"{alpha:+.2f}% (vs BM)")
                    m2.metric("샤프 지수 (위험 대비 수익)", f"{p_sharpe:.2f}", f"{p_sharpe - b_sharpe:+.2f} (vs BM)")
                    m3.metric("최대 낙폭 (MDD)", f"{p_mdd:.1f}%", f"{p_mdd - b_mdd:+.1f}% (vs BM)")
                    
                    # 수익률 차트
                    fig_perf = go.Figure()
                    fig_perf.add_trace(go.Scatter(x=perf_df.index, y=(perf_df['Portfolio']-1)*100, name='전략 (Top 10)', line=dict(color='cyan', width=3)))
                    fig_perf.add_trace(go.Scatter(x=perf_df.index, y=(perf_df['Benchmark']-1)*100, name='벤치마크 (Index)', line=dict(color='gray', dash='dash')))
                    fig_perf.update_layout(title="누적 수익률 비교 (1년)", yaxis_title="수익률 (%)", template="plotly_dark", height=450)
                    st.plotly_chart(fig_perf, width="stretch")
                    
                    # 선정된 종목 리스트
                    with st.expander("📌 1년 전 선정되었던 Top 10 종목 보기"):
                        st.table(top_10_hist[['Ticker', 'Name', 'FinalScore', 'Momentum']])
                else:
                    st.error("백테스트를 위한 과거 데이터를 충분히 확보하지 못했습니다. (미국 주식은 티커가 너무 많아 시간이 소요될 수 있습니다)")
    else:
        st.error("데이터를 불러오지 못했습니다. 티커 설정을 확인해주세요.")

elif menu == "💎 펀더멘털 가치평가":
    st.title("💎 펀더멘털 가치평가 (Scenario Analysis)")
    st.markdown("""
    설정된 **가치평가 매트릭스**를 바탕으로, 주요 종목의 적정 주가 밴드와 현재 위치를 정량적으로 분석합니다.
    - **Bear**: 하락 시나리오에서의 강력한 지지선 (보수적 멀티플 적용)
    - **Base**: 현재 펀더멘털과 시장 평균을 반영한 적정가
    - **Bull**: 성장 가속 및 낙관적 시장 환경에서의 목표가
    """)
    
    # 관심 종목 리스트 (matrix에 정의된 종목들)
    tickers = list(engine.valuation_matrix.keys())
    
    if not tickers:
        st.warning("설정된 가치평가 종목이 없습니다. `config/valuation_matrix.json`을 확인해주세요.")
    else:
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            st.markdown("가치평가 대상: " + ", ".join(tickers))
        with c2:
            valuation_mode = st.radio("밸류에이션 모드", ["Manual Matrix", "Dynamic Historical"], horizontal=True)
        with c3:
            force_refresh = st.button("🔄 데이터 새로고침", use_container_width=True)

        # 데이터 로드
        with st.spinner('종목별 펀더멘털 데이터 수집 중...'):
            fund_df = loader.get_stock_fundamentals(tickers, market_name="us", force_download=force_refresh)
            if force_refresh:
                st.success("최신 데이터로 갱신되었습니다!")
            
        if fund_df is not None and not fund_df.empty:
            found_count = 0
            for i, ticker in enumerate(tickers):
                row = fund_df[fund_df['Ticker'].str.upper() == ticker.upper()]
                if not row.empty:
                    found_count += 1
                    row = row.iloc[0]
                    fwd_eps = row.get('ForwardEPS', 0)
                    curr_price = row.get('Price', 0)
                    
                    # 1. 밸류에이션 시나리오 결정 (수동 vs 자동)
                    if valuation_mode == "Manual Matrix":
                        res = engine.calculate_valuation_scenarios(ticker, fwd_eps, curr_price)
                        mode_label = "(Matrix 기준)"
                    else:
                        with st.spinner(f"{ticker} 역사적 PER 분석 중..."):
                            hist_bands = engine.calculate_historical_per_bands(ticker)
                            if hist_bands:
                                # 자동 산출된 PER를 Forward EPS에 적용
                                scenarios = {
                                    'bull': fwd_eps * hist_bands['bull'],
                                    'base': fwd_eps * hist_bands['base'],
                                    'bear': fwd_eps * hist_bands['bear']
                                }
                                # 현재가 위치 계산 (%)
                                if scenarios['bull'] > scenarios['bear']:
                                    pos = (curr_price - scenarios['bear']) / (scenarios['bull'] - scenarios['bear']) * 100
                                else: pos = 50.0
                                
                                res = {
                                    'scenarios': scenarios,
                                    'current_price': curr_price,
                                    'position_pct': pos,
                                    'ticker_name': row.get('Name', ticker),
                                    'hist_bands': hist_bands # 상세 데이터 포함
                                }
                                mode_label = f"(역사적 5년 PER 기준: {hist_bands['base']:.1f}x)"
                            else:
                                res = None
                                st.error(f"{ticker}의 역사적 데이터를 분석할 수 없어 Manual Matrix로 대체합니다.")
                                res = engine.calculate_valuation_scenarios(ticker, fwd_eps, curr_price)
                                mode_label = "(Matrix로 자동 전환)"

                    if res:
                        s = res['scenarios']
                        pos = res['position_pct']
                        
                        st.markdown(f"### {res['ticker_name']} ({ticker}) {mode_label}")
                        
                        # 3분할 표시
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Bear Case", f"${s['bear']:,.1f}")
                        m2.metric("Base Case", f"${s['base']:,.1f}")
                        m3.metric("Bull Case", f"${s['bull']:,.1f}")
                        
                        st.write(f"현재가: **${curr_price:,.2f}** (밴드 내 위치: **{pos:.1f}%**)")
                        
                        # 차트 시각화
                        hist_data = loader.get_market_history(ticker, period="1y")
                        if hist_data is not None and not hist_data.empty:
                            fig_val = go.Figure()
                            fig_val.add_trace(go.Scatter(x=hist_data.index, y=hist_data['Close'], 
                                                       name='Price', line=dict(color='white', width=1.5), opacity=0.7))
                            
                            fig_val.add_hline(y=s['bull'], line_dash="dash", line_color="#ff4b4b", 
                                            annotation_text=f"Bull ({s['bull']:,.0f})", annotation_position="top right")
                            fig_val.add_hline(y=s['base'], line_dash="dot", line_color="#31333f", 
                                            annotation_text=f"Base ({s['base']:,.0f})", annotation_position="top right")
                            fig_val.add_hline(y=s['bear'], line_dash="dash", line_color="#00c04b", 
                                            annotation_text=f"Bear ({s['bear']:,.0f})", annotation_position="bottom right")
                            
                            fig_val.add_hrect(y0=s['bear'], y1=s['base'], fillcolor="green", opacity=0.05, line_width=0)
                            fig_val.add_hrect(y0=s['base'], y1=s['bull'], fillcolor="orange", opacity=0.05, line_width=0)
                            
                            fig_val.add_trace(go.Scatter(x=[hist_data.index[-1]], y=[curr_price],
                                                       mode='markers+text', name='Current',
                                                       text=[f"  ${curr_price:,.1f}"], textposition="middle right",
                                                       marker=dict(color='yellow', size=10, symbol='diamond')))

                            fig_val.update_layout(title=f"{ticker} 가치평가 밴드 추이 {mode_label}", template="plotly_dark", height=450, yaxis_title="Price ($)", showlegend=False)
                            st.plotly_chart(fig_val, use_container_width=True)
                        
                        # 자동 모드일 때 추가 통계 제공
                        if valuation_mode == "Dynamic Historical" and 'hist_bands' in res:
                            with st.expander(f"📊 {ticker} 역사적 PER 분포 상세"):
                                h = res['hist_bands']
                                st.write(f"- **최근 5년 PER 범위:** {h['min']:.1f}x ~ {h['max']:.1f}x")
                                st.write(f"- **현재(Trailing) PER:** {h['current']:.1f}x")
                                st.write(f"- **적용된 밴드 (25% / 50% / 75%):** {h['bear']:.1f}x / {h['base']:.1f}x / {h['bull']:.1f}x")
                        
                        if curr_price <= s['bear']:
                            st.success(f"🎯 **매수 기회:** {ticker}가 역사적/수동 저평가 임계점에 도달했습니다.")
                        elif curr_price >= s['bull']:
                            st.error(f"🚫 **주의:** {ticker}가 역사적/수동 고평가 임계점을 상회했습니다.")
                            
                        st.markdown("---")
            
            if found_count == 0:
                st.warning("설정된 종목들을 데이터에서 찾을 수 없습니다. 티커명을 확인해주세요.")
                st.write("불러온 데이터 티커 목록:", fund_df['Ticker'].tolist())
        else:
            st.error("종목 데이터를 불러오는 데 실패했습니다. 잠시 후 다시 시도하거나 '데이터 새로고침'을 눌러주세요.")

elif menu == "🚀 실시간 마켓 모니터":
    st.title("🚀 실시간 마켓 모니터 (5분봉)")
    st.markdown("TradingView 실시간 엔진을 활용한 초정밀 시장 모니터링 보드입니다.")

    # --- 1섹션: 지수 선물 (Futures) ---
    st.subheader("📊 주요 지수 선물")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.info("나스닥 100 (US100)")
        tradingview_widget("CAPITALCOM:US100", height=450)
    with col2:
        st.info("S&P 500 (US500)")
        tradingview_widget("CAPITALCOM:US500", height=450)
    with col3:
        st.info("다우 30 (US30)")
        tradingview_widget("CAPITALCOM:US30", height=450)

    # --- 2섹션: 매크로 및 공포 지수 ---
    st.markdown("---")
    st.subheader("🌐 실시간 매크로 & 공포 지수")
    col4, col5, col6 = st.columns(3)

    with col4:
        st.warning("미국채 10년물 수익률 (10Y)")
        tradingview_widget("BLACKBULL:US10Y", height=400)
    with col5:
        st.warning("미국채 2년물 수익률 (2Y)")
        tradingview_widget("BLACKBULL:US02Y", height=400)
    with col6:
        st.error("변동성 지수 (VIX)")
        tradingview_widget("CAPITALCOM:VIX", height=400)

    # --- 3섹션: 통화 및 원자재 ---
    st.markdown("---")
    st.subheader("💱 외환 및 핵심 지표")
    col7, col8, col9 = st.columns(3)

    with col7:
        st.success("원/달러 환율 (USDKRW)")
        tradingview_widget("FX_IDC:USDKRW", height=400)
    with col8:
        st.success("달러 인덱스 (DXY)")
        tradingview_widget("CAPITALCOM:DXY", height=400)
    with col9:
        st.success("비트코인 (BTC/USD)")
        tradingview_widget("BINANCE:BTCUSDT", height=400)

elif menu == "🛠️ 관리자 시스템 로그":
    st.title("📋 시스템 로그 관리자")
    
    # 로그 디렉토리 설정
    log_dir = "logs"
    log_files = sorted([f for f in os.listdir(log_dir) if f.endswith(".log")], reverse=True) if os.path.exists(log_dir) else []

    if not log_files:
        st.info("기록된 로그 파일이 없습니다.")
    else:
        # 파일 선택 및 검색 인터페이스
        col1, col2 = st.columns([1, 1])
        with col1:
            selected_log = st.selectbox("로그 파일 선택", log_files)
        with col2:
            search_query = st.text_input("🔍 로그 검색 (키워드)", "")

        log_path = os.path.join(log_dir, selected_log)

        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                
                # 검색 필터링
                if search_query:
                    filtered_lines = [line for line in lines if search_query.lower() in line.lower()]
                    st.caption(f"검색 결과: {len(filtered_lines)}개 / 전체 {len(lines)}개")
                else:
                    filtered_lines = lines
                
                # 정렬 및 출력
                sort_order = st.radio("정렬 순서", ["최신순", "과거순"], horizontal=True)
                display_lines = filtered_lines[::-1] if sort_order == "최신순" else filtered_lines

                if not display_lines:
                    st.warning("조건에 맞는 로그가 없습니다.")
                else:
                    max_display = 500
                    display_text = "".join(display_lines[:max_display])
                    if len(display_lines) > max_display:
                        st.info(f"표시 제한: 상위 {max_display}줄만 표시됩니다.")
                    st.code(display_text, language="log")

                if st.button("🗑️ 현재 로그 파일 삭제"):
                    os.remove(log_path)
                    st.success("삭제되었습니다.")
                    st.rerun()

            except Exception as e:
                st.error(f"로그 읽기 오류: {e}")

st.markdown("---")

# --- 공통 정보 및 팝업 핸들러 (마지막에 배치하여 최신 상태 반영) ---

# 1. 환율 정보 (사이드바 하단 표시)
st.sidebar.markdown("---")
st.sidebar.metric("원/달러 환율", f"{current_usd_krw:,.1f}원")

# 2. 팝업 호출 대기 티커 확인 및 실행
if 'active_ticker' not in st.session_state:
    st.session_state.active_ticker = None

if st.session_state.active_ticker:
    # 상세 분석 다이얼로그 호출
    show_stock_details(st.session_state.active_ticker)

st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

