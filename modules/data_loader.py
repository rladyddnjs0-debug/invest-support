import yfinance as yf
import pandas as pd
import os
import concurrent.futures
import threading
import requests
import time
import random
from datetime import datetime, timedelta
from pykrx import stock as krx_stock
from abc import ABC, abstractmethod

from modules.config import settings
from modules.logger import logger

class BaseFetcher(ABC):
    @abstractmethod
    def fetch_fundamentals(self, tickers, progress_callback=None):
        pass

    @abstractmethod
    def fetch_history(self, ticker, period, interval):
        pass

class DataTransformer:
    """데이터 소스별 필드명을 표준 규격으로 변환"""
    @staticmethod
    def normalize_kr(df):
        # pykrx -> 표준 필드
        # 현재는 DataLoader 내부 로직에서 처리 중
        return df

    @staticmethod
    def normalize_us(df):
        # yfinance -> 표준 필드
        return df

class DataLoader:
    def __init__(self, data_dir=None):
        self.config = settings.data_loader
        self.data_dir = data_dir if data_dir is not None else self.config.data_dir
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            
        self.tickers = {
            "S&P500": "^GSPC", "NASDAQ": "^IXIC", "KOSPI": "^KS11", "KOSDAQ": "^KQ11",
            "US10Y": "^TNX", "US2Y": "^IRX", "US30Y": "^TYX", "DXY": "DX-Y.NYB", "GOLD": "GC=F",
            "OIL": "CL=F", "TIP": "TIP", "IEF": "IEF", "USD_KRW": "USDKRW=X",
            "BTC": "BTC-USD", "VIX": "^VIX", "HYG": "HYG"
        }
        self.sector_etfs = {
            "XLK": "XLK", "XLF": "XLF", "XLV": "XLV", "XLE": "XLE", 
            "XLY": "XLY", "XLI": "XLI", "XLP": "XLP", "XLU": "XLU", 
            "XLRE": "XLRE", "XLB": "XLB", "XLC": "XLC"
        }
        self.sample_stocks = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "BRK-B", "UNH", "JNJ"]
        self.portfolio_path = os.path.join(self.data_dir, "portfolio.json")

    def save_portfolio(self, portfolio_data):
        import json
        with open(self.portfolio_path, 'w') as f:
            json.dump(portfolio_data, f, indent=4)

    def load_portfolio(self):
        import json
        if os.path.exists(self.portfolio_path):
            with open(self.portfolio_path, 'r') as f:
                return json.load(f)
        return []

    def get_sp500_tickers(self):
        try:
            url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=10)
            table = pd.read_html(response.text)
            df = table[0]
            tickers = [t.replace('.', '-') for t in df['Symbol'].tolist()]
            return tickers
        except Exception as e:
            logger.warning(f"Error fetching S&P 500 tickers: {e}")
            return self.sample_stocks

    def get_kospi200_tickers(self):
        try:
            target_date = datetime.now()
            for _ in range(7):
                date_str = target_date.strftime("%Y%m%d")
                tickers = krx_stock.get_index_portfolio_deposit_file("1028", date_str)
                if tickers and len(tickers) > 150:
                    return [t + ".KS" for t in tickers]
                target_date -= timedelta(days=1)
            return [
                "005930.KS", "000660.KS", "373220.KS", "207940.KS", "005380.KS",
                "068270.KS", "000270.KS", "005490.KS", "035420.KS", "006400.KS",
                "051910.KS", "035720.KS", "003550.KS", "012330.KS", "032830.KS",
                "096770.KS", "033780.KS", "000810.KS", "015760.KS", "018260.KS"
            ]
        except Exception as e:
            logger.warning(f"Error fetching KOSPI 200 tickers from KRX: {e}")
            return [
                "005930.KS", "000660.KS", "373220.KS", "207940.KS", "005380.KS",
                "068270.KS", "000270.KS", "005490.KS", "035420.KS", "006400.KS",
                "051910.KS", "035720.KS", "003550.KS", "012330.KS", "032830.KS",
                "096770.KS", "033780.KS", "000810.KS", "015760.KS", "018260.KS"
            ]


    def get_stock_fundamentals(self, tickers=None, progress_callback=None, market_name="us", force_download=False):
        if tickers is None: tickers = self.sample_stocks
        cache_file = f"{market_name}_fundamentals.csv"
        cache_path = os.path.join(self.data_dir, cache_file)
        
        # 기존 캐시 로드 (업데이트 실패 시 보존용)
        df_old_cache = pd.DataFrame()
        if os.path.exists(cache_path):
            try:
                df_old_cache = pd.read_csv(cache_path)
            except Exception:
                pass

        # force_download가 아니면 캐시 바로 반환
        if not force_download and not df_old_cache.empty:
            file_mtime = datetime.fromtimestamp(os.path.getmtime(cache_path))
            if (datetime.now() - file_mtime).days < self.config.cache_expiry_days:
                if set(tickers).issubset(set(df_old_cache['Ticker'].astype(str).tolist())):
                    logger.info(f"Using cached {market_name} fundamentals from {cache_path}")
                    return df_old_cache[df_old_cache['Ticker'].isin(tickers)]

        if force_download:
            logger.info(f"Force refreshing {market_name} fundamentals...")
        
        fundamental_data = []
        if market_name == "kr":
            try:
                target_date = datetime.now()
                df_krx = None
                for _ in range(7):
                    date_str = target_date.strftime("%Y%m%d")
                    df_kospi = krx_stock.get_market_fundamental_by_ticker(date_str, market="KOSPI")
                    df_kosdaq = krx_stock.get_market_fundamental_by_ticker(date_str, market="KOSDAQ")
                    if not df_kospi.empty and df_kospi['PER'].sum() > 0:
                        df_krx = pd.concat([df_kospi, df_kosdaq]); break
                    target_date -= timedelta(days=1)
                
                if df_krx is not None:
                    df_cap = krx_stock.get_market_cap_by_ticker(date_str, market="ALL")
                    six_months_ago = (target_date - timedelta(days=180)).strftime("%Y%m%d")
                    df_momentum = krx_stock.get_market_price_change_by_ticker(six_months_ago, date_str)
                    
                    for full_ticker in tickers:
                        pure_ticker = full_ticker.split('.')[0]
                        if pure_ticker in df_krx.index:
                            row = df_krx.loc[pure_ticker]
                            eps, bps = row.get('EPS', 0), row.get('BPS', 1)
                            roe = (eps / bps * 100) if bps > 0 else 0
                            fundamental_data.append({
                                'Ticker': full_ticker, 'Name': krx_stock.get_market_ticker_name(pure_ticker),
                                'Sector': 'KOSPI' if pure_ticker in df_kospi.index else 'KOSDAQ',
                                'Price': row.get('종가', 0), 'PER': row.get('PER', 0), 'PBR': row.get('PBR', 0),
                                'ROE': roe, 'ProfitMargin': 0, 'RevenueGrowth': 0, 'MarketCap': df_cap.loc[pure_ticker, '시가총액'] if pure_ticker in df_cap.index else 0,
                                'Momentum': df_momentum.loc[pure_ticker, '등락률'] if pure_ticker in df_momentum.index else 0,
                                'ForwardEPS': eps
                            })
            except Exception as e:
                logger.warning(f"KR Error (pykrx): {e}")

            if not fundamental_data:
                # KR Fallback to yfinance
                pass

        if not fundamental_data or market_name == "us":
            logger.info(f"Downloading US fundamentals for {len(tickers)} tickers")
            try:
                # 50개 이상의 종목인 경우 지연 방지를 위해 batch download만 수행 (info 제외)
                # 단, 소량 종목(밸류에이션용)인 경우 정밀 분석 수행
                is_large_batch = len(tickers) > 50
                batch_data = yf.download(tickers, period="1y", interval="1d", progress=False, group_by='ticker')
            except Exception as e:
                logger.error(f"Batch yfinance download failed: {e}")
                batch_data = pd.DataFrame()

            lock = threading.Lock(); count = 0
            
            def fetch_single_ticker(ticker):
                nonlocal count; curr_price = 0; mom = 0
                old_row = df_old_cache[df_old_cache['Ticker'] == ticker].iloc[0] if not df_old_cache.empty and ticker in df_old_cache['Ticker'].values else None
                
                # 1. 가격 및 모멘텀 (Batch Data 활용)
                try:
                    if not batch_data.empty:
                        if isinstance(batch_data.columns, pd.MultiIndex):
                            if ticker in batch_data.columns.levels[0]:
                                t_data = batch_data[ticker].dropna()
                            else: t_data = pd.DataFrame()
                        else: t_data = batch_data.dropna()
                            
                        if not t_data.empty:
                            price_col = t_data['Close']
                            if isinstance(price_col, pd.DataFrame): price_col = price_col.iloc[:, 0]
                            curr_price = float(price_col.iloc[-1])
                            start_price = float(price_col.iloc[0])
                            mom = (curr_price / start_price - 1) * 100
                except Exception: pass

                # 2. 상세 재무 정보 (Ticker.info 활용 - Retry 로직 포함)
                data = None
                # 대량 배치인 경우 Rate Limit 방지를 위해 info 호출을 최소화하거나 지연을 크게 둠
                if is_large_batch and not force_download and old_row is not None:
                    # 기존 데이터 재사용 (가격/모멘텀만 갱신)
                    data = old_row.to_dict()
                    data['Price'] = curr_price if curr_price > 0 else data.get('Price', 0)
                    data['Momentum'] = mom if mom != 0 else data.get('Momentum', 0)
                else:
                    # 정밀 분석이 필요한 경우 (소량 종목 또는 강제 갱신)
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            # 요청 간 짧은 지연 (차단 방지)
                            if not is_large_batch: time.sleep(random.uniform(0.5, 1.5))
                            
                            t_obj = yf.Ticker(ticker)
                            info = t_obj.info
                            if not info: raise ValueError("Empty info")
                            
                            # EPS 데이터 추출 (Forward -> Trailing 순으로 시도)
                            fwd_eps = info.get('forwardEps')
                            if fwd_eps is None or fwd_eps == 0:
                                fwd_eps = info.get('trailingEps', 0)
                                
                            # PER 데이터 추출 (Trailing -> Forward 순으로 시도)
                            per = info.get('trailingPE')
                            if per is None or per == 0:
                                per = info.get('forwardPE', 0)

                            # PBR 데이터 추출 (없으면 PBR = PER * ROE 항등식으로 유도)
                            pbr = info.get('priceToBook')
                            if pbr is None or pbr == 0:
                                roe_raw = info.get('returnOnEquity', 0) or 0
                                pbr = (per * roe_raw) if (per and roe_raw) else 0

                            data = {
                                'Ticker': ticker, 'Name': info.get('shortName', ticker), 'Sector': info.get('sector', 'N/A'),
                                'Price': curr_price if curr_price > 0 else info.get('currentPrice', 0),
                                'PER': per, 'PBR': pbr,
                                'ROE': info.get('returnOnEquity', 0) * 100, 'ProfitMargin': info.get('profitMargins', 0) * 100,
                                'RevenueGrowth': info.get('revenueGrowth', 0) * 100, 'MarketCap': info.get('marketCap', 0),
                                'Momentum': mom if mom != 0 else (info.get('52WeekChange', 0) * 100),
                                'ForwardEPS': fwd_eps, 'TrailingEPS': info.get('trailingEps', 0)
                            }
                            break # 성공 시 루프 탈출
                        except Exception as e:
                            if "Too Many Requests" in str(e) and attempt < max_retries - 1:
                                wait_time = (attempt + 1) * 5 + random.random()
                                logger.warning(f"Rate limited for {ticker}, waiting {wait_time:.1f}s...")
                                time.sleep(wait_time)
                            else:
                                if attempt == max_retries - 1:
                                    logger.warning(f"Failed to fetch info for {ticker} after {max_retries} attempts.")
                
                # 3. 최종 데이터 확정 (실패 시 캐시 병합)
                if data is None:
                    if old_row is not None:
                        data = old_row.to_dict()
                        data['Price'] = curr_price if curr_price > 0 else data.get('Price', 0)
                        data['Momentum'] = mom if mom != 0 else data.get('Momentum', 0)
                    else:
                        data = {'Ticker': ticker, 'Price': curr_price, 'Momentum': mom, 'ForwardEPS': 0}

                with lock: fundamental_data.append(data); count += 1

            # 스레드 풀 크기 축소하여 차단 확률 감소
            workers = 2 if is_large_batch else 5
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                executor.map(fetch_single_ticker, tickers)

        result_df = pd.DataFrame(fundamental_data)
        if not result_df.empty:
            result_df.to_csv(cache_path, index=False)
            logger.info(f"Saved {market_name} fundamentals ({len(result_df)} records) to cache.")
        return result_df

    def get_historical_fundamentals(self, tickers, base_date, market_name="us"):
        """
        백테스트용 과거 시점 펀더멘털 데이터.
        과거 시점 재무제표 재구성 대신, 인터페이스 호환을 위해 현재 펀더멘털 데이터를 반환합니다.
        """
        return self.get_stock_fundamentals(tickers, market_name=market_name)

    def get_market_history(self, name, period="5y", interval="1d", force_download=False):
        ticker_symbol = self.tickers.get(name, name)
        # 인터벌에 따라 캐시 파일명 분리 (데이터 정합성 유지)
        file_path = os.path.join(self.data_dir, f"{name.lower().replace('/', '_')}_{interval}_history.csv")
        
        should_download = force_download
        if not os.path.exists(file_path):
            should_download = True
        else:
            file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
            # 인트라데이 데이터(1d 미만)는 1시간마다 갱신, 일간 데이터는 하루마다 갱신
            if "m" in interval or "h" in interval:
                if (datetime.now() - file_mtime).seconds > 3600: # 1 hour
                    should_download = True
            elif file_mtime.date() != datetime.now().date():
                should_download = True
            
            if not should_download:
                return pd.read_csv(file_path, index_col=0, parse_dates=True)

        if should_download:
            try:
                logger.info(f"Downloading historical data for {ticker_symbol} (period={period}, interval={interval})...")
                data = yf.download(ticker_symbol, period=period, interval=interval)
                if not data.empty:
                    if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
                    data.to_csv(file_path)
                    return data
            except Exception as e:
                logger.error(f"Error downloading {ticker_symbol} history: {e}")
                return None
        return None

    def get_sector_data(self, period="5y"):
        sector_data = {name: self.get_market_history(name, period=period)['Close'] for name in self.sector_etfs}
        return pd.DataFrame(sector_data)

    def get_yield_spread(self, period="5y"):
        ten_y, two_y = self.get_market_history("US10Y", period=period), self.get_market_history("US2Y", period=period)
        if ten_y is not None and two_y is not None:
            df = pd.DataFrame({'10Y': ten_y['Close'], '2Y': two_y['Close']}).ffill().dropna()
            df['Spread'] = df['10Y'] - df['2Y']; return df[['Spread']]
        return None
