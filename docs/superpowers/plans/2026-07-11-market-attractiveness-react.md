# Market Attractiveness React Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a market attractiveness/regime analysis page to `invest-support-web` — 5-factor market score, target equity weight, and macro/yield charts for S&P500/NASDAQ/KOSPI/KOSDAQ — per `docs/superpowers/specs/2026-07-11-market-attractiveness-react-design.md`.

**Architecture:** One new backend helper (`attractiveness.py`) fetches all required market/macro data (index prices, yield spread, sector breadth, liquidity inputs, credit spread) and runs the existing `AnalysisModel` methods (`calculate_breadth_score`, `calculate_liquidity_score`, `calculate_attractiveness`, `run_lppl_fit`, `calculate_target_weight`) unchanged, day-scoped-cached per `(market_name, period)`. One new endpoint returns the full bundle in one response. The frontend adds a third page (market/period selectors, 2 gauges, 6 factor cards, a plain price line, yield charts, and 6 macro mini-charts), reusing the `ignore`-flag fetch pattern already established.

**Tech Stack:** Same as the existing project — Python 3.14 / FastAPI / Pydantic v2 / pandas (backend) — TypeScript / Vite / React / Tailwind CSS / shadcn/ui / react-plotly.js (frontend). No new dependencies.

## Global Constraints

