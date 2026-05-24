import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from scipy.stats import gaussian_kde
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
import concurrent.futures
import os
import joblib

from modules.config import settings
from modules.logger import logger

# 캐시 디렉토리 설정
cache_dir = os.path.join(settings.data_loader.data_dir, "cache")
if not os.path.exists(cache_dir):
    os.makedirs(cache_dir)
memory = joblib.Memory(cache_dir, verbose=0)

@memory.cache
def _calculate_lppl_risk_logic(values, dates, window_sizes, num_iterations, min_data_points, tc_range_days, m_bounds, omega_bounds, max_oscillation_ratio, macro_data=None):
    """실제 계산 로직 (joblib 캐시 적용을 위해 독립된 함수로 분리)"""
    # 입력을 다시 Pandas Series로 복원
    data = pd.Series(values, index=pd.to_datetime(dates))
    
    engine = LPPLEngine(num_iterations=num_iterations, window_sizes=window_sizes)
    
    regime_score = engine.get_regime_score(data)
    y_full = np.log(data.values)
    t_full = (data.index - data.index[0]).days.values
    
    window_results = []
    for ws in window_sizes:
        if len(y_full) < ws: continue
        res = engine.analyze_window(t_full[-ws:], y_full[-ws:], num_iterations)
        if res: window_results.append(res)
        
    if not window_results: return 0.0, {"msg": "No valid fits"}
    
    tcs = [r['peak_tc'] for r in window_results]
    consistency_score = np.exp(-np.std(tcs) / 50.0) if len(tcs) > 1 else 0.6
    
    macro_score = 1.0
    if macro_data:
        if macro_data.get('us10y_mom', 0) > 5: macro_score *= 1.2 
        if macro_data.get('dxy_mom', 0) > 2: macro_score *= 1.1
        
    avg_fit = np.clip(np.mean([r['fit_score'] for r in window_results]), 0.1, 1.0)
    avg_stab = np.clip(np.mean([r['stability_score'] for r in window_results]), 0.1, 1.0)
    avg_timing = np.clip(np.mean([r['timing_score'] for r in window_results]), 0.1, 1.0)
    
    raw_product = (regime_score * avg_fit * avg_stab * avg_timing * consistency_score)
    final_score = np.clip(np.sqrt(raw_product) * macro_score * 100, 0, 100)
    
    details = {
        "regime": regime_score,
        "fit": avg_fit,
        "stability": avg_stab,
        "timing": avg_timing,
        "consistency": consistency_score,
        "macro": macro_score,
        "peak_tc": np.mean(tcs)
    }
    
    return final_score, details

