import pytest
import pandas as pd
import numpy as np
from modules.lppl_engine import LPPLEngine

@pytest.fixture
def bubble_data():
    """버블 형태의 가상 데이터 생성"""
    t = np.arange(250)
    tc = 300
    m = 0.5
    # LPPL 형태와 유사한 가속 데이터
    y = 10 - (tc - t)**m
    dates = pd.date_range(start="2023-01-01", periods=250)
    return pd.Series(np.exp(y), index=dates)

def test_lppl_engine_init():
    engine = LPPLEngine()
    assert engine.num_iterations is not None
    assert len(engine.window_sizes) > 0

def test_get_regime_score():
    engine = LPPLEngine()
    # 강한 상승 추세 데이터 (충분히 길게)
    data = pd.Series(np.linspace(100, 200, 500))
    score = engine.get_regime_score(data)
    assert score >= 0.5 # 추세가 좋으므로 최소 0.5 이상이어야 함

def test_calculate_risk_indicator_caching(bubble_data):
    engine = LPPLEngine(num_iterations=20)
    
    # 첫 번째 실행
    score1, details1 = engine.calculate_risk_indicator(bubble_data)
    
    # 동일한 인자로 두 번째 실행
    score2, details2 = engine.calculate_risk_indicator(bubble_data)
    
    # 점수가 정확히 일치해야 함 (캐시 결과)
    assert score1 == score2
    assert details1['peak_tc'] == details2['peak_tc']