- LPPL diagnosis section (Tc, R², danger score details) and the AI report button are OUT of scope — but `run_lppl_fit`'s `danger_score` must still be computed internally to feed `targetWeightPct`, per the screener's existing `get_ref_analysis` precedent (compute for internal use, don't expose the details).
- No real-time (5-minute-bar) yield mode — 5-year daily view only.
- 4 markets: `S&P500`, `NASDAQ`, `KOSPI`, `KOSDAQ` (exact strings — these are `DataLoader.tickers` dict keys, not raw ticker symbols. `DataLoader.get_market_history("S&P500", ...)` resolves internally). 4 periods: `1y`, `2y`, `3y`, `5y`.
- Main index price/data failure → `503`. Any OTHER individual macro/yield ticker failure (e.g. BTC, HYG unavailable) → that one metric gets `current: 0, momPct: 0, series: []` and the rest of the response still succeeds — never fail the whole request over one secondary data point.
- `weights` field in the response reuses the EXISTING `MacroWeights` schema from `app/schemas.py` (fields `trend/macro/sentiment/liquidity/breadth/credit`) — do not redefine it.
- Cache key format: `attractiveness:{market_name}:{period}`, day-scoped (no `ttl_seconds` — this data is daily-refresh, same as the screener's existing caches).
- This plan does not assume whether the market-heatmap plan (`2026-07-11-market-heatmap-react.md`) has been executed yet — `main.py` changes are additive (add an import line + an `include_router` line), not a full-file replacement, so this works regardless of execution order.

---

## File Structure

```
backend/app/
├── attractiveness.py       # NEW: get_market_attractiveness(market_name, period, cache, loader, engine)
├── schemas.py              # MODIFY: add FactorRawScores, PricePoint, YieldMetric, MacroMetric,
│                           #         YieldSpreadInfo, YieldsInfo, MacroIndicators, AttractivenessResponse
├── main.py                 # MODIFY: register the new attractiveness router
└── routers/
    └── attractiveness.py     # NEW: GET /api/attractiveness/{marketName}
backend/tests/
├── test_attractiveness.py   # NEW: unit tests for get_market_attractiveness
└── test_attractiveness_router.py  # NEW: router-level tests

frontend/src/
├── api/
│   ├── types.ts             # MODIFY: add all the new response types
│   └── attractiveness.ts     # NEW: getAttractiveness(marketName, period)
├── components/
│   ├── ScoreGauges.tsx        # NEW: attractiveness score + target weight gauges
│   ├── FactorScores.tsx       # NEW: 6-factor score cards
│   ├── YieldCharts.tsx        # NEW: 2Y/10Y/30Y + spread charts
│   └── MacroMiniCharts.tsx    # NEW: DXY/BEI/Gold/Oil/VIX/BTC 6 mini-charts
├── pages/
│   └── AttractivenessPage.tsx  # NEW: market/period selectors + inline price chart + assembly
└── App.tsx                  # MODIFY: add a third nav button
```

---

### Task 1: `get_market_attractiveness` helper

**Files:**
- Create: `backend/app/attractiveness.py`
- Create: `backend/tests/test_attractiveness.py`

**Interfaces:**
- Consumes: `MarketCache.get(key)`/`.set(key, value)`/`.lock_for(key)` (existing, day-scoped mode, no `ttl_seconds`), `DataLoader.get_market_history(name, period=...)`, `DataLoader.get_yield_spread(period=...)`, `DataLoader.get_sector_data(period=...)`, `AnalysisModel.calculate_breadth_score(sector_df)`, `AnalysisModel.calculate_liquidity_score(dxy, us10y, gold, btc, vix=None)`, `AnalysisModel.calculate_attractiveness(prices, spread_df, liquidity_score=0.0, breadth_score=50.0, credit_spread_df=None)`, `AnalysisModel.run_lppl_fit(data, num_iterations=None)`, `AnalysisModel.calculate_target_weight(score, danger_score)` — all pre-existing, unmodified.
- Produces: `async def get_market_attractiveness(market_name: str, period: str, cache, loader, engine) -> dict` — a plain dict matching `AttractivenessResponse`'s field names (camelCase) exactly. Task 2's router constructs the Pydantic response directly from this dict.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_attractiveness.py
import asyncio
from unittest.mock import MagicMock

import pandas as pd

from app.attractiveness import get_market_attractiveness
from app.cache import MarketCache


def _make_price_df(values):
    dates = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.DataFrame({"Close": values}, index=dates)


def _make_loader_and_engine():
    loader = MagicMock()

    def get_market_history(name, period="5y", interval="1d", force_download=False):
        series_map = {
            "S&P500": [100.0, 101.0, 102.0],
            "US10Y": [4.2, 4.3, 4.25],
            "US2Y": [4.5, 4.4, 4.45],
            "US30Y": [4.4, 4.42, 4.41],
            "DXY": [103.0, 103.5, 103.2],
            "GOLD": [2000.0, 2010.0, 2005.0],
            "BTC": [60000.0, 61000.0, 60500.0],
            "VIX": [15.0, 14.5, 14.8],
            "HYG": [75.0, 75.2, 75.1],
            "IEF": [95.0, 95.1, 95.05],
            "TIP": [100.0, 100.2, 100.1],
            "OIL": [70.0, 71.0, 70.5],
        }
        if name not in series_map:
            return None
        return _make_price_df(series_map[name])

    loader.get_market_history.side_effect = get_market_history
    loader.get_yield_spread.return_value = pd.DataFrame(
        {"Spread": [1.2, 1.1, 1.15]}, index=pd.date_range("2024-01-01", periods=3, freq="D")
    )
    loader.get_sector_data.return_value = pd.DataFrame(
        {f"sector_{i}": [100.0, 101.0, 102.0] for i in range(11)},
        index=pd.date_range("2024-01-01", periods=3, freq="D"),
    )

    engine = MagicMock()
    engine.calculate_breadth_score.return_value = 63.6
    engine.calculate_liquidity_score.return_value = 12.3
    engine.calculate_attractiveness.return_value = {
        "score": 62.5,
        "regime": "Risk-on (안정 성장)",
        "risk_level": "Low-Mid",
        "action": "매수",
        "weights": {"trend": 0.35, "macro": 0.15, "sentiment": 0.15, "liquidity": 0.15, "breadth": 0.1, "credit": 0.1},
        "raw_scores": {"Trend": 55.2, "Macro": 60.1, "Credit": 58.0, "Liquidity": 12.3, "Breadth": 63.6, "Sentiment": 48.9},
    }
    engine.run_lppl_fit.return_value = {"danger_score": 18.0}
    engine.calculate_target_weight.return_value = 65.0
    return loader, engine


def test_get_market_attractiveness_returns_expected_shape():
    loader, engine = _make_loader_and_engine()
    cache = MarketCache()

    result = asyncio.run(get_market_attractiveness("S&P500", "2y", cache, loader, engine))

    assert result["marketName"] == "S&P500"
    assert result["period"] == "2y"
    assert result["currentPrice"] == 102.0
    assert result["score"] == 62.5
    assert result["regime"] == "Risk-on (안정 성장)"
    assert result["targetWeightPct"] == 65.0
    assert result["rawScores"]["trend"] == 55.2
    assert result["weights"]["trend"] == 0.35
    assert result["yieldSpread"]["current"] == 1.15
    assert result["yields"]["us2y"]["current"] == 4.45
    assert result["macro"]["dxy"]["current"] == 103.2
    assert result["macro"]["btc"]["current"] == 60500.0


def test_get_market_attractiveness_calls_engine_with_collected_data():
    loader, engine = _make_loader_and_engine()
    cache = MarketCache()

    asyncio.run(get_market_attractiveness("S&P500", "2y", cache, loader, engine))

    engine.calculate_breadth_score.assert_called_once()
    engine.calculate_liquidity_score.assert_called_once()
    engine.calculate_attractiveness.assert_called_once()
    engine.run_lppl_fit.assert_called_once()
    engine.calculate_target_weight.assert_called_once_with(62.5, 18.0)


def test_get_market_attractiveness_reuses_cache_for_same_market_and_period():
    loader, engine = _make_loader_and_engine()
    cache = MarketCache()

    asyncio.run(get_market_attractiveness("S&P500", "2y", cache, loader, engine))
    asyncio.run(get_market_attractiveness("S&P500", "2y", cache, loader, engine))

    assert engine.calculate_attractiveness.call_count == 1
    assert engine.run_lppl_fit.call_count == 1


def test_get_market_attractiveness_recomputes_for_different_period():
    loader, engine = _make_loader_and_engine()
    cache = MarketCache()

    asyncio.run(get_market_attractiveness("S&P500", "2y", cache, loader, engine))
    asyncio.run(get_market_attractiveness("S&P500", "5y", cache, loader, engine))

    assert engine.calculate_attractiveness.call_count == 2


def test_get_market_attractiveness_defaults_missing_ticker_to_zero():
    loader, engine = _make_loader_and_engine()
    # Simulate BTC being unavailable — get_market_history returns None for it.
    original_side_effect = loader.get_market_history.side_effect

    def get_market_history_no_btc(name, period="5y", interval="1d", force_download=False):
        if name == "BTC":
            return None
        return original_side_effect(name, period=period, interval=interval, force_download=force_download)

    loader.get_market_history.side_effect = get_market_history_no_btc
    cache = MarketCache()

    result = asyncio.run(get_market_attractiveness("S&P500", "2y", cache, loader, engine))

    assert result["macro"]["btc"]["current"] == 0.0
    assert result["macro"]["btc"]["momPct"] == 0.0
    assert result["macro"]["btc"]["series"] == []
    # Other metrics remain unaffected
    assert result["macro"]["dxy"]["current"] == 103.2
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd ~/develop/workspace/invest-support-web/backend
source .venv/bin/activate
pytest tests/test_attractiveness.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.attractiveness'`.

- [ ] **Step 3: Implement `attractiveness.py`**

```python
# backend/app/attractiveness.py
import pandas as pd


def _series_to_points(series: pd.Series) -> list:
    return [{"date": str(idx.date()), "value": float(val)} for idx, val in series.items()]


def _momentum_pct(series: pd.Series) -> float:
    if len(series) < 21:
        return 0.0
    return float((series.iloc[-1] / series.iloc[-21] - 1) * 100)


def _macro_metric(df) -> dict:
    if df is None or df.empty:
        return {"current": 0.0, "momPct": 0.0, "series": []}
    close = df["Close"]
    return {
        "current": float(close.iloc[-1]),
        "momPct": _momentum_pct(close),
        "series": _series_to_points(close),
    }


def _yield_metric(df) -> dict:
    if df is None or df.empty:
        return {"current": 0.0, "dailyChangePct": 0.0, "series": []}
    close = df["Close"]
    daily_change = float(close.iloc[-1] - close.iloc[-2]) if len(close) > 1 else 0.0
    return {
        "current": float(close.iloc[-1]),
        "dailyChangePct": daily_change,
        "series": _series_to_points(close),
    }


def _yield_spread_status(current: float) -> str:
    if current < 0:
        return "역전"
    if current < 0.5:
        return "평탄화"
    return "정상"


async def get_market_attractiveness(market_name: str, period: str, cache, loader, engine) -> dict:
    """market_name(S&P500/NASDAQ/KOSPI/KOSDAQ)의 5-Factor 매력도 + 목표비중 + 매크로/국채
    데이터를 한 번에 수집·계산해 당일 캐시에 저장한다.

    LPPL 피팅은 목표비중 산출에만 내부적으로 쓰이며, 상세 결과(Tc/R²/danger_score)는
    응답에 포함하지 않는다 — 스크리너의 position-sizing 엔드포인트가 쓰는 것과 동일한 패턴.
    """
    key = f"attractiveness:{market_name}:{period}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    lock = cache.lock_for(key)
    async with lock:
        cached = cache.get(key)
        if cached is not None:
            return cached

        index_data = loader.get_market_history(market_name, period=period)
        if index_data is None or index_data.empty:
            return None

        prices = index_data["Close"]
        spread_df = loader.get_yield_spread(period=period)
        sector_df = loader.get_sector_data(period=period)
        dxy_data = loader.get_market_history("DXY", period=period)
        us10y_data = loader.get_market_history("US10Y", period=period)
        us2y_data = loader.get_market_history("US2Y", period=period)
        us30y_data = loader.get_market_history("US30Y", period=period)
        vix_data = loader.get_market_history("VIX", period=period)
        hyg_data = loader.get_market_history("HYG", period=period)
        ief_data = loader.get_market_history("IEF", period=period)
        gold_data = loader.get_market_history("GOLD", period=period)
        btc_data = loader.get_market_history("BTC", period=period)
        tip_data = loader.get_market_history("TIP", period=period)
        oil_data = loader.get_market_history("OIL", period=period)

        breadth_score = engine.calculate_breadth_score(sector_df)
        liquidity_score = engine.calculate_liquidity_score(
            dxy_data, us10y_data, gold_data, btc_data, vix=vix_data
        )

        credit_spread_df = None
        if hyg_data is not None and ief_data is not None:
            credit_spread_df = pd.DataFrame(
                {"HYG": hyg_data["Close"], "IEF": ief_data["Close"]}
            ).ffill()

        attr_res = engine.calculate_attractiveness(
            prices, spread_df, liquidity_score, breadth_score, credit_spread_df
        )
        if attr_res is None:
            # calculate_attractiveness returns None when the fetched price
            # history has fewer than min_data_points (200) rows — the same
            # "no meaningful result" case as the main-index-missing check
            # above, so this function degrades the same way: return None,
            # which Task 2's router converts to a 503.
            return None
        lppl_res = engine.run_lppl_fit(prices)
        danger_score = lppl_res["danger_score"] if lppl_res else 0.0
        target_weight = engine.calculate_target_weight(attr_res["score"], danger_score)

        price_change_pct = (
            float((prices.iloc[-1] / prices.iloc[-2] - 1) * 100) if len(prices) > 1 else 0.0
        )

        spread_current = 0.0
        spread_change_mom = 0.0
        spread_series = []
        if spread_df is not None and not spread_df.empty:
            spread_series_data = spread_df["Spread"]
            spread_current = float(spread_series_data.iloc[-1])
            prev = spread_series_data.iloc[-20] if len(spread_series_data) >= 20 else spread_series_data.iloc[0]
            spread_change_mom = float(spread_current - prev)
            spread_series = _series_to_points(spread_series_data)

        # BEI proxy: TIP price / IEF price (inflation-expectation proxy)
        bei_metric = {"current": 0.0, "momPct": 0.0, "series": []}
        if tip_data is not None and ief_data is not None:
            bei_series = tip_data["Close"] / ief_data["Close"]
            bei_metric = {
                "current": float(bei_series.iloc[-1]),
                "momPct": _momentum_pct(bei_series),
                "series": _series_to_points(bei_series),
            }

        result = {
            "marketName": market_name,
            "period": period,
            "currentPrice": float(prices.iloc[-1]),
            "priceChangePct": price_change_pct,
            "priceSeries": _series_to_points(prices),
            "score": attr_res["score"],
            "regime": attr_res["regime"],
            "riskLevel": attr_res["risk_level"],
            "action": attr_res["action"],
            "targetWeightPct": target_weight,
            "rawScores": {
                "trend": attr_res["raw_scores"]["Trend"],
                "macro": attr_res["raw_scores"]["Macro"],
                "credit": attr_res["raw_scores"].get("Credit", 50.0),
                "liquidity": attr_res["raw_scores"]["Liquidity"],
                "breadth": attr_res["raw_scores"]["Breadth"],
                "sentiment": attr_res["raw_scores"]["Sentiment"],
            },
            "weights": attr_res["weights"],
            "yieldSpread": {
                "current": spread_current,
                "changeMoM": spread_change_mom,
                "status": _yield_spread_status(spread_current),
                "series": spread_series,
            },
            "yields": {
                "us2y": _yield_metric(us2y_data),
                "us10y": _yield_metric(us10y_data),
                "us30y": _yield_metric(us30y_data),
            },
            "macro": {
                "dxy": _macro_metric(dxy_data),
                "beiProxy": bei_metric,
                "gold": _macro_metric(gold_data),
                "oil": _macro_metric(oil_data),
                "vix": _macro_metric(vix_data),
                "btc": _macro_metric(btc_data),
            },
        }

        cache.set(key, result)
        return result
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd ~/develop/workspace/invest-support-web/backend
source .venv/bin/activate
pytest tests/test_attractiveness.py -v
```

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
cd ~/develop/workspace/invest-support-web
git add backend/app/attractiveness.py backend/tests/test_attractiveness.py
git commit -m "feat: add cached market attractiveness data + scoring helper"
```

---

### Task 2: `GET /api/attractiveness/{marketName}` endpoint

**Files:**
- Modify: `backend/app/schemas.py` (add all new response schemas)
- Create: `backend/app/routers/attractiveness.py`
- Modify: `backend/app/main.py` (register the new router)
- Create: `backend/tests/test_attractiveness_router.py`

**Interfaces:**
- Consumes: `get_market_attractiveness` (Task 1), `get_cache`/`get_loader`/`get_engine` (existing `app/dependencies.py`)
- Produces: `AttractivenessResponse` and its sub-schemas. This is the last backend task for this feature — Task 4 (frontend API client) is the sole remaining consumer.

- [ ] **Step 1: Add schemas**

```python
# backend/app/schemas.py — append to existing file
class FactorRawScores(BaseModel):
    trend: float
    macro: float
    credit: float
    liquidity: float
    breadth: float
    sentiment: float


class PricePoint(BaseModel):
    date: str
    value: float


class YieldMetric(BaseModel):
    current: float
    dailyChangePct: float
    series: list[PricePoint]


class MacroMetric(BaseModel):
    current: float
    momPct: float
    series: list[PricePoint]


class YieldSpreadInfo(BaseModel):
    current: float
    changeMoM: float
    status: str
    series: list[PricePoint]


class YieldsInfo(BaseModel):
    us2y: YieldMetric
    us10y: YieldMetric
    us30y: YieldMetric


class MacroIndicators(BaseModel):
    dxy: MacroMetric
    beiProxy: MacroMetric
    gold: MacroMetric
    oil: MacroMetric
    vix: MacroMetric
    btc: MacroMetric


class AttractivenessResponse(BaseModel):
    marketName: str
    period: str
    currentPrice: float
    priceChangePct: float
    priceSeries: list[PricePoint]
    score: float
    regime: str
    riskLevel: str
    action: str
    targetWeightPct: float
    rawScores: FactorRawScores
    weights: MacroWeights
    yieldSpread: YieldSpreadInfo
    yields: YieldsInfo
    macro: MacroIndicators
```

`MacroWeights` is already defined earlier in this file (from the screener feature) — do not redefine it.

- [ ] **Step 2: Write the failing router tests**

```python
# backend/tests/test_attractiveness_router.py
from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.attractiveness import get_market_attractiveness
from app.cache import MarketCache
from app.dependencies import get_cache, get_engine, get_loader
from app.main import app


def _make_price_df(values):
    dates = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.DataFrame({"Close": values}, index=dates)


@pytest.fixture
def attractiveness_loader():
    loader = MagicMock()

    def get_market_history(name, period="5y", interval="1d", force_download=False):
        series_map = {
            "S&P500": [100.0, 101.0, 102.0],
            "US10Y": [4.2, 4.3, 4.25],
            "US2Y": [4.5, 4.4, 4.45],
            "US30Y": [4.4, 4.42, 4.41],
            "DXY": [103.0, 103.5, 103.2],
            "GOLD": [2000.0, 2010.0, 2005.0],
            "BTC": [60000.0, 61000.0, 60500.0],
            "VIX": [15.0, 14.5, 14.8],
            "HYG": [75.0, 75.2, 75.1],
            "IEF": [95.0, 95.1, 95.05],
            "TIP": [100.0, 100.2, 100.1],
            "OIL": [70.0, 71.0, 70.5],
        }
        return _make_price_df(series_map[name]) if name in series_map else None

    loader.get_market_history.side_effect = get_market_history
    loader.get_yield_spread.return_value = pd.DataFrame(
        {"Spread": [1.2, 1.1, 1.15]}, index=pd.date_range("2024-01-01", periods=3, freq="D")
    )
    loader.get_sector_data.return_value = pd.DataFrame(
        {f"sector_{i}": [100.0, 101.0, 102.0] for i in range(11)},
        index=pd.date_range("2024-01-01", periods=3, freq="D"),
    )
    return loader


@pytest.fixture
def attractiveness_engine():
    engine = MagicMock()
    engine.calculate_breadth_score.return_value = 63.6
    engine.calculate_liquidity_score.return_value = 12.3
    engine.calculate_attractiveness.return_value = {
        "score": 62.5,
        "regime": "Risk-on (안정 성장)",
        "risk_level": "Low-Mid",
        "action": "매수",
        "weights": {"trend": 0.35, "macro": 0.15, "sentiment": 0.15, "liquidity": 0.15, "breadth": 0.1, "credit": 0.1},
        "raw_scores": {"Trend": 55.2, "Macro": 60.1, "Credit": 58.0, "Liquidity": 12.3, "Breadth": 63.6, "Sentiment": 48.9},
    }
    engine.run_lppl_fit.return_value = {"danger_score": 18.0}
    engine.calculate_target_weight.return_value = 65.0
    return engine


@pytest.fixture
def attractiveness_client(attractiveness_loader, attractiveness_engine):
    app.dependency_overrides[get_loader] = lambda: attractiveness_loader
    app.dependency_overrides[get_engine] = lambda: attractiveness_engine
    app.dependency_overrides[get_cache] = lambda: MarketCache()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_attractiveness_returns_full_response(attractiveness_client):
    res = attractiveness_client.get("/api/attractiveness/S%26P500?period=2y")

    assert res.status_code == 200
    body = res.json()
    assert body["marketName"] == "S&P500"
    assert body["score"] == 62.5
    assert body["targetWeightPct"] == 65.0
    assert body["rawScores"]["trend"] == 55.2
    assert body["weights"]["trend"] == 0.35
    assert body["yields"]["us2y"]["current"] == 4.45
    assert body["macro"]["btc"]["current"] == 60500.0


def test_get_attractiveness_returns_503_when_index_data_missing(attractiveness_client, attractiveness_loader):
    attractiveness_loader.get_market_history.side_effect = lambda name, **kwargs: None

    res = attractiveness_client.get("/api/attractiveness/S%26P500?period=2y")

    assert res.status_code == 503


def test_get_attractiveness_invalid_period_returns_422(attractiveness_client):
    res = attractiveness_client.get("/api/attractiveness/S%26P500?period=10y")
    assert res.status_code == 422
```

Note: `S&P500` contains `&`, which must be URL-encoded as `S%26P500` in the test's request path.

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd ~/develop/workspace/invest-support-web/backend
source .venv/bin/activate
pytest tests/test_attractiveness_router.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.routers.attractiveness'` (or a collection error referencing it).

- [ ] **Step 4: Implement the router**

```python
# backend/app/routers/attractiveness.py
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from app.attractiveness import get_market_attractiveness
from app.dependencies import get_cache, get_engine, get_loader
from app.schemas import AttractivenessResponse

IndexMarket = Literal["S&P500", "NASDAQ", "KOSPI", "KOSDAQ"]
Period = Literal["1y", "2y", "3y", "5y"]

router = APIRouter(prefix="/api/attractiveness", tags=["attractiveness"])


@router.get("/{market_name}", response_model=AttractivenessResponse)
async def get_attractiveness(
    market_name: IndexMarket,
    period: Period,
    cache=Depends(get_cache),
    loader=Depends(get_loader),
    engine=Depends(get_engine),
) -> AttractivenessResponse:
    result = await get_market_attractiveness(market_name, period, cache, loader, engine)
    if result is None:
        raise HTTPException(status_code=503, detail="market_data_unavailable")
    return AttractivenessResponse(**result)
```

- [ ] **Step 5: Register the router in `main.py`**

```python
# backend/app/main.py — add this import near the other router imports
from app.routers.attractiveness import router as attractiveness_router
```

```python
# backend/app/main.py — add this line near the other app.include_router(...) calls
app.include_router(attractiveness_router)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd ~/develop/workspace/invest-support-web/backend
source .venv/bin/activate
pytest -v
```

Expected: all previously-passing tests still pass, plus the 5 new attractiveness helper tests and 3 new router tests.

- [ ] **Step 7: Commit**

```bash
cd ~/develop/workspace/invest-support-web
git add backend/app/schemas.py backend/app/routers/attractiveness.py backend/app/main.py backend/tests/test_attractiveness_router.py
git commit -m "feat: add GET /api/attractiveness/{marketName} endpoint"
```

---

### Task 3: Manual backend E2E smoke test

**Files:** none (verification only)

**Interfaces:** none — validates Tasks 1-2 together against real data.

- [ ] **Step 1: Start the backend**

```bash
cd ~/develop/workspace/invest-support-web/backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 2: Hit the endpoint for each of the 4 markets**

```bash
curl -s "http://127.0.0.1:8000/api/attractiveness/S%26P500?period=2y" | python3 -m json.tool | head -40
curl -s "http://127.0.0.1:8000/api/attractiveness/NASDAQ?period=2y" | python3 -m json.tool | head -20
curl -s "http://127.0.0.1:8000/api/attractiveness/KOSPI?period=2y" | python3 -m json.tool | head -20
curl -s "http://127.0.0.1:8000/api/attractiveness/KOSDAQ?period=2y" | python3 -m json.tool | head -20
```

Expected: each returns a full `AttractivenessResponse` JSON body with real numbers (score 0-100, real yield/macro series). First call per market may take 10-30s (multiple real network fetches); subsequent calls to the same market+period should be fast (cache hit).

- [ ] **Step 3: Confirm the day-scoped cache is working**

```bash
time curl -s "http://127.0.0.1:8000/api/attractiveness/S%26P500?period=2y" > /dev/null
```

Expected: well under a second on the second call for the same market+period.

- [ ] **Step 4: Spot-check a degraded-data scenario is at least structurally sound**

```bash
curl -s "http://127.0.0.1:8000/api/attractiveness/S%26P500?period=5y" | python3 -c "
import json, sys
data = json.load(sys.stdin)
assert 0 <= data['score'] <= 100
assert 0 <= data['targetWeightPct'] <= 100
assert data['macro']['btc']['current'] > 0
print('OK')
"
```

No commit for this task — it's a verification checkpoint.

---

### Task 4: API client (types + `attractiveness.ts`)

**Files:**
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/api/attractiveness.ts`

**Interfaces:**
- Consumes: backend response shape from Task 2 (field names match exactly, camelCase both sides)
- Produces: `getAttractiveness(marketName, period): Promise<AttractivenessResponse>` — Task 7's `AttractivenessPage` calls this directly.

- [ ] **Step 1: Add the types**

```ts
// frontend/src/api/types.ts — append
export type IndexMarket = "S&P500" | "NASDAQ" | "KOSPI" | "KOSDAQ"
export type AttractivenessPeriod = "1y" | "2y" | "3y" | "5y"

export interface FactorRawScores {
  trend: number
  macro: number
  credit: number
  liquidity: number
  breadth: number
  sentiment: number
}

export interface PricePoint {
  date: string
  value: number
}

export interface YieldMetric {
  current: number
  dailyChangePct: number
  series: PricePoint[]
}

export interface MacroMetric {
  current: number
  momPct: number
  series: PricePoint[]
}

export interface YieldSpreadInfo {
  current: number
  changeMoM: number
  status: string
  series: PricePoint[]
}

export interface YieldsInfo {
  us2y: YieldMetric
  us10y: YieldMetric
  us30y: YieldMetric
}

export interface MacroIndicators {
  dxy: MacroMetric
  beiProxy: MacroMetric
  gold: MacroMetric
  oil: MacroMetric
  vix: MacroMetric
  btc: MacroMetric
}

export interface AttractivenessResponse {
  marketName: IndexMarket
  period: AttractivenessPeriod
  currentPrice: number
  priceChangePct: number
  priceSeries: PricePoint[]
  score: number
  regime: string
  riskLevel: string
  action: string
  targetWeightPct: number
  rawScores: FactorRawScores
  weights: MacroWeights
  yieldSpread: YieldSpreadInfo
  yields: YieldsInfo
  macro: MacroIndicators
}
```

`MacroWeights` is already defined in this file from the screener feature — do not redefine it.

- [ ] **Step 2: Implement the API client function**

```ts
// frontend/src/api/attractiveness.ts
import type { AttractivenessPeriod, AttractivenessResponse, IndexMarket } from "./types"

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"

export async function getAttractiveness(
  marketName: IndexMarket,
  period: AttractivenessPeriod,
): Promise<AttractivenessResponse> {
  const res = await fetch(
    `${BASE_URL}/api/attractiveness/${encodeURIComponent(marketName)}?period=${period}`,
  )
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${await res.text()}`)
  }
  return res.json() as Promise<AttractivenessResponse>
}
```

- [ ] **Step 3: Verify it compiles**

```bash
cd ~/develop/workspace/invest-support-web/frontend
npx tsc --noEmit
```

Expected: no type errors.

- [ ] **Step 4: Commit**

```bash
cd ~/develop/workspace/invest-support-web
git add frontend/src/api/types.ts frontend/src/api/attractiveness.ts
git commit -m "feat: add typed API client for attractiveness endpoint"
```

---

### Task 5: `ScoreGauges` + `FactorScores` components

**Files:**
- Create: `frontend/src/components/ScoreGauges.tsx`
- Create: `frontend/src/components/FactorScores.tsx`

**Interfaces:**
- Consumes: `score: number`, `targetWeightPct: number` (for `ScoreGauges`); `rawScores: FactorRawScores` (for `FactorScores`) — both from Task 4's types
- Produces: `<ScoreGauges score={...} targetWeightPct={...} />`, `<FactorScores rawScores={...} />`. Task 7 renders both.

- [ ] **Step 1: Implement `ScoreGauges`**

```tsx
// frontend/src/components/ScoreGauges.tsx
import Plot from "react-plotly.js"

