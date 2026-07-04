import os
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from modules.data_loader import DataLoader

@pytest.fixture
def clean_data_loader(tmp_path):
    """임시 디렉토리를 사용하는 DataLoader 인스턴스 제공"""
    loader = DataLoader(data_dir=str(tmp_path))
    return loader

def test_get_sp500_tickers(clean_data_loader):
    loader = clean_data_loader
    # Wiki 페이지가 차단되었을 때의 Fallback 검증을 위해 requests mock 사용 가능하나,
    # 여기서는 기본 리스트 반환 여부를 테스트합니다.
    with patch('requests.get') as mock_get:
        mock_get.side_effect = Exception("Network Error")
        tickers = loader.get_sp500_tickers()
        assert isinstance(tickers, list)
        assert len(tickers) > 0
        assert "AAPL" in tickers

def test_get_kospi200_tickers_fallback(clean_data_loader):
    loader = clean_data_loader
    with patch('pykrx.stock.get_index_portfolio_deposit_file') as mock_get:
        mock_get.side_effect = Exception("KRX Error")
        tickers = loader.get_kospi200_tickers()
        assert isinstance(tickers, list)
        assert len(tickers) == 20
        assert "005930.KS" in tickers

@patch('yfinance.download')
@patch('yfinance.Ticker')
def test_get_stock_fundamentals_us(mock_ticker, mock_download, clean_data_loader):
    loader = clean_data_loader
    
    # Mock yfinance download
    mock_df = pd.DataFrame({
        ('Close', 'AAPL'): [150.0],
        ('Close', 'MSFT'): [300.0]
    })
    mock_df.columns = pd.MultiIndex.from_tuples([('Close', 'AAPL'), ('Close', 'MSFT')])
    mock_download.return_value = mock_df
    
    # Mock yfinance Ticker info
    mock_info1 = MagicMock()
    mock_info1.info = {
        'shortName': 'Apple Inc.', 'sector': 'Technology', 'currentPrice': 150.0,
        'trailingPE': 30.0, 'priceToBook': 40.0, 'returnOnEquity': 0.5,
        'profitMargins': 0.25, 'revenueGrowth': 0.1, 'marketCap': 2000000000000,
        '52WeekChange': 0.2
    }
    mock_info2 = MagicMock()
    mock_info2.info = {
        'shortName': 'Microsoft Corp.', 'sector': 'Technology', 'currentPrice': 300.0,
        'trailingPE': 35.0, 'priceToBook': 15.0, 'returnOnEquity': 0.4,
        'profitMargins': 0.3, 'revenueGrowth': 0.12, 'marketCap': 2200000000000,
        '52WeekChange': 0.15
    }
    mock_ticker.side_effect = lambda t: mock_info1 if t == "AAPL" else mock_info2
    
    res = loader.get_stock_fundamentals(tickers=["AAPL", "MSFT"], market_name="us")
    
    assert isinstance(res, pd.DataFrame)
    assert not res.empty
    assert "AAPL" in res['Ticker'].values
    assert "MSFT" in res['Ticker'].values
    assert res.loc[res['Ticker'] == 'AAPL', 'PER'].values[0] == 30.0
    assert res.loc[res['Ticker'] == 'AAPL', 'ROE'].values[0] == 50.0

@patch('yfinance.download')
@patch('yfinance.Ticker')
def test_get_stock_fundamentals_kr_fallback(mock_ticker, mock_download, clean_data_loader):
    loader = clean_data_loader
    
    # pykrx가 예외를 발생시키도록 모킹하고, yfinance 폴백 작동 검증
    with patch('pykrx.stock.get_market_fundamental_by_ticker') as mock_krx:
        mock_krx.side_effect = Exception("KRX Server Blocked")
        
        # Mock yfinance download
        mock_df = pd.DataFrame({
            ('Close', '005930.KS'): [70000.0]
        })
        mock_df.columns = pd.MultiIndex.from_tuples([('Close', '005930.KS')])
        mock_download.return_value = mock_df
        
        # Mock yfinance Ticker info (PBR, PER 결측 상황을 가정하여 forwardPE와 ROE로 계산하는지 테스트)
        mock_info = MagicMock()
        mock_info.info = {
            'shortName': 'Samsung Electronics', 'sector': 'Technology', 'currentPrice': 70000.0,
            'forwardPE': 10.0, 'returnOnEquity': 0.15, 'profitMargins': 0.12,
            'revenueGrowth': 0.05, 'marketCap': 400000000000000, '52WeekChange': 0.1
        }
        mock_ticker.return_value = mock_info
        
        res = loader.get_stock_fundamentals(tickers=["005930.KS"], market_name="kr")
        
        assert isinstance(res, pd.DataFrame)
        assert not res.empty
        row = res.iloc[0]
        assert row['Ticker'] == "005930.KS"
        # PER = forwardPE = 10
        assert row['PER'] == 10.0
        # ROE = 15.0%
        assert row['ROE'] == 15.0
        # PBR = ROE * PER = 0.15 * 10 = 1.5 (returnOnEquity 0.15 * forwardPE 10.0)
        assert row['PBR'] == 1.5

