import os
import json
import time
import random
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from modules.lppl_engine import LPPLEngine
from modules.config import settings
from modules.logger import logger


def resolve_regime_choice(auto_regime, use_manual_override, manual_choice):
    """수동 오버라이드가 켜져 있거나 자동 계산에 실패했으면 수동 선택값을, 아니면 자동 계산값을 사용한다."""
    if use_manual_override or not auto_regime:
        return manual_choice
    return auto_regime


class AnalysisModel:
    def __init__(self):
        self.config = settings.lppl
        self.attr_config = settings.attractiveness
        self.port_config = settings.portfolio
        self.lppl_engine = LPPLEngine(num_iterations=self.config.num_iterations)
        self.valuation_matrix = self._load_valuation_matrix()

    def _load_valuation_matrix(self):
        matrix_path = os.path.join("config", "valuation_matrix.json")
        if os.path.exists(matrix_path):
            try:
                with open(matrix_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading valuation matrix: {e}")
        return {}

    def calculate_historical_per_bands(self, ticker, force_download=False):
        """
        과거 5년 데이터를 바탕으로 역사적 PER 밴드 산출.
        Base: Median, Bear: 25th Percentile, Bull: 75th Percentile
        """
        cache_dir = "data"
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        cache_path = os.path.join(cache_dir, "historical_per_cache.json")
        
        # 1. 파일 캐시 확인
        cache_data = {}
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
            except Exception:
                pass
        
        if not force_download and ticker in cache_data:
            cached_entry = cache_data[ticker]
            # 캐시 유효 기간 확인 (예: 7일)
            cache_time = datetime.strptime(cached_entry['timestamp'], '%Y-%m-%d %H:%M:%S')
            if (datetime.now() - cache_time).days < 7:
                logger.info(f"Using cached historical PER for {ticker}")
                return cached_entry['data']

        try:
            logger.info(f"Fetching fresh historical PER for {ticker} from yfinance...")
            
            # Rate limit 방지를 위한 재시도 로직
            max_retries = 3
            income, bs, hist, current_per = None, None, None, 0
            
            for attempt in range(max_retries):
                try:
                    t = yf.Ticker(ticker)
                    income = t.income_stmt
                    time.sleep(random.uniform(0.5, 1.0))
                    bs = t.balance_sheet
                    time.sleep(random.uniform(0.5, 1.0))
                    hist = t.history(period="5y")
                    current_per = float(t.info.get('trailingPE', 0)) if t.info else 0
                    
                    if income.empty or bs.empty or hist.empty:
                        raise ValueError("Some financial data is empty")
                    break # 성공 시 탈출
                except Exception as e:
                    if "Too Many Requests" in str(e) and attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 10 + random.random()
                        logger.warning(f"Rate limited for {ticker} history, waiting {wait_time:.1f}s...")
                        time.sleep(wait_time)
                    else:
                        if attempt == max_retries - 1: raise e
            
            # 1. 과거 실적 (연간) 및 발행주식수 가져오기
            # 순이익 및 주식수 행 식별
            net_income_row = 'Net Income Common Stockholders' if 'Net Income Common Stockholders' in income.index else 'Net Income'
            shares_row = 'Ordinary Shares Number' if 'Ordinary Shares Number' in bs.index else 'Share Issued'
            
            if net_income_row not in income.index or shares_row not in bs.index:
                return None
                
            annual_eps = income.loc[net_income_row] / bs.loc[shares_row]
            annual_eps = annual_eps.dropna()
            
            if annual_eps.empty:
                return None
            
            # 2. 실적 발표일 근처의 주가 분석
            per_list = []
            for date, eps in annual_eps.items():
                try:
                    # tz-aware issue handle
                    target_date = pd.to_datetime(date).tz_localize(hist.index.tz)
                    idx = hist.index.get_indexer([target_date], method='nearest')[0]
                    price = hist.iloc[idx]['Close']
                    if eps > 0:
                        per_list.append(price / eps)
                except Exception:
                    continue
            
            # 3. 일일 PER 추정 (최근 1년 주가 / 최근 EPS)
            latest_eps = annual_eps.iloc[0]
            if latest_eps > 0:
                recent_hist = hist.tail(252) # 약 1년
                daily_pers = recent_hist['Close'] / latest_eps
                per_list.extend(daily_pers.tolist())
            
            if not per_list:
                return None
                
            per_series = pd.Series(per_list).dropna()
            per_series = per_series[per_series > 0] # 음수 PER 제외
            
            if per_series.empty:
                return None
                
            result = {
                'bear': float(per_series.quantile(0.25)),
                'base': float(per_series.median()),
                'bull': float(per_series.quantile(0.75)),
                'min': float(per_series.min()),
                'max': float(per_series.max()),
                'current': current_per
            }
            
            # 4. 캐시 저장
            cache_data[ticker] = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'data': result
            }
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=4)
                
            return result
        except Exception as e:
            logger.error(f"Error calculating historical PER for {ticker}: {e}")
            # 에러 발생 시 기존 캐시가 있다면 리턴 (기간 만료되었더라도 0보다는 나음)
            if ticker in cache_data:
                logger.warning(f"Returning expired cache for {ticker} due to error.")
                return cache_data[ticker]['data']
            return None

    def calculate_valuation_scenarios(self, ticker, forward_eps, current_price):
        """
        펀더멘털 시나리오 기반 적정 주가 및 밴드 산출.
        (Milestone 01: Fundamentals)
        """
        clean_ticker = ticker.split('.')[0] # .KS 등 제거
        matrix = self.valuation_matrix.get(clean_ticker) or self.valuation_matrix.get(ticker)
        
        if not matrix or forward_eps <= 0:
            return None
            
        multiples = matrix['multiples']
        scenarios = {
            'bull': forward_eps * multiples['bull'],
            'base': forward_eps * multiples['base'],
            'bear': forward_eps * multiples['bear']
        }
        
        # 현재가 위치 계산 (%)
        # Bear(0%) ~ Base(50%) ~ Bull(100%) 로 정규화
        if scenarios['bull'] > scenarios['bear']:
            if current_price <= scenarios['bear']:
                position_pct = 0.0
            elif current_price >= scenarios['bull']:
                position_pct = 100.0
            else:
                # Bear ~ Bull 사이의 위치 (선형 보간)
                position_pct = (current_price - scenarios['bear']) / (scenarios['bull'] - scenarios['bear']) * 100
        else:
            position_pct = 50.0

        return {
            'scenarios': scenarios,
            'current_price': current_price,
            'position_pct': position_pct,
            'ticker_name': matrix.get('name', ticker)
        }

    def lppl_func(self, t, A, B, tc, m, C, omega, phi):
        """LPPL 표준 수식 (수학적 정합성 강화)"""
        # tc 이후의 시간은 수식 성립 불가 (음수 로그 방지)
        with np.errstate(invalid='ignore', divide='ignore'):
            dt = tc - t
            dt = np.maximum(dt, 1e-10) # 0 또는 음수 치환
            res = A + B * (dt**m) + C * (dt**m) * np.cos(omega * np.log(dt) + phi)
        return res

    def run_lppl_fit(self, data, macro_data=None, num_iterations=None):
        """
        연구 등급의 LPPL 리스크 인디케이터.
        멀티플리케이티브 스코어링을 통해 가짜 신호를 최소화하고 방어적 리스크 필터로 작동합니다.
        """
        if data is None:
            return None
            
        # 데이터 정제
        if isinstance(data, pd.DataFrame):
            data = data.iloc[:, 0]
        data = data.dropna()
        
        if len(data) < self.config.min_data_points: # 레짐 필터를 위한 최소 데이터
            return None

        # LPPLEngine을 통한 리스크 인디케이터 산출
        risk_score, details = self.lppl_engine.calculate_risk_indicator(data, macro_data, num_iterations)
        
        # 윈도우 결과 중 가장 긴 것 또는 대표적인 것 추출 (시각화용)
        t_full = (data.index - data.index[0]).days.values
        y_full = np.log(data.values)
        best_overall_res = self.lppl_engine.analyze_window(t_full[-250:], y_full[-250:], num_iterations)
        
        if not best_overall_res:
            return {
                'danger_score': risk_score,
                'is_bubble': risk_score >= self.config.bubble_threshold,
                'details': details,
                'regime_msg': "No valid LPPL pattern detected"
            }
            
        best_fit = best_overall_res['best_fit']
        tc_date = data.index[0] + pd.Timedelta(days=int(best_overall_res['peak_tc']))
        
        # 예측 데이터 생성 (미래 30일)
        last_t = t_full[-1]
        future_t = np.arange(0, last_t + 30)
        p1, p2, p3 = self.lppl_engine._lppl_basis(future_t, best_fit['tc'], best_fit['m'], best_fit['omega'])
        beta = self.lppl_engine._solve_linear(t_full[-250:], y_full[-250:], best_fit['tc'], best_fit['m'], best_fit['omega'])
        y_pred = beta[0] + beta[1]*p1 + beta[2]*p2 + beta[3]*p3
        
        res = {
            'params': best_fit,
            'fitted': np.exp(y_pred),
            'tc_date': tc_date,
            'confidence_score': risk_score / 100.0,
            'danger_score': risk_score,
            'is_bubble': risk_score >= self.config.bubble_threshold,
            'details': details,
            'r_squared': best_overall_res['r2']
        }
        return res

    def calculate_breadth_score(self, sector_df):
        """
        섹터 ETF들의 MA50 상회 비율을 통해 시장의 내부 체력(Breadth)을 측정합니다.
        """
        if sector_df is None or sector_df.empty:
            return 50.0
        
        # 각 섹터의 MA50 계산
        ma50 = sector_df.rolling(window=50).mean()
        
        # 최신 데이터 기준 MA50 상회 여부 확인
        latest_price = sector_df.iloc[-1]
        latest_ma50 = ma50.iloc[-1]
        
        above_ma50 = (latest_price > latest_ma50).sum()
        total_sectors = len(sector_df.columns)
        
        breadth_score = (above_ma50 / total_sectors) * 100
        return round(breadth_score, 1)

    def calculate_liquidity_score(self, dxy, us10y, gold, btc, vix=None):
        """
        달러, 금리, 금, 비트코인, VIX를 활용한 포괄적 유동성 및 위험 선호도 인덱스를 산출합니다.
        """
        # 데이터 유효성 체크
        data_list = [dxy, us10y, gold, btc]
        if any(d is None or len(d) < 20 for d in data_list):
            return 0.0
            
        # 20일 모멘텀(ROC) 계산
        def get_roc(df):
            if isinstance(df, pd.DataFrame): df = df.iloc[:, 0]
            return (df.iloc[-1] / df.iloc[-21] - 1) * 100

        roc_dxy = get_roc(dxy)
        roc_us10y = get_roc(us10y)
        roc_gold = get_roc(gold)
        roc_btc = get_roc(btc)
        
        # VIX 기여도 추가 (VIX 하락 시 유동성/위험선호 개선)
        vix_contrib = 0
        if vix is not None and len(vix) >= 20:
            roc_vix = get_roc(vix)
            vix_contrib = -roc_vix * 0.2

        # 유동성 방향 정의 (DXY/금리 하락 시 +, 금/비트코인 상승 시 +)
        score = (-roc_dxy * 0.3) + (-roc_us10y * 0.2) + (roc_gold * 0.15) + (roc_btc * 0.15) + vix_contrib
        
        # -100 ~ 100 사이로 클리핑
        final_score = np.clip(score * 5, -100, 100)
        return round(float(final_score), 1)

    def calculate_attractiveness(self, prices, spread_df, liquidity_score=0.0, breadth_score=50.0, credit_spread_df=None):
        """
        고도화된 레짐 스위칭 기반 시장 매력도 모델
        (Phase 6-6: 신용 스프레드 및 연속 레짐 전환 로직 강화)
        """
        # 데이터 타입 보정
        if isinstance(prices, pd.DataFrame):
            prices = prices.iloc[:, 0]
        
        if prices is None or len(prices) < self.config.min_data_points:
            return None

        # 1. 기술적 지표 (Z-Score & RSI)
        ma_long = self.attr_config.ma_long
        ma_long_series = prices.rolling(window=ma_long).mean()
        dist = (prices / ma_long_series - 1).dropna()
        z_dist = (dist.iloc[-1] - dist.tail(252).mean()) / dist.tail(252).std() if len(dist) >= 20 else 0
        
        delta = prices.diff()
        rsi_window = self.attr_config.rsi_window
        gain = (delta.where(delta > 0, 0)).rolling(window=rsi_window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_window).mean().replace(0, 1e-10)
        rsi = 100 - (100 / (1 + gain/loss))
        smoothed_rsi = rsi.rolling(window=3).mean().iloc[-1]

        # 2. 매크로 스코어링 (시그모이드 기반 연속성 확보)
        def sigmoid(x, k, center=0):
            return 1 / (1 + np.exp(-k * (x - center)))

        # A. 기간 프리미엄 (장단기 금리차)
        macro_score = 50
        if spread_df is not None and not spread_df.empty:
            curr_spread = spread_df['Spread'].iloc[-1]
            spread_mom = spread_df['Spread'].diff(20).iloc[-1]
            level_contrib = (sigmoid(curr_spread, k=self.attr_config.sigmoid_k_spread) * 50) - 20
            mom_contrib = (sigmoid(spread_mom, k=self.attr_config.sigmoid_k_mom) * 30) - 10
            macro_score = 50 + level_contrib + mom_contrib

        # B. 신용 프리미엄 (Credit Spread: HYG/IEF ratio)
        credit_score = 50
        if credit_spread_df is not None and not credit_spread_df.empty:
            # HYG/IEF 비율의 200일 대비 위치 (상대적 강세 = 신용 위험 낮음)
            ratio = credit_spread_df['HYG'] / credit_spread_df['IEF']
            ratio_ma = ratio.rolling(200).mean()
            ratio_z = (ratio.iloc[-1] / ratio_ma.iloc[-1] - 1) * 100
            credit_score = np.clip(50 + ratio_z * 10, 0, 100)

        # 3. 레짐(Regime) 분류 및 동적 가중치 (Smoothing 적용)
        vol = prices.pct_change().rolling(window=20).std().iloc[-1] * np.sqrt(252)
        
        # 신용 스코어와 매크로 스코어를 통합한 리스크 지수
        risk_composite = (100 - credit_score) * 0.5 + (100 - macro_score) * 0.5
        
        # 시그모이드 기반 국면 가중치 계산 (연속성 확보)
        def get_blend_factor(val, low, high):
            if val <= low: return 0.0
            if val >= high: return 1.0
            return (val - low) / (high - low)

        # 변동성과 리스크 지수의 가속도/국면 반영
        vol_factor = get_blend_factor(vol, self.attr_config.volatility_low, self.attr_config.volatility_high)
        risk_factor = get_blend_factor(risk_composite, self.attr_config.risk_composite_low, self.attr_config.risk_composite_high)
        
        # 종합 국면 강도 (0: Risk-on, 0.5: Transition, 1.0: Risk-off)
        regime_intensity = np.maximum(vol_factor, risk_factor)
        
        rw = self.attr_config.regime_weights
        w_on = rw['risk_on'].model_dump()
        w_trans = rw['transition'].model_dump()
        w_off = rw['risk_off'].model_dump()
        
        # 가중치 선형 보간 (Linear Interpolation)
        weights = {}
        for key in w_on.keys():
            if regime_intensity <= 0.5:
                # Risk-on <-> Transition 블렌딩
                t = regime_intensity * 2
                weights[key] = w_on[key] * (1 - t) + w_trans[key] * t
            else:
                # Transition <-> Risk-off 블렌딩
                t = (regime_intensity - 0.5) * 2
                weights[key] = w_trans[key] * (1 - t) + w_off[key] * t
        
        # 레짐 명칭 결정
        if regime_intensity < 0.3: regime = "Risk-on (안정 성장)"
        elif regime_intensity > 0.7: regime = "Risk-off (위험 관리)"
        else: regime = "Transition (국면 전환)"

        # 4. 최종 합산
        trend_score = np.clip(50 - z_dist * self.attr_config.z_score_multiplier, 0, 100)
        sent_score = np.clip(100 - smoothed_rsi, 0, 100)
        liq_norm = (liquidity_score + 100) / 2
        
        final_score = (
            trend_score * weights['trend'] +
            macro_score * weights['macro'] +
            sent_score * weights['sentiment'] +
            liq_norm * weights['liquidity'] +
            breadth_score * weights['breadth'] +
            credit_score * weights.get('credit', 0)
        )

        # 5. 결과 반환
        action_map = [(75, "매수 확대", "Low"), (55, "매수", "Low-Mid"), (40, "보유", "Medium")]
        action, risk_lv = next(((a, r) for s, a, r in action_map if final_score > s), ("비중 축소", "High"))

        return {
            'score': round(final_score, 1),
            'regime': regime,
            'risk_level': risk_lv,
            'action': action,
            'weights': weights,
            'raw_scores': {
                'Trend': round(trend_score, 1),
                'Sentiment': round(sent_score, 1),
                'Macro': round(macro_score, 1),
                'Liquidity': round(liq_norm, 1),
                'Breadth': round(breadth_score, 1),
                'Credit': round(credit_score, 1)
            },
            'details': {
                'Z-이격도': f"{z_dist:.2f}σ",
                '스무딩RSI': f"{smoothed_rsi:.1f}",
                '매크로점수': f"{macro_score:.0f}",
                '유동성점수': f"{liquidity_score:.1f}",
                '신용점수': f"{credit_score:.0f}",
                'Breadth': f"{breadth_score:.1f}%"
            }
        }

    def calculate_target_weight(self, attractiveness_score, danger_score):
        """
        매력도 점수와 버블 위험 점수를 결합하여 최종 권장 주식 비중(%)을 산출합니다.
        """
        base_weight = attractiveness_score
        
        thresholds = self.port_config.danger_thresholds
        penalties = self.port_config.risk_penalties
        
        penalty = penalties[0]
        for i, threshold in enumerate(thresholds):
            if danger_score >= threshold:
                penalty = penalties[i+1]
            else:
                break
            
        final_weight = base_weight * penalty
        
        if danger_score >= thresholds[-1]:
            final_weight = min(final_weight, self.port_config.max_equity_weight_at_high_risk)
            
        return round(float(final_weight), 1)