interface ScoreGaugesProps {
  score: number
  targetWeightPct: number
}

export function ScoreGauges({ score, targetWeightPct }: ScoreGaugesProps) {
  return (
    <div className="space-y-2">
      <Plot
        data={[
          {
            type: "indicator",
            mode: "gauge+number",
            value: score,
            gauge: {
              axis: { range: [0, 100] },
              bar: { color: "white" },
              steps: [
                { range: [0, 40], color: "red" },
                { range: [40, 75], color: "gray" },
                { range: [75, 100], color: "green" },
              ],
            },
          },
        ]}
        layout={{
          height: 200,
          margin: { l: 20, r: 20, t: 20, b: 20 },
          title: { text: "시장 매력도 점수" },
        }}
        style={{ width: "100%" }}
        useResizeHandler
      />
      <Plot
        data={[
          {
            type: "indicator",
            mode: "gauge+number",
            value: targetWeightPct,
            number: { suffix: "%", font: { size: 24 } },
            gauge: {
              axis: { range: [0, 100] },
              bar: { color: "cyan" },
              steps: [
                { range: [0, 30], color: "gray" },
                { range: [30, 70], color: "darkslategray" },
              ],
            },
          },
        ]}
        layout={{
          height: 180,
          margin: { l: 20, r: 20, t: 20, b: 20 },
          title: { text: "권장 주식 투자 비중" },
        }}
        style={{ width: "100%" }}
        useResizeHandler
      />
    </div>
  )
}
```

- [ ] **Step 2: Implement `FactorScores`**

```tsx
// frontend/src/components/FactorScores.tsx
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { FactorRawScores } from "@/api/types"

