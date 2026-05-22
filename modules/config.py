import yaml
import os
from pydantic import BaseModel, Field
from typing import List, Dict

class LPPLEngineConfig(BaseModel):
    min_data_points: int = 200
    bubble_threshold: float = 70.0
    warning_threshold: float = 40.0
    m_bounds: List[float] = [0.1, 0.9]
    omega_bounds: List[float] = [6.0, 13.0]
    tc_range_days: List[int] = [1, 500]
    max_oscillation_ratio: float = 1.5
    num_iterations: int = 100
    window_sizes: List[int] = [120, 250, 500]

class RegimeWeights(BaseModel):
    trend: float
    macro: float
    sentiment: float
    liquidity: float
    breadth: float
    credit: float

class AttractivenessConfig(BaseModel):
    rsi_window: int = 14
    ma_long: int = 200
    z_score_multiplier: float = 20.0
    volatility_low: float = 0.18
    volatility_high: float = 0.22
    risk_composite_low: float = 40.0
    risk_composite_high: float = 60.0
    sigmoid_k_spread: float = 400.0
    sigmoid_k_mom: float = 1000.0
    regime_weights: Dict[str, RegimeWeights]

class PortfolioConfig(BaseModel):
    show_portfolio: bool = True
    default_capital: int = 10000000
    max_equity_weight_at_high_risk: float = 20.0
    danger_thresholds: List[float] = [50.0, 70.0, 85.0]
    risk_penalties: List[float] = [1.0, 0.8, 0.5, 0.2]

class FactorWeights(BaseModel):
    quality: float
    value: float
    growth: float
    momentum: float

class ScreenerConfig(BaseModel):
    regime_factor_weights: Dict[str, FactorWeights]

class DataLoaderConfig(BaseModel):
    cache_expiry_days: int = 7
    data_dir: str = "data"

class AppConfig(BaseModel):
    lppl: LPPLEngineConfig
    attractiveness: AttractivenessConfig
    portfolio: PortfolioConfig
    screener: ScreenerConfig
    data_loader: DataLoaderConfig

def load_config(config_path: str = "config.yaml") -> AppConfig:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found at {config_path}")
    
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)
    
    return AppConfig(**config_data)

# Singleton instance for global access
settings = load_config()
