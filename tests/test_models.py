import pytest
import pandas as pd
import numpy as np
from modules.models import (
    AnalysisModel, QuantScreener, resolve_regime_choice,
    filter_screener_df, build_saveticker_url,
)


def _build_ohlc(closes, high=100.0, low=0.0, start="2023-01-01"):
    """High/Low를 고정해 Fast%K = Close, Williams %R = Close - 100 이 되도록 만든
    테스트 전용 OHLC 데이터. 신호 판정 로직을 손으로 검증 가능하게 하기 위함."""
    dates = pd.date_range(start=start, periods=len(closes))
    return pd.DataFrame({
        'High': [high] * len(closes),
        'Low': [low] * len(closes),
        'Close': closes,
    }, index=dates)

@pytest.fixture
def mock_price_data():
    """테스트용 가상 가격 데이터 생성 (250일치)"""
    dates = pd.date_range(start="2023-01-01", periods=250)
    # 완만한 상승 추세 데이터
    prices = np.linspace(100, 150, 250) + np.random.normal(0, 1, 250)
    return pd.Series(prices, index=dates)

def test_analysis_model_init():
    model = AnalysisModel()
    assert model.config is not None
    assert model.lppl_engine is not None

def test_calculate_breadth_score():
    model = AnalysisModel()
    # 10개 섹터 중 7개가 MA50 상회하도록 설정
    data = {}
    for i in range(10):
        if i < 7:
            data[f"S{i}"] = np.linspace(100, 110, 60) # 상승 중
        else:
            data[f"S{i}"] = np.linspace(110, 100, 60) # 하락 중
    df = pd.DataFrame(data)
    score = model.calculate_breadth_score(df)
    assert score == 70.0

def test_calculate_liquidity_score():
    model = AnalysisModel()
    # 가상 데이터 (모두 동일하게 21일치)
    dxy = pd.Series(np.linspace(100, 95, 21)) # 하락 (+)
    us10y = pd.Series(np.linspace(4.0, 3.5, 21)) # 하락 (+)
    gold = pd.Series(np.linspace(1800, 1900, 21)) # 상승 (+)
    btc = pd.Series(np.linspace(20000, 25000, 21)) # 상승 (+)
    
    score = model.calculate_liquidity_score(dxy, us10y, gold, btc)
    assert score > 0 # 유동성 개선 국면이므로 양수여야 함

def test_calculate_target_weight():
    model = AnalysisModel()
    # 매력도 60, 위험도 30 (정상) -> 100% 반영
    w1 = model.calculate_target_weight(60.0, 30.0)
    assert w1 == 60.0

    # 매력도 60, 위험도 75 (경고) -> 페널티 적용 (0.5배 등)
    w2 = model.calculate_target_weight(60.0, 75.0)
    assert w2 < 60.0

    # 매력도 60, 위험도 90 (위험) -> 최대 20% 제한
    w3 = model.calculate_target_weight(60.0, 90.0)
    assert w3 <= 20.0