interface FactorScoresProps {
  rawScores: FactorRawScores
}

const FACTORS: { key: keyof FactorRawScores; label: string; help: string }[] = [
  { key: "trend", label: "추세", help: "200일 이동평균선과의 이격도(Z-Score) 기반. 수치가 높을수록 단기 과열, 낮을수록 저평가 국면을 의미합니다." },
  { key: "macro", label: "매크로", help: "미국 국채 장단기 금리차(10Y-2Y)의 수준과 변화율을 반영합니다. 금리차가 확대되거나 양수일 때 높은 점수를 부여합니다." },
  { key: "credit", label: "신용", help: "하이일드 채권(HYG) 대 국채(IEF) 비율의 상대적 강세입니다. 높을수록 기업들의 부도 위험이 낮고 신용 시장이 건강함을 의미합니다." },
  { key: "liquidity", label: "유동성", help: "달러, 금리, 금, 비트코인, VIX의 모멘텀을 종합합니다. 달러/금리/VIX 하락 및 금/비트코인 상승 시 유동성이 풍부한 것으로 판단합니다." },
  { key: "breadth", label: "Breadth", help: "주요 11개 섹터 ETF 중 50일 이동평균선 위에 있는 종목의 비율입니다. 시장 상승의 질(내부 체력)을 측정합니다." },
  { key: "sentiment", label: "심리", help: "RSI 지표의 스무딩 값을 활용합니다. 극심한 과매도 구간(공포)일수록 반등 매력도가 높아집니다." },
]