def _apply_weight_cap(rec_weights, total_target_weight_pct, max_multiple):
    """상한을 초과하는 비중을 상한만큼 자르고, 초과분을 상한 미만 종목에 비례 재분배한다."""
    n = len(rec_weights)
    if n == 0:
        return rec_weights

    cap = (total_target_weight_pct / n) * max_multiple
    weights = rec_weights.copy()
    for _ in range(5):
        over_mask = weights > cap
        if not over_mask.any():
            break
        excess = (weights[over_mask] - cap).sum()
        weights[over_mask] = cap
        under_mask = ~over_mask
        under_total = weights[under_mask].sum()
        if under_total <= 0:
            break
        weights[under_mask] += excess * (weights[under_mask] / under_total)
    return weights


class QuantScreener:
    def __init__(self):
        self.config = settings.screener
        self.weights = {
            "Risk-on (안정 성장)": self.config.regime_factor_weights['risk_on'].model_dump(),
            "Risk-off (위험 관리)": self.config.regime_factor_weights['risk_off'].model_dump(),
            "Transition (국면 전환)": self.config.regime_factor_weights['transition'].model_dump()
        }
        self.analysis_model = AnalysisModel()

    def run_screening(self, df, regime, sector_neutral=False):
        if df.empty: return df

        # 1. 밸류 데이터 전처리 (적자 기업 및 결측치 처리)
        df_clean = df.copy()

        # 필수 컬럼 존재 확인 및 수치화
        required_cols = ['PER', 'PBR', 'ROE', 'Momentum', 'RevenueGrowth', 'ProfitMargin']
        for col in required_cols:
            if col not in df_clean.columns:
                logger.warning(f"Column '{col}' missing in screening input. Filling with 0.")
                df_clean[col] = 0.0
            df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce').fillna(0.0)

        # PER, PBR 특수 처리 (낮을수록 좋음, 적자는 최하위)
        for col in ['PER', 'PBR']:
            # 0 이하(적자) 또는 NaN인 경우 해당 컬럼의 최대값 + 100 할당 (최하위 랭킹용)
            mask = (df_clean[col] <= 0)
            if mask.any():
                max_val = df_clean.loc[~mask, col].max() if not df_clean.loc[~mask, col].empty else 100
                df_clean.loc[mask, col] = max_val + 100

        # 섹터 중립화 여부에 따라 전체 풀 또는 섹터 그룹 내 백분위 순위를 계산하는 헬퍼.
        # Sector 컬럼이 없으면(예: 실제 업종 데이터가 없는 시장) 전체 풀 기준으로 자동 폴백한다.
        use_sector_groups = sector_neutral and 'Sector' in df_clean.columns
        missing_sector = pd.Series(False, index=df_clean.index)
        if use_sector_groups:
            # DataLoader는 결측 섹터를 NaN 또는 문자열 'N/A'로 채운다(modules/data_loader.py 참고).
            # 둘 다 '결측'으로 취급해야 groupby가 조용히 누락시키거나 단독 그룹으로 만점을 주지 않는다.
            normalized_sector = df_clean['Sector'].astype(str).str.strip().str.upper()
            missing_sector = df_clean['Sector'].isna() | normalized_sector.isin(['', 'N/A', 'NAN', 'NONE'])
            # 결측/공백 섹터는 별도 그룹으로 묶어, groupby가 해당 행을 조용히 누락시키는 것을 방지한다
            df_clean['Sector'] = df_clean['Sector'].replace('', pd.NA).fillna('Unknown')

        def pct_rank(col, ascending):
            if not use_sector_groups:
                return df_clean[col].rank(ascending=ascending, pct=True)
            group_rank = df_clean.groupby('Sector')[col].rank(ascending=ascending, pct=True)
            if missing_sector.any():
                # 섹터 정보가 원래 없던 종목은 그룹 랭킹 대신 전체 풀 기준으로 계산해,
                # 'Unknown' 그룹의 유일한(또는 소수) 멤버라는 이유만으로 만점을 받는 것을 방지한다
                full_rank = df_clean[col].rank(ascending=ascending, pct=True)
                group_rank = group_rank.where(~missing_sector, full_rank)
            return group_rank

        # 2. 랭킹 산출 (낮을수록 점수가 높아야 하므로 ascending=False 적용)
        # 단, 위에서 처리한 '나쁜 값'들이 가장 큰 값을 가지므로 rank(ascending=False) 시 최하위 점수를 받게 됨
        df_clean['score_value'] = (
            pct_rank('PER', False) * 50 +
            pct_rank('PBR', False) * 50
        )

        # 퀄리티 및 성장성 (높을수록 좋으므로 ascending=True)
        df_clean['score_quality'] = (
            pct_rank('ROE', True) * 50 +
            pct_rank('ProfitMargin', True) * 50
        )
        df_clean['score_growth'] = pct_rank('RevenueGrowth', True) * 100

        if 'Momentum' in df_clean.columns:
            df_clean['score_momentum'] = pct_rank('Momentum', True) * 100
        else:
            df_clean['score_momentum'] = 50

        # 3. 레짐별 가중치 합산
        w = self.weights.get(regime, self.weights["Transition (국면 전환)"])
        df_clean['FinalScore'] = (
            df_clean['score_quality'] * w['quality'] +
            df_clean['score_value'] * w['value'] +
            df_clean['score_growth'] * w['growth'] +
            df_clean['score_momentum'] * w['momentum']
        )
        
        # 원본 데이터에 계산된 스코어들 병합 (표시용 데이터 보존)
        cols_to_add = ['score_value', 'score_quality', 'score_growth', 'score_momentum', 'FinalScore']
        for col in cols_to_add:
            df[col] = df_clean[col]
            
        return df.sort_values(by='FinalScore', ascending=False)

    def calculate_stock_weights(self, top_df, total_target_weight_pct, loader, total_capital=10000000):
        """
        상위 종목들에 대해 리스크(LPPL)와 변동성(Volatility)을 결합한 실전 포지션 사이징을 수행합니다.
        """
        if top_df.empty: return top_df
        
        results = []
        total_inv_amount = total_capital * (total_target_weight_pct / 100)
        
        for _, row in top_df.iterrows():
            ticker = row['Ticker']
            curr_price = row.get('Price', 0)
            danger_score = 0
            volatility = 0.02 # 기본값 2%
            
            try:
                hist = loader.get_market_history(ticker, period="1y")
                if hist is not None and not hist.empty:
                    # 1. LPPL 위험도 평가
                    lppl_res = self.analysis_model.run_lppl_fit(hist['Close'], num_iterations=20)
                    if lppl_res:
                        danger_score = lppl_res['danger_score']
                    
                    # 2. 변동성 계산 (최근 20일 표준편차 기반, 0에 가까운 값은 하한 적용)
                    returns = hist['Close'].pct_change().dropna()
                    volatility = max(returns.tail(20).std(), self.analysis_model.port_config.min_volatility_floor)
            except Exception as e:
                logger.debug(f"Risk analysis failed for {ticker}: {e}")
            
            # 3. 리스크 조정 가중치 (Risk Parity 기초)
            # 변동성이 높을수록 비중 축소, 퀀트 스코어가 높을수록 비중 확대
            risk_adj_factor = (1.0 / (volatility + 1e-6)) * (row['FinalScore'] / 100.0)
            
            # 4. LPPL 페널티 적용
            penalty = 1.0
            if danger_score >= self.analysis_model.config.bubble_threshold: 
                penalty = 0.2 # 강력 경고
            elif danger_score >= self.analysis_model.config.warning_threshold: 
                penalty = 0.6 # 주의
            
            results.append({
                'Ticker': ticker,
                'DangerScore': danger_score,
                'Volatility': volatility * 100, # % 표시
                'RiskAdjFactor': risk_adj_factor * penalty,
                'Price': curr_price
            })
            
        res_df = pd.DataFrame(results)
        
        # 5. 비중 정규화 및 수량 산출
        total_factor = res_df['RiskAdjFactor'].sum()
        if total_factor > 0:
            res_df['RecWeight'] = (res_df['RiskAdjFactor'] / total_factor) * total_target_weight_pct
        else:
            res_df['RecWeight'] = total_target_weight_pct / len(res_df)

        res_df['RecWeight'] = _apply_weight_cap(
            res_df['RecWeight'], total_target_weight_pct, self.analysis_model.port_config.max_stock_weight_multiple
        )

        # 6. 매수 가이드 산출 (수량, 손절가, 목표가)
        def get_trade_guide(r):
            if r['Price'] <= 0: return pd.Series([0, 0, 0])
            
            # 할당 금액 (KRW 또는 USD 기준 - 환율 처리는 상위 app.py에서 수행 권장)
            alloc_amount = total_inv_amount * (r['RecWeight'] / total_target_weight_pct)
            qty = max(1, int(alloc_amount / r['Price'])) if alloc_amount > 0 else 0
            
            # 기술적 가이드 (변동성의 2배를 손절선으로 설정)
            stop_loss = r['Price'] * (1 - (r['Volatility']/100 * 2))
            target_p = r['Price'] * (1 + (r['Volatility']/100 * 4)) # 리스크 대비 보상비 1:2
            
            return pd.Series([qty, stop_loss, target_p])

        res_df[['Shares', 'StopLoss', 'TargetPrice']] = res_df.apply(get_trade_guide, axis=1)
        
        # 원본과 병합
        final_df = top_df.merge(res_df.drop('Price', axis=1), on='Ticker')
        return final_df

    def calculate_rebalancing(self, portfolio_df, total_target_weight, loader, regime="Transition (국면 전환)"):
        """
        보유 종목들에 대해 퀀트 스코어 및 리스크 기반 리밸런싱 지침을 산출합니다.
        (기존 동일 비중 방식에서 스코어 비례 방식으로 고도화)
        """
        if portfolio_df.empty: return portfolio_df
        
        tickers = portfolio_df['Ticker'].tolist()
        
        # 1. 퀀트 스코어링을 위한 펀더멘털 데이터 수집
        us_tickers = [t for t in tickers if ".KS" not in t and ".KQ" not in t]
        kr_tickers = [t for t in tickers if ".KS" in t or ".KQ" in t]
        
        fund_data_list = []
        if us_tickers:
            fund_data_list.append(loader.get_stock_fundamentals(us_tickers, market_name="us"))
        if kr_tickers:
            fund_data_list.append(loader.get_stock_fundamentals(kr_tickers, market_name="kr"))
            
        if fund_data_list:
            fund_df = pd.concat(fund_data_list)
            # 퀀트 스코어 산출
            scored_df = self.run_screening(fund_df, regime)
            # 스코어 매핑
            score_map = scored_df.set_index('Ticker')['FinalScore'].to_dict()
        else:
            score_map = {t: 50.0 for t in tickers} # 폴백

        results = []
        for _, row in portfolio_df.iterrows():
            ticker = row['Ticker']
            danger_score = 0
            
            # 개별 종목 LPPL 위험도 평가
            try:
                hist = loader.get_market_history(ticker, period="1y")
                if hist is not None and not hist.empty:
                    lppl_res = self.analysis_model.run_lppl_fit(hist['Close'])
                    if lppl_res:
                        danger_score = lppl_res['danger_score']
            except Exception as e:
                logger.debug(f"Individual risk eval failed for {ticker}: {e}")
                
            # 기본 비중: 퀀트 스코어 (0~100)
            base_score = score_map.get(ticker, 50.0)
            
            # 리스크 페널티 적용
            actual_score = base_score
            is_penalized = False
            if danger_score >= self.analysis_model.config.bubble_threshold:
                actual_score = base_score * 0.3 # 위험 종목은 스코어 70% 삭감
                is_penalized = True
            elif danger_score >= self.analysis_model.config.warning_threshold:
                actual_score = base_score * 0.7 # 과열 종목은 스코어 30% 삭감
                
            results.append({
                'Ticker': ticker,
                'DangerScore': danger_score,
                'RawScore': actual_score,
                'IsPenalized': is_penalized
            })
            
        res_df = pd.DataFrame(results)
        
        # 스코어 비중을 퍼센트로 환산하여 total_target_weight 배분
        total_raw_score = res_df['RawScore'].sum()
        if total_raw_score > 0:
            res_df['TargetWeight'] = (res_df['RawScore'] / total_raw_score) * total_target_weight
        else:
            res_df['TargetWeight'] = total_target_weight / len(res_df)
        
        # 원본과 병합 및 매매 수량 계산
        final_df = portfolio_df.merge(res_df[['Ticker', 'DangerScore', 'TargetWeight']], on='Ticker')
        total_portfolio_value = portfolio_df['평가금액(KRW)'].sum()
        
        def calc_trade(row):
            target_val_krw = total_portfolio_value * (row['TargetWeight'] / 100)
            diff_krw = target_val_krw - row['평가금액(KRW)']
            
            # 1주당 KRW 가격 계산
            price_per_share_krw = row['평가금액(KRW)'] / row['수량'] if row['수량'] > 0 else 0
            if price_per_share_krw == 0: return 0
                
            trade_qty = diff_krw / price_per_share_krw
            return round(trade_qty, 1)

        final_df['TradeQty'] = final_df.apply(calc_trade, axis=1)
        return final_df