def _build_two_sector_df():
    """
    Sector A: PER 10, 20, 30 (종목 A1, A2, A3)
    Sector B: PER 5, 15, 25 (종목 B1, B2, B3)
    전체 풀 기준 PER 오름차순: B1(5) < A1(10) < B2(15) < A2(20) < B3(25) < A3(30)
    -> A1은 전체 6개 중 2번째로 저PER(전체 기준 상위권)이지만,
       Sector A 안에서는 가장 저PER(그룹 내 1위)이므로 sector_neutral일 때 더 높은 score_value를 받아야 한다.
    """
    return pd.DataFrame({
        'Ticker': ['A1', 'A2', 'A3', 'B1', 'B2', 'B3'],
        'Sector': ['A', 'A', 'A', 'B', 'B', 'B'],
        'PER': [10.0, 20.0, 30.0, 5.0, 15.0, 25.0],
        'PBR': [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        'ROE': [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
        'ProfitMargin': [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
        'RevenueGrowth': [5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
        'Momentum': [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    })


def test_run_screening_default_matches_full_pool_ranking():
    screener = QuantScreener()
    df = _build_two_sector_df()

    result = screener.run_screening(df, "Transition (국면 전환)")

    # 전체 풀 기준: B1(PER 5)이 가장 저PER이므로 score_value가 가장 높아야 함
    b1_score = result.loc[result['Ticker'] == 'B1', 'score_value'].iloc[0]
    a1_score = result.loc[result['Ticker'] == 'A1', 'score_value'].iloc[0]
    assert b1_score > a1_score


def test_run_screening_sector_neutral_ranks_within_group():
    screener = QuantScreener()
    df = _build_two_sector_df()

    result = screener.run_screening(df, "Transition (국면 전환)", sector_neutral=True)

    # 섹터 중립화: A1(Sector A 내 최저 PER)이 A2, A3보다 score_value가 높아야 함
    a1_score = result.loc[result['Ticker'] == 'A1', 'score_value'].iloc[0]
    a2_score = result.loc[result['Ticker'] == 'A2', 'score_value'].iloc[0]
    a3_score = result.loc[result['Ticker'] == 'A3', 'score_value'].iloc[0]
    assert a1_score > a2_score > a3_score

    # Sector A 내 최저 PER(A1)과 Sector B 내 최저 PER(B1)은 각자 그룹의 1등이므로 동점(100점)이어야 함
    b1_score = result.loc[result['Ticker'] == 'B1', 'score_value'].iloc[0]
    assert a1_score == pytest.approx(b1_score)


def test_run_screening_sector_neutral_without_sector_column_falls_back():
    screener = QuantScreener()
    df = _build_two_sector_df().drop(columns=['Sector'])

    # Sector 컬럼이 없어도 예외 없이 전체 풀 기준으로 폴백해야 함
    result = screener.run_screening(df, "Transition (국면 전환)", sector_neutral=True)

    b1_score = result.loc[result['Ticker'] == 'B1', 'score_value'].iloc[0]
    a1_score = result.loc[result['Ticker'] == 'A1', 'score_value'].iloc[0]
    assert b1_score > a1_score


def test_run_screening_sector_neutral_handles_missing_sector_value():
    screener = QuantScreener()
    df = _build_two_sector_df()
    df.loc[df['Ticker'] == 'A2', 'Sector'] = None  # missing sector value

    result = screener.run_screening(df, "Transition (국면 전환)", sector_neutral=True)

    a2_score = result.loc[result['Ticker'] == 'A2', 'score_value'].iloc[0]
    assert pd.notna(a2_score)


def test_run_screening_sector_neutral_missing_sector_uses_full_pool_rank_not_auto_top_score():
    screener = QuantScreener()
    df = _build_two_sector_df()
    df.loc[df['Ticker'] == 'A2', 'Sector'] = None  # A2 has no sector info; PER=20, mid-pack pool-wide

    result = screener.run_screening(df, "Transition (국면 전환)", sector_neutral=True)
    full_pool_result = screener.run_screening(_build_two_sector_df(), "Transition (국면 전환)", sector_neutral=False)

    a2_sector_neutral_score = result.loc[result['Ticker'] == 'A2', 'score_value'].iloc[0]
    a2_full_pool_score = full_pool_result.loc[full_pool_result['Ticker'] == 'A2', 'score_value'].iloc[0]

    # A2's missing-sector row should match the full-pool computation, not get an automatic 100
    assert a2_sector_neutral_score == pytest.approx(a2_full_pool_score)
    assert a2_sector_neutral_score < 100.0


def test_run_screening_sector_neutral_na_string_sector_uses_full_pool_rank():
    """DataLoader가 실제로 채우는 'N/A' 문자열 결측 섹터도 NaN과 동일하게 처리되어야 한다."""
    screener = QuantScreener()
    df = _build_two_sector_df()
    df.loc[df['Ticker'] == 'A2', 'Sector'] = 'N/A'  # DataLoader의 실제 결측 센티널 문자열

    result = screener.run_screening(df, "Transition (국면 전환)", sector_neutral=True)
    full_pool_result = screener.run_screening(_build_two_sector_df(), "Transition (국면 전환)", sector_neutral=False)

    a2_sector_neutral_score = result.loc[result['Ticker'] == 'A2', 'score_value'].iloc[0]
    a2_full_pool_score = full_pool_result.loc[full_pool_result['Ticker'] == 'A2', 'score_value'].iloc[0]

    assert a2_sector_neutral_score == pytest.approx(a2_full_pool_score)
    assert a2_sector_neutral_score < 100.0


def test_resolve_regime_choice_uses_auto_by_default():
    result = resolve_regime_choice("Risk-off (위험 관리)", False, "Transition (국면 전환)")
    assert result == "Risk-off (위험 관리)"


def test_resolve_regime_choice_manual_override_wins():
    result = resolve_regime_choice("Risk-off (위험 관리)", True, "Risk-on (안정 성장)")
    assert result == "Risk-on (안정 성장)"


def test_resolve_regime_choice_falls_back_to_manual_when_auto_missing():
    result = resolve_regime_choice(None, False, "Transition (국면 전환)")
    assert result == "Transition (국면 전환)"


class _FakeLoader:
    def __init__(self, histories):
        self._histories = histories

    def get_market_history(self, ticker, period="1y"):
        return self._histories.get(ticker)


def _flat_price_history(periods=25, price=100.0):
    dates = pd.date_range(start="2023-01-01", periods=periods)
    return pd.DataFrame({'Close': [price] * periods}, index=dates)


def _volatile_price_history(periods=25):
    dates = pd.date_range(start="2023-01-01", periods=periods)
    prices = [100.0]
    for i in range(1, periods):
        prices.append(prices[-1] * (1.05 if i % 2 == 0 else 0.95))
    return pd.DataFrame({'Close': prices}, index=dates)


def test_calculate_stock_weights_applies_volatility_floor():
    screener = QuantScreener()
    top_df = pd.DataFrame({
        'Ticker': ['FLAT', 'NORMAL'],
        'FinalScore': [80.0, 80.0],
        'Price': [100.0, 100.0],
    })
    loader = _FakeLoader({
        'FLAT': _flat_price_history(),
        'NORMAL': _volatile_price_history(),
    })

    result = screener.calculate_stock_weights(top_df, total_target_weight_pct=100.0, loader=loader)

    floor_pct = screener.analysis_model.port_config.min_volatility_floor * 100
    flat_vol = result.loc[result['Ticker'] == 'FLAT', 'Volatility'].iloc[0]
    normal_vol = result.loc[result['Ticker'] == 'NORMAL', 'Volatility'].iloc[0]
    assert flat_vol == pytest.approx(floor_pct)
    assert normal_vol > floor_pct


def test_calculate_stock_weights_caps_extreme_weight_and_redistributes():
    screener = QuantScreener()
    tickers = ['FLAT'] + [f'NORMAL{i}' for i in range(9)]
    top_df = pd.DataFrame({
        'Ticker': tickers,
        'FinalScore': [80.0] * 10,
        'Price': [100.0] * 10,
    })
    histories = {'FLAT': _flat_price_history()}
    histories.update({f'NORMAL{i}': _volatile_price_history() for i in range(9)})
    loader = _FakeLoader(histories)

    result = screener.calculate_stock_weights(top_df, total_target_weight_pct=100.0, loader=loader)

    n = len(tickers)
    cap = (100.0 / n) * screener.analysis_model.port_config.max_stock_weight_multiple
    flat_weight = result.loc[result['Ticker'] == 'FLAT', 'RecWeight'].iloc[0]

    assert flat_weight <= cap + 1e-9
    assert result['RecWeight'].sum() == pytest.approx(100.0)


def test_calculate_stock_weights_normal_case_unaffected_by_cap():
    screener = QuantScreener()
    tickers = [f'NORMAL{i}' for i in range(5)]
    top_df = pd.DataFrame({
        'Ticker': tickers,
        'FinalScore': [80.0] * 5,
        'Price': [100.0] * 5,
    })
    loader = _FakeLoader({t: _volatile_price_history() for t in tickers})

    result = screener.calculate_stock_weights(top_df, total_target_weight_pct=100.0, loader=loader)

    # 모든 종목의 변동성이 동일하므로 상한에 걸리지 않고 균등 비중(20%)이 나와야 함
    for t in tickers:
        w = result.loc[result['Ticker'] == t, 'RecWeight'].iloc[0]
        assert w == pytest.approx(20.0, abs=0.5)


def test_calculate_stoch_williams_value_ranges():
    """%K/%D는 0~100, %R은 -100~0 범위를 벗어나지 않아야 한다."""
    model = AnalysisModel()
    np.random.seed(0)
    closes = 50 + np.cumsum(np.random.normal(0, 2, 60))
    data = _build_ohlc(closes.tolist(), high=max(closes) + 10, low=min(closes) - 10)

    ind = model.calculate_stoch_williams(data)

    assert ind['k'].dropna().between(0, 100).all()
    assert ind['d'].dropna().between(0, 100).all()
    assert ind['r'].dropna().between(-100, 0).all()


def test_stoch_williams_signal_confirmed_buy_on_simultaneous_cross():
    """Stochastic %K와 Williams %R이 같은 날 동시에 상향 돌파하면 '매수 확정'."""
    model = AnalysisModel()
    # 17일간 저점(Close=5, 깊은 과매도) 유지 후 55로 급등.
    # High=100/Low=0 고정이므로 FastK=Close, %R=Close-100.
    # 급등 당일에서 시리즈를 끝내야 함 — 신호는 "최근 봉의 돌파"만 인식하므로
    # 돌파 후 며칠이 더 지나면(값이 그대로 유지돼도) 신호는 중립으로 되돌아간다.
    closes = [5.0] * 17 + [55.0]
    data = _build_ohlc(closes)

    ind = model.calculate_stoch_williams(data)
    signal = model.classify_stoch_williams_signal(ind['k'], ind['r'])

    # 급등 당일(index 17)에 SlowK: mean(5,5,55)/3=21.67 (>=20, 직전 SlowK=5<20 → 돌파)
    # %R: 55-100=-45 (>=-80, 직전 %R=5-100=-95<-80 → 돌파) => 동시 돌파
    assert signal == "매수 확정"


def test_stoch_williams_signal_weak_when_only_one_crosses():
    """%R만 돌파하고 스토캐스틱 %K는 스무딩 지연으로 아직 못 넘으면 약한 신호."""
    model = AnalysisModel()
    # Close 5 -> 35: %R은 즉시 -65로 돌파하지만, SlowK는 3일 평균이라 첫날엔 15로 미돌파.
    closes = [5.0] * 17 + [35.0]
    data = _build_ohlc(closes)

    ind = model.calculate_stoch_williams(data)
    signal = model.classify_stoch_williams_signal(ind['k'], ind['r'])

    assert signal == "관심 (약한 매수 신호)"


def test_stoch_williams_signal_confirmed_sell_on_simultaneous_cross():
    """과매수 구간에서 %K/%R이 동시에 하향 돌파하면 '매도 확정'."""
    model = AnalysisModel()
    # 17일간 고점(Close=95, 깊은 과매수) 유지 후 45로 급락 (급락 당일에서 종료).
    closes = [95.0] * 17 + [45.0]
    data = _build_ohlc(closes)

    ind = model.calculate_stoch_williams(data)
    signal = model.classify_stoch_williams_signal(ind['k'], ind['r'])

    # 급락 당일 SlowK: mean(95,95,45)/3=78.33 (<=80, 직전 95>80 → 돌파)
    # %R: 45-100=-55 (<=-20, 직전 -5>-20 → 돌파) => 동시 돌파
    assert signal == "매도 확정"


def test_stoch_williams_signal_neutral_without_fresh_cross():
    """돌파 이벤트가 없으면(평탄한 구간) 중립."""
    model = AnalysisModel()
    closes = [50.0] * 20
    data = _build_ohlc(closes)

    ind = model.calculate_stoch_williams(data)
    signal = model.classify_stoch_williams_signal(ind['k'], ind['r'])

    assert signal == "중립"


def test_calculate_stoch_williams_ignores_trailing_incomplete_bar():
    """yfinance가 당일 캔들을 아직 채우지 못해 마지막 행의 High/Low/Close가
    NaN인 경우에도, 그 앞의 마지막 유효 거래일 기준으로 값이 계산되어야 한다
    (매번 N/A로만 표시되는 것을 방지)."""
    model = AnalysisModel()
    closes = [5.0] * 17 + [55.0]
    data = _build_ohlc(closes)

    # 미확정 당일 캔들 한 줄 추가 (High/Low/Close가 비어 있음)
    incomplete_row = pd.DataFrame({'High': [np.nan], 'Low': [np.nan], 'Close': [np.nan]},
                                  index=[data.index[-1] + pd.Timedelta(days=1)])
    data_with_incomplete_bar = pd.concat([data, incomplete_row])

    ind = model.calculate_stoch_williams(data_with_incomplete_bar)
    signal = model.classify_stoch_williams_signal(ind['k'], ind['r'])

    assert pd.notna(ind['k'].iloc[-1])
    assert pd.notna(ind['r'].iloc[-1])
    assert signal == "매수 확정"


def _build_screener_df():
    return pd.DataFrame({
        'Ticker': ['AAPL', 'GOOGL', 'MSFT', '005930.KS'],
        'Name': ['Apple Inc.', 'Alphabet Inc.', 'Microsoft Corporation', 'Samsung Electronics'],
    })


def test_filter_screener_df_no_filters_returns_all_rows():
    df = _build_screener_df()
    result = filter_screener_df(df)
    assert len(result) == 4


def test_filter_screener_df_matches_ticker_case_insensitively():
    df = _build_screener_df()
    result = filter_screener_df(df, search_query="aapl")
    assert result['Ticker'].tolist() == ['AAPL']


def test_filter_screener_df_matches_name_substring():
    df = _build_screener_df()
    result = filter_screener_df(df, search_query="samsung")
    assert result['Ticker'].tolist() == ['005930.KS']


def test_filter_screener_df_blank_query_returns_all_rows():
    df = _build_screener_df()
    result = filter_screener_df(df, search_query="   ")
    assert len(result) == 4


def test_filter_screener_df_watchlist_only():
    df = _build_screener_df()
    result = filter_screener_df(df, watchlist_only=True, watchlist_tickers=['MSFT', '005930.KS'])
    assert sorted(result['Ticker'].tolist()) == ['005930.KS', 'MSFT']


def test_filter_screener_df_watchlist_only_with_no_watchlist_returns_empty():
    df = _build_screener_df()
    result = filter_screener_df(df, watchlist_only=True, watchlist_tickers=[])
    assert result.empty


def test_filter_screener_df_combines_search_and_watchlist():
    df = _build_screener_df()
    result = filter_screener_df(
        df, search_query="inc", watchlist_only=True, watchlist_tickers=['GOOGL']
    )
    assert result['Ticker'].tolist() == ['GOOGL']


def test_build_saveticker_url_us_ticker():
    assert build_saveticker_url("GOOGL") == "https://www.saveticker.com/company/GOOGL"


def test_build_saveticker_url_strips_kr_suffix():
    assert build_saveticker_url("005930.KS") == "https://www.saveticker.com/company/005930"
    assert build_saveticker_url("005930.KQ") == "https://www.saveticker.com/company/005930"