export function FactorScores({ rawScores }: FactorScoresProps) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
      {FACTORS.map((f) => (
        <Card key={f.key} title={f.help}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">{f.label}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold">{rawScores[f.key].toFixed(0)}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
```

- [ ] **Step 3: Verify it compiles**

```bash
cd ~/develop/workspace/invest-support-web/frontend
npx tsc --noEmit
```

Expected: no type errors.

- [ ] **Step 4: Commit**

```bash
cd ~/develop/workspace/invest-support-web
git add frontend/src/components/ScoreGauges.tsx frontend/src/components/FactorScores.tsx
git commit -m "feat: add ScoreGauges and FactorScores components"
```

---

### Task 6: `YieldCharts` + `MacroMiniCharts` components

**Files:**
- Create: `frontend/src/components/YieldCharts.tsx`
- Create: `frontend/src/components/MacroMiniCharts.tsx`

**Interfaces:**
- Consumes: `yieldSpread: YieldSpreadInfo`, `yields: YieldsInfo` (for `YieldCharts`); `macro: MacroIndicators` (for `MacroMiniCharts`) — both from Task 4's types
- Produces: `<YieldCharts yieldSpread={...} yields={...} />`, `<MacroMiniCharts macro={...} />`. Task 7 renders both.

- [ ] **Step 1: Implement `YieldCharts`**

```tsx
// frontend/src/components/YieldCharts.tsx
import Plot from "react-plotly.js"
import type { YieldsInfo, YieldSpreadInfo } from "@/api/types"

interface YieldChartsProps {
  yieldSpread: YieldSpreadInfo
  yields: YieldsInfo
}

export function YieldCharts({ yieldSpread, yields }: YieldChartsProps) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4 text-sm">
        <div>
          <p className="text-muted-foreground">장단기 금리차 (10Y-2Y)</p>
          <p className="text-xl font-semibold">
            {yieldSpread.current.toFixed(3)}% ({yieldSpread.changeMoM >= 0 ? "+" : ""}
            {yieldSpread.changeMoM.toFixed(3)}%)
          </p>
        </div>
        <div>
          <p className="text-muted-foreground">매크로 상태</p>
          <p className="text-xl font-semibold">{yieldSpread.status}</p>
        </div>
        <div>
          <p className="text-muted-foreground">US 2Y / 10Y / 30Y</p>
          <p className="text-xl font-semibold">
            {yields.us2y.current.toFixed(2)} / {yields.us10y.current.toFixed(2)} / {yields.us30y.current.toFixed(2)}
          </p>
        </div>
      </div>

      <Plot
        data={[
          {
            type: "scatter",
            mode: "lines",
            name: "US 2Y",
            x: yields.us2y.series.map((p) => p.date),
            y: yields.us2y.series.map((p) => p.value),
            line: { color: "#00d1b2" },
          },
          {
            type: "scatter",
            mode: "lines",
            name: "US 10Y",
            x: yields.us10y.series.map((p) => p.date),
            y: yields.us10y.series.map((p) => p.value),
            line: { color: "#3273dc" },
          },
          {
            type: "scatter",
            mode: "lines",
            name: "US 30Y",
            x: yields.us30y.series.map((p) => p.date),
            y: yields.us30y.series.map((p) => p.value),
            line: { color: "#ff3860" },
          },
        ]}
        layout={{
          title: { text: "미국 국채 만기별 금리 추이" },
          height: 400,
          margin: { l: 10, r: 10, t: 40, b: 10 },
          legend: { orientation: "h", yanchor: "bottom", y: 1.02, xanchor: "right", x: 1 },
        }}
        style={{ width: "100%" }}
        useResizeHandler
      />

      <Plot
        data={[
          {
            type: "scatter",
            mode: "lines",
            fill: "tozeroy",
            x: yieldSpread.series.map((p) => p.date),
            y: yieldSpread.series.map((p) => p.value),
            line: { color: "#ffdd57" },
          },
        ]}
        layout={{
          title: { text: "장단기 금리차 (10Y-2Y) 추이" },
          height: 300,
          margin: { l: 10, r: 10, t: 40, b: 10 },
          shapes: [
            {
              type: "line",
              x0: 0,
              x1: 1,
              xref: "paper",
              y0: 0,
              y1: 0,
              line: { color: "red", dash: "dash", width: 1 },
            },
          ],
        }}
        style={{ width: "100%" }}
        useResizeHandler
      />
    </div>
  )
}
```

- [ ] **Step 2: Implement `MacroMiniCharts`**

```tsx
// frontend/src/components/MacroMiniCharts.tsx
import Plot from "react-plotly.js"
import type { MacroIndicators, MacroMetric } from "@/api/types"

interface MacroMiniChartsProps {
  macro: MacroIndicators
}

const CHART_CONFIGS: { key: keyof MacroIndicators; label: string; color: string; prefix?: string }[] = [
  { key: "dxy", label: "달러 인덱스 (DXY)", color: "#636efa" },
  { key: "beiProxy", label: "기대 인플레이션 (BEI Proxy)", color: "#636efa" },
  { key: "gold", label: "금 선물 (Gold)", color: "gold", prefix: "$" },
  { key: "oil", label: "WTI 유가 (Oil)", color: "orangered", prefix: "$" },
  { key: "vix", label: "변동성 지표 (VIX)", color: "mediumpurple" },
  { key: "btc", label: "비트코인 (BTC)", color: "orange", prefix: "$" },
]

function MiniChart({ label, metric, color, prefix }: { label: string; metric: MacroMetric; color: string; prefix?: string }) {
  if (metric.series.length === 0) {
    return (
      <div>
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="text-sm text-muted-foreground">데이터 없음</p>
      </div>
    )
  }

  return (
    <div>
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="text-lg font-semibold">
        {prefix ?? ""}
        {metric.current.toLocaleString(undefined, { maximumFractionDigits: 2 })} (
        {metric.momPct >= 0 ? "+" : ""}
        {metric.momPct.toFixed(2)}% 1개월)
      </p>
      <Plot
        data={[
          {
            type: "scatter",
            mode: "lines",
            x: metric.series.map((p) => p.date),
            y: metric.series.map((p) => p.value),
            line: { color },
          },
        ]}
        layout={{
          height: 180,
          margin: { l: 10, r: 10, t: 10, b: 10 },
          xaxis: { title: { text: "" } },
          yaxis: { title: { text: "" } },
        }}
        style={{ width: "100%" }}
        useResizeHandler
      />
    </div>
  )
}

export function MacroMiniCharts({ macro }: MacroMiniChartsProps) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      {CHART_CONFIGS.map((c) => (
        <MiniChart key={c.key} label={c.label} metric={macro[c.key]} color={c.color} prefix={c.prefix} />
      ))}
    </div>
  )
}
```

- [ ] **Step 3: Verify it compiles**

```bash
cd ~/develop/workspace/invest-support-web/frontend
npx tsc --noEmit
```

Expected: no type errors.

- [ ] **Step 4: Commit**

```bash
cd ~/develop/workspace/invest-support-web
git add frontend/src/components/YieldCharts.tsx frontend/src/components/MacroMiniCharts.tsx
git commit -m "feat: add YieldCharts and MacroMiniCharts components"
```

---

### Task 7: `AttractivenessPage` + nav update

**Files:**
- Create: `frontend/src/pages/AttractivenessPage.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `getAttractiveness` (Task 4), `ScoreGauges`/`FactorScores` (Task 5), `YieldCharts`/`MacroMiniCharts` (Task 6), shadcn/ui `Select`/`Badge` (existing)
- Produces: `<AttractivenessPage />`. `App.tsx` gains a third nav option.