@patch('yfinance.download')
def test_get_market_history(mock_download, clean_data_loader):
    loader = clean_data_loader
    
    # Mock yfinance download
    mock_df = pd.DataFrame({
        'Close': [100.0, 101.0, 102.0],
        'Open': [99.0, 100.0, 101.0]
    }, index=pd.date_range(start="2023-01-01", periods=3))
    mock_download.return_value = mock_df
    
    # 첫 번째 로드 (다운로드 발생)
    res1 = loader.get_market_history("S&P500", period="1y")
    assert mock_download.call_count == 1
    assert len(res1) == 3
    
    # 캐시 파일이 저장되었는지 확인 (인터벌별로 파일명이 분리됨, 기본 interval="1d")
    cache_file = os.path.join(loader.data_dir, "s&p500_1d_history.csv")
    assert os.path.exists(cache_file)
    
    # 두 번째 로드 (다운로드하지 않고 캐시에서 로드)
    res2 = loader.get_market_history("S&P500", period="1y")
    assert mock_download.call_count == 1 # 추가 다운로드 없음
    assert len(res2) == 3

@patch('yfinance.download')
def test_get_yield_spread(mock_download, clean_data_loader):
    loader = clean_data_loader

    # 10Y 및 2Y 금리 모킹
    mock_10y = pd.DataFrame({'Close': [4.0, 4.1]}, index=pd.date_range(start="2023-01-01", periods=2))
    mock_2y = pd.DataFrame({'Close': [3.5, 3.7]}, index=pd.date_range(start="2023-01-01", periods=2))

    mock_download.side_effect = [mock_10y, mock_2y]

    spread = loader.get_yield_spread(period="1y")
    assert spread is not None
    assert 'Spread' in spread.columns
    # Spread = 10Y - 2Y => [0.5, 0.4]
    assert np.allclose(spread['Spread'].values, [0.5, 0.4])


@patch('yfinance.download')
def test_get_daily_changes(mock_download, clean_data_loader):
    loader = clean_data_loader

    mock_df = pd.DataFrame({
        ('AAPL', 'Close'): [150.0, 153.0],
        ('MSFT', 'Close'): [300.0, 297.0],
    }, index=pd.date_range(start="2023-01-01", periods=2))
    mock_df.columns = pd.MultiIndex.from_tuples([('AAPL', 'Close'), ('MSFT', 'Close')])
    mock_download.return_value = mock_df

    changes = loader.get_daily_changes(["AAPL", "MSFT"])

    assert changes["AAPL"] == pytest.approx((153.0 / 150.0 - 1) * 100)
    assert changes["MSFT"] == pytest.approx((297.0 / 300.0 - 1) * 100)


@patch('yfinance.download')
def test_get_daily_changes_missing_ticker(mock_download, clean_data_loader):
    loader = clean_data_loader

    # MSFT를 요청했지만 다운로드 결과에는 AAPL만 존재하는 상황
    mock_df = pd.DataFrame({
        ('AAPL', 'Close'): [150.0, 153.0],
    }, index=pd.date_range(start="2023-01-01", periods=2))
    mock_df.columns = pd.MultiIndex.from_tuples([('AAPL', 'Close')])
    mock_download.return_value = mock_df

    changes = loader.get_daily_changes(["AAPL", "MSFT"])

    assert "AAPL" in changes
    assert "MSFT" not in changes


@patch('yfinance.download')
def test_get_daily_changes_download_failure(mock_download, clean_data_loader):
    loader = clean_data_loader
    mock_download.side_effect = Exception("Too Many Requests")

    changes = loader.get_daily_changes(["AAPL", "MSFT"])

    assert changes == {}
