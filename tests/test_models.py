import pytest
import pandas as pd
import numpy as np
from modules.models import AnalysisModel, QuantScreener

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