- [ ] **Step 1: Implement `AttractivenessPage`**

```tsx
// frontend/src/pages/AttractivenessPage.tsx
import { useEffect, useState } from "react"
import Plot from "react-plotly.js"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { getAttractiveness } from "@/api/attractiveness"
import type { AttractivenessPeriod, AttractivenessResponse, IndexMarket } from "@/api/types"
import { ScoreGauges } from "@/components/ScoreGauges"
import { FactorScores } from "@/components/FactorScores"
import { YieldCharts } from "@/components/YieldCharts"
import { MacroMiniCharts } from "@/components/MacroMiniCharts"

const MARKET_OPTIONS: IndexMarket[] = ["S&P500", "NASDAQ", "KOSPI", "KOSDAQ"]
const PERIOD_OPTIONS: AttractivenessPeriod[] = ["1y", "2y", "3y", "5y"]

export function AttractivenessPage() {
  const [market, setMarket] = useState<IndexMarket>("S&P500")
  const [period, setPeriod] = useState<AttractivenessPeriod>("2y")
  const [data, setData] = useState<AttractivenessResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let ignore = false
    setLoading(true)
    setError(null)

    getAttractiveness(market, period)
      .then((res) => {
        if (!ignore) setData(res)
      })
      .catch((err) => {
        if (!ignore) setError(err instanceof Error ? err.message : "알 수 없는 오류")
      })
      .finally(() => {
        if (!ignore) setLoading(false)
      })

    return () => {
      ignore = true
    }
  }, [market, period])

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-8">
      <div className="flex items-center gap-4">
        <Select value={market} onValueChange={(v) => setMarket(v as IndexMarket)}>
          <SelectTrigger className="w-40">
            <SelectValue>{market}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {MARKET_OPTIONS.map((m) => (
              <SelectItem key={m} value={m}>
                {m}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={period} onValueChange={(v) => setPeriod(v as AttractivenessPeriod)}>
          <SelectTrigger className="w-32">
            <SelectValue>{period}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {PERIOD_OPTIONS.map((p) => (
              <SelectItem key={p} value={p}>
                {p}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {loading && <p className="text-sm text-muted-foreground">분석 중...</p>}
      {error && <p className="text-sm text-destructive">{error}</p>}

      {data && !loading && (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <div className="md:col-span-1">
              <ScoreGauges score={data.score} targetWeightPct={data.targetWeightPct} />
            </div>
            <div className="md:col-span-2 space-y-2">
              <p className="text-sm text-muted-foreground">
                현재 {data.marketName}: {data.currentPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })} (
                {data.priceChangePct >= 0 ? "+" : ""}
                {data.priceChangePct.toFixed(2)}%)
              </p>
              <p className="text-sm text-muted-foreground">리스크 수준: {data.riskLevel}</p>
              <p className="text-sm font-semibold">추천 행동: {data.action}</p>
              <p className="text-sm text-muted-foreground">현재 시장 국면: {data.regime}</p>
            </div>
          </div>

          <FactorScores rawScores={data.rawScores} />

          <Plot
            data={[
              {
                type: "scatter",
                mode: "lines",
                x: data.priceSeries.map((p) => p.date),
                y: data.priceSeries.map((p) => p.value),
                line: { color: "#3273dc" },
              },
            ]}
            layout={{
              title: { text: `${data.marketName} 가격 추이` },
              height: 400,
              margin: { l: 20, r: 20, t: 30, b: 20 },
            }}
            style={{ width: "100%" }}
            useResizeHandler
          />

          <YieldCharts yieldSpread={data.yieldSpread} yields={data.yields} />
          <MacroMiniCharts macro={data.macro} />
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Add a third nav option to `App.tsx`**

```tsx
// frontend/src/App.tsx — full replacement
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { ScreenerPage } from "@/pages/ScreenerPage"
import { HeatmapPage } from "@/pages/HeatmapPage"
import { AttractivenessPage } from "@/pages/AttractivenessPage"