class LPPLEngine:
    """
    Defensive LPPL Risk Indicator.
    Focus: Minimizing false positives via multiplicative scoring and hard gates.
    """
    def __init__(self, num_iterations=None, window_sizes=None):
        self.config = settings.lppl
        self.num_iterations = num_iterations if num_iterations is not None else self.config.num_iterations
        self.window_sizes = window_sizes if window_sizes is not None else self.config.window_sizes
        self.min_m, self.max_m = self.config.m_bounds
        self.min_omega, self.max_omega = self.config.omega_bounds

    def get_regime_score(self, data):
        if len(data) < self.config.min_data_points: return 0.2
        ma200 = data.rolling(200).mean().iloc[-1]
        ma50 = data.rolling(50).mean().iloc[-1]
        current_price = data.iloc[-1]
        if pd.isna(ma200) or pd.isna(ma50): return 0.2
        trend_score = 1.0 if current_price > ma200 else 0.2
        mom_score = 1.0 if ma50 > ma200 else 0.4
        returns = np.log(data / data.shift(1)).dropna()
        vol_score = np.clip(returns.tail(20).std() / (returns.std() + 1e-9), 0.5, 1.5)
        return np.clip(trend_score * mom_score * vol_score, 0.1, 1.0)

    def _lppl_basis(self, t, tc, m, omega):
        dt = np.maximum(tc - t, 1e-10)
        return dt**m, (dt**m) * np.cos(omega * np.log(dt)), (dt**m) * np.sin(omega * np.log(dt))

    def _solve_linear(self, t, y, tc, m, omega):
        phi_1, phi_2, phi_3 = self._lppl_basis(t, tc, m, omega)
        X = np.column_stack([np.ones_like(t), phi_1, phi_2, phi_3])
        try: return np.linalg.lstsq(X, y, rcond=None)[0]
        except Exception as e:
            logger.debug(f"Linear solve failed: {e}")
            return None

    def _objective(self, params, t, y):
        tc, m, omega = params
        beta = self._solve_linear(t, y, tc, m, omega)
        if beta is None: return 1e10 * np.ones_like(t)
        p1, p2, p3 = self._lppl_basis(t, tc, m, omega)
        return (beta[0] + beta[1]*p1 + beta[2]*p2 + beta[3]*p3) - y

    def _single_run(self, t, y, bounds):
        last_t = t[-1]
        tc_min, tc_max = self.config.tc_range_days
        x0 = [np.random.uniform(last_t + tc_min, last_t + tc_max * 0.8), 
              np.random.uniform(self.min_m, self.max_m), 
              np.random.uniform(self.min_omega, self.max_omega)]
        try:
            res = least_squares(self._objective, x0, bounds=bounds, args=(t, y), max_nfev=200)
            if res.success:
                tc, m, omega = res.x
                beta = self._solve_linear(t, y, tc, m, omega)
                if beta is not None and beta[1] < 0:
                    C = np.sqrt(beta[2]**2 + beta[3]**2)
                    if (C / np.abs(beta[1])) < self.config.max_oscillation_ratio:
                        return {'tc': tc, 'm': m, 'omega': omega, 'cost': res.cost, 'residuals': res.fun}
        except Exception:
            pass
        return None

    def _validate_residuals(self, residuals):
        try:
            lb_pval = acorr_ljungbox(residuals, lags=[10])['lb_pvalue'].iloc[0]
            arch_pval = het_arch(residuals, nlags=10)[1]
            return np.clip(lb_pval * 5, 0, 1) * np.clip(arch_pval * 5, 0, 1)
        except Exception as e:
            logger.debug(f"Residual validation failed: {e}")
            return 0.0

    def analyze_window(self, t, y, num_iterations=None):
        tc_min, tc_max = self.config.tc_range_days
        bounds = ([t[-1] + tc_min, self.min_m, self.min_omega], [t[-1] + tc_max, self.max_m, self.max_omega])
        valid_fits = []
        n_iter = num_iterations if num_iterations is not None else self.num_iterations
        with concurrent.futures.ThreadPoolExecutor() as ex:
            futures = [ex.submit(self._single_run, t, y, bounds) for _ in range(n_iter)]
            for f in concurrent.futures.as_completed(futures):
                if f.result(): valid_fits.append(f.result())
        if not valid_fits: return None
        best_fit = min(valid_fits, key=lambda x: x['cost'])
        tcs = np.array([f['tc'] for f in valid_fits])
        r2 = 1.0 - (2 * best_fit['cost'] / (len(y) * np.var(y)))
        fit_score = np.clip(r2, 0, 1) * self._validate_residuals(best_fit['residuals'])
        try:
            kde = gaussian_kde(tcs)
            test_tcs = np.linspace(tcs.min(), tcs.max(), 200)
            peak_tc = test_tcs[np.argmax(kde(test_tcs))]
            stability_score = np.clip(np.max(kde(tcs)) * (tcs.max() - tcs.min()) / 2.0, 0, 1)
        except Exception as e:
            logger.debug(f"KDE analysis failed: {e}")
            peak_tc = np.mean(tcs); stability_score = 0.3
        timing_score = np.exp(-(peak_tc - t[-1]) / 100.0)
        return {'peak_tc': peak_tc, 'fit_score': fit_score, 'stability_score': stability_score, 
                'timing_score': timing_score, 'r2': r2, 'best_fit': best_fit}

    def calculate_risk_indicator(self, data, macro_data=None, num_iterations=None):
        n_iter = num_iterations if num_iterations is not None else self.num_iterations
        # Pandas 객체를 Numpy 배열/리스트로 변환하여 캐싱 효율성 증대
        return _calculate_lppl_risk_logic(
            tuple(data.values.tolist()), tuple(data.index.tolist()), tuple(self.window_sizes), n_iter, 
            self.config.min_data_points, tuple(self.config.tc_range_days), 
            tuple(self.config.m_bounds), tuple(self.config.omega_bounds), 
            self.config.max_oscillation_ratio, macro_data
        )
