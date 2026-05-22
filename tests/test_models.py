import pytest
import pandas as pd
import numpy as np
from modules.models import AnalysisModel

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