type Page = "screener" | "heatmap" | "attractiveness"

function App() {
  const [page, setPage] = useState<Page>("screener")

  return (
    <div>
      <nav className="flex gap-2 border-b p-4">
        <Button
          variant={page === "screener" ? "default" : "outline"}
          onClick={() => setPage("screener")}
        >
          퀀트 스크리너
        </Button>
        <Button
          variant={page === "heatmap" ? "default" : "outline"}
          onClick={() => setPage("heatmap")}
        >
          마켓 히트맵
        </Button>
        <Button
          variant={page === "attractiveness" ? "default" : "outline"}
          onClick={() => setPage("attractiveness")}
        >
          시장 지수 분석
        </Button>
      </nav>
      {page === "screener" && <ScreenerPage />}
      {page === "heatmap" && <HeatmapPage />}
      {page === "attractiveness" && <AttractivenessPage />}
    </div>
  )
}

export default App
```

If `frontend/src/pages/HeatmapPage.tsx` does not exist yet (the market-heatmap plan hasn't been executed), remove the `HeatmapPage` import and the `"heatmap"` `Page` union member / nav button / render branch from this file — this feature does not depend on the heatmap page existing.

- [ ] **Step 3: Manual browser verification**

```bash
# terminal 1
cd ~/develop/workspace/invest-support-web/backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000

