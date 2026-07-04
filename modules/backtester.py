import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from modules.models import QuantScreener
from modules.logger import logger

class QuantBacktester:
    def __init__(self, data_loader):
        self.loader = data_loader
        self.screener = QuantScreener()

    def run_backtest(self, market_type, regime_choice, lookback_days=365):
        """
        '오늘 시점'의 펀더멘털로 선정한 Top 10 종목이 지난 1년간 기록한 실제 수익률을 계산합니다.
        주의: 종목 선정에 사용하는 펀더멘털은 항상 최신 데이터이며 base_date 시점으로 되돌아가지
        않으므로, 이는 전략의 사전 예측력을 검증하는 진짜 point-in-time 백테스트가 아니라
        참고용 성과 조회 기능입니다 (look-ahead bias 있음).
        """
        # 1. 시점 설정
        base_date = datetime.now() - timedelta(days=lookback_days)
        
        # 2. 티커 리스트 확보
        if "US" in market_type:
            tickers = self.loader.get_sp500_tickers()
            market_name = "us"
            benchmark_ticker = "^GSPC" # S&P 500
        else:
            tickers = self.loader.get_kospi200_tickers()
            market_name = "kr"
            benchmark_ticker = "^KS11" # KOSPI (코스피 200 지수 대신 종합지수 사용)
            
        # 3. 과거 펀더멘털 데이터 수집
        hist_fund_df = self.loader.get_historical_fundamentals(tickers, base_date, market_name=market_name)
        
        if hist_fund_df.empty:
            return None, None
            
        # 4. 스크리닝 (1년 전 시점의 랭킹)
        screened_df = self.screener.run_screening(hist_fund_df, regime_choice)
        top_10 = screened_df.head(10)
        top_10_tickers = top_10['Ticker'].tolist()
        
        # 5. 수익률 계산 (Top 10 종목 vs 벤치마크)
        start_date_str = base_date.strftime("%Y-%m-%d")
        end_date_str = datetime.now().strftime("%Y-%m-%d")
        
        # 종목별 가격 데이터 가져오기
        try:
            # 병합된 가격 데이터 수집
            all_tickers = top_10_tickers + [benchmark_ticker]
            price_data = yf.download(all_tickers, start=start_date_str, end=end_date_str, progress=False)['Close']
            
            # 다중 인덱스 컬럼 정리
            if isinstance(price_data.columns, pd.MultiIndex):
                price_data.columns = price_data.columns.get_level_values(0)
            
            # 결측치 채우기 및 기준일(1.0) 수익률화
            returns_df = price_data.ffill().dropna()
            if returns_df.empty:
                return top_10, None
                
            # 각 컬럼별 누적 수익률 계산 (시작점 = 1.0)
            norm_returns = returns_df / returns_df.iloc[0]
            
            # 포트폴리오 수익률 (동일 비중 10개 종목 평균)
            portfolio_returns = norm_returns[top_10_tickers].mean(axis=1)
            
            # 결과 합치기
            result_df = pd.DataFrame({
                'Portfolio': portfolio_returns,
                'Benchmark': norm_returns[benchmark_ticker]
            })
            
            return top_10, result_df
            
        except Exception as e:
            logger.error(f"Error in backtest return calculation: {e}", exc_info=True)
            return top_10, None