# terminal 2
cd ~/develop/workspace/invest-support-web/frontend && npm run dev -- --port 5173
```

Open `http://localhost:5173`, click "시장 지수 분석". Confirm: default S&P500/2y loads with real data (gauges, 6 factor cards, price chart, yield charts, 6 macro mini-charts all populated), switching market to KOSPI re-fetches and re-renders correctly, switching period to 5y re-fetches. Stop both servers.

- [ ] **Step 4: Commit**

```bash
cd ~/develop/workspace/invest-support-web
git add frontend/src/pages/AttractivenessPage.tsx frontend/src/App.tsx
git commit -m "feat: add AttractivenessPage with market/period selection"
```

---

### Task 8: Full end-to-end verification

**Files:** none (verification only)

**Interfaces:** none — final acceptance check for this feature.

- [ ] **Step 1: Start both servers fresh**

```bash
# terminal 1
cd ~/develop/workspace/invest-support-web/backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000

# terminal 2
cd ~/develop/workspace/invest-support-web/frontend && npm run dev -- --port 5173
```

- [ ] **Step 2: Walk through all 4 markets**

For each of S&P500/NASDAQ/KOSPI/KOSDAQ: select it, confirm the gauges/factor cards/price chart/yield charts/macro mini-charts all populate with real, plausible data (score between 0-100, target weight between 0-100%, sensible price/yield magnitudes).

- [ ] **Step 3: Walk through all 4 periods for one market**

For S&P500: cycle through 1y/2y/3y/5y, confirm the price chart and yield charts visibly change range each time (not stuck on one period's data).

- [ ] **Step 4: Verify the error path**

Stop the backend. Reload the page on the attractiveness tab — confirm the error banner appears, not a blank page or crash.

- [ ] **Step 5: Verify no regression on the other pages**

Confirm the screener page (and heatmap page, if implemented) still work exactly as before — this feature's `main.py`/`App.tsx` changes must not have broken existing routes.

- [ ] **Step 6: Verify no duplicate data collection**

Restart the backend fresh. Load the attractiveness page for S&P500/2y, then reload the same page again. Confirm via backend logs that the second load is a cache hit (no repeated "Downloading historical data" lines for the same tickers) — this is the project's core caching requirement, applied to this feature's much larger data footprint (12+ tickers per request).

No commit for this task. If all steps pass, this feature is complete.

---

## Self-Review Notes

- **Spec coverage:** market/period selection (Task 7), score+target-weight gauges (Task 5), 6 factor cards (Task 5), plain price chart without LPPL overlay (Task 7, inline per the spec's resolved ambiguity), yield charts + spread chart (Task 6), 6 macro mini-charts (Task 6), LPPL computed internally only for target weight without exposing details (Task 1), individual-ticker-failure graceful degradation (Task 1's `_macro_metric`/`_yield_metric` None-handling, tested in Task 1), 503 on main index failure (Task 1 returns `None`, Task 2's router converts to `HTTPException`) — all covered.
- **Type consistency:** `AttractivenessResponse` and all sub-schemas use identical camelCase field names between `backend/app/schemas.py` and `frontend/src/api/types.ts`, checked against each producing task. `MacroWeights` reused from the screener feature without redefinition on either side.
- **No placeholders:** every step has literal file contents or literal commands with expected output.
- **Correction (post-Task-1 review):** the original version of Task 1's helper called `engine.calculate_attractiveness(...)` and immediately accessed `attr_res["score"]`/`["regime"]`/`["raw_scores"][...]`/`["weights"]` with no `None` check — but `AnalysisModel.calculate_attractiveness` (`modules/models.py`) returns `None` whenever the fetched price history has fewer than `min_data_points` (200) rows, which would crash with `TypeError: 'NoneType' object is not subscriptable`. The SAME function already correctly guarded the analogous `run_lppl_fit` call one line later (`danger_score = lppl_res["danger_score"] if lppl_res else 0.0`), making the omission a clear oversight rather than a deliberate choice — and the mocked test suite never caught it because the mock's `calculate_attractiveness.return_value` was always a valid dict. Fixed by adding `if attr_res is None: return None` immediately after the call, matching the existing main-index-missing contract (Task 2's router converts either `None` case to a 503). A regression test (`test_get_market_attractiveness_returns_none_when_insufficient_price_history`) was added to `test_attractiveness.py`. This plan's Task 1 code block above is updated to match.
- **Correction (post-Task-7 live browser test):** two issues found. (1) `DataLoader.get_market_history` (`modules/data_loader.py`, untouched — copied verbatim) caches each ticker's price history to a disk file keyed only by ticker name + interval, not by period, with a purely date-based freshness check (same calendar day → reuse cached file regardless of requested period). So the `period` query param has NO effect on returned data within the same calendar day — whichever period is fetched first for a ticker "wins" until the cache naturally expires the next day. Verified via curl: 1y/2y/3y/5y responses were byte-identical except the echoed `period` field. This is a pre-existing characteristic of the shared engine (same category as the earlier-documented pykrx/KRX limitation), not a regression introduced by this feature, and not fixable without either editing `modules/` (forbidden) or building a nontrivial period-aware cache-versioning layer that risks reintroducing unnecessary duplicate downloads when only the MARKET (not the period) changes. **User decision: accept as a known, documented limitation** (see `backend/NOTES.md`) rather than build a fix — the period selector remains in the UI but currently has no visible effect within a given day. (2) The price chart's hardcoded `line: { color: "white" }` was invisible against the app's white background (no dark theme). Fixed to `"#3273dc"`, matching `YieldCharts.tsx`'s US10Y color. This plan's Task 7 code block above is updated to match.
