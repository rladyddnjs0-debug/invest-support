# Market Heatmap React Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second page to the existing `invest-support-web` project (React+FastAPI) — a Finviz-style US market heatmap (S&P 500 sector treemap colored by daily % change) — per `docs/superpowers/specs/2026-07-11-market-heatmap-react-design.md`.

**Architecture:** Extend the existing `MarketCache` with an optional `ttl_seconds` expiry mode (alongside its existing day-scoped mode) to support the 30-minute freshness the daily-change data needs. Add one new backend module (`heatmap.py`) with two cached helpers, one new endpoint (`GET /api/heatmap`), and one new frontend page that polls every 30 minutes and renders a treemap reusing the exact flat-`labels`/`parents` pattern already built for the screener's `SectorTreemap`.

**Tech Stack:** Same as the existing project — Python 3.14 / FastAPI / Pydantic v2 / pandas (backend) — TypeScript / Vite / React / Tailwind CSS / shadcn/ui / react-plotly.js (frontend). No new dependencies.

## Global Constraints

- US (S&P 500) only — no KR support in this feature.
- No tile-click interaction — pure visualization + hover only.
- Frontend polls `GET /api/heatmap` every 30 minutes (`setInterval`), in addition to the initial fetch on mount.
- Hover text order: name+ticker → 현재가(price, 2 decimals) → 등락률(change) → 시가총액(human-readable) → PER/ROE → (only if non-null) 애프터마켓 등락률.
- `changesAvailable: false` (whole daily-change batch failed) still renders the treemap (all `change: 0`, neutral color) with a warning banner — it must NOT block rendering the way a fundamentals failure does.
- Fundamentals failure (empty/missing data) returns `503` and the frontend shows an error banner instead of the treemap.
- Zero/negative/missing `marketCap` rows are excluded from the response entirely (not just hidden client-side).
- `MarketCache`'s existing day-scoped `get(key, today=None)` / `set(key, value, today=None)` call sites (used by `ref_analysis.py` and `screening.py`) must keep working unchanged — the `ttl_seconds` addition must be purely additive.

---

## File Structure

```
backend/app/
├── cache.py             # MODIFY: add ttl_seconds support to get()/set()
├── heatmap.py            # NEW: get_heatmap_fundamentals(), get_daily_changes_cached()
├── schemas.py            # MODIFY: add HeatmapTile, HeatmapResponse
├── main.py               # MODIFY: register the new heatmap router
└── routers/
    └── heatmap.py          # NEW: GET /api/heatmap
backend/tests/
├── test_cache.py          # MODIFY: add ttl_seconds tests
├── test_heatmap.py         # NEW: unit tests for the two heatmap.py helpers
├── conftest.py            # MODIFY: add get_daily_changes mock to fake_loader fixture
└── test_heatmap_router.py  # NEW: router-level tests

frontend/src/
├── api/
│   ├── types.ts           # MODIFY: add HeatmapTile, HeatmapResponse
│   └── heatmap.ts          # NEW: getHeatmap()
├── components/
│   └── MarketHeatmap.tsx   # NEW: treemap, reuses SectorTreemap's flat-labels pattern
├── pages/
│   └── HeatmapPage.tsx     # NEW: fetch + 30-min polling + error/warning banners
└── App.tsx                # MODIFY: simple state-based nav between ScreenerPage/HeatmapPage
```

---

### Task 1: Extend `MarketCache` with `ttl_seconds` support

**Files:**
- Modify: `backend/app/cache.py`
- Modify: `backend/tests/test_cache.py`

**Interfaces:**
- Consumes: nothing new (pure internal refactor of an existing class)
- Produces: `MarketCache.get(key, ttl_seconds=None, today=None)` — when `ttl_seconds` is given, expiry is based on elapsed seconds since caching; when omitted, existing day-scoped behavior is unchanged. `MarketCache.set(key, value, today=None)` — unchanged signature and behavior. Task 2's `heatmap.py` calls `cache.get(key, ttl_seconds=1800)`.

- [ ] **Step 1: Write the failing tests for TTL mode**

Add these three tests to the END of `backend/tests/test_cache.py` (do not remove or modify the existing 6 tests above them):

```python
# backend/tests/test_cache.py — append
from datetime import datetime, timedelta


def test_set_then_get_within_ttl_returns_value():
    cache = MarketCache()
    cache.set("changes:us", {"AAPL": 1.2})
    assert cache.get("changes:us", ttl_seconds=1800) == {"AAPL": 1.2}


def test_get_after_ttl_expires_returns_none():
    cache = MarketCache()
    cache.set("changes:us", {"AAPL": 1.2})
    cache._store["changes:us"] = (datetime.now() - timedelta(seconds=2000), {"AAPL": 1.2})
    assert cache.get("changes:us", ttl_seconds=1800) is None


def test_get_within_ttl_boundary_returns_value():
    cache = MarketCache()
    cache._store["changes:us"] = (datetime.now() - timedelta(seconds=1000), {"AAPL": 1.2})
    assert cache.get("changes:us", ttl_seconds=1800) == {"AAPL": 1.2}
```

- [ ] **Step 2: Run tests to verify the new ones fail, the existing ones still pass**

```bash
cd ~/develop/workspace/invest-support-web/backend
source .venv/bin/activate
pytest tests/test_cache.py -v
```

Expected: the 6 pre-existing tests still `PASS` (current `get()`/`set()` signature already accepts extra kwargs being added, but `ttl_seconds` isn't implemented yet); the 3 new tests `FAIL` — `get()` doesn't accept/use `ttl_seconds` yet, so `cache.get("changes:us", ttl_seconds=1800)` will raise `TypeError: get() got an unexpected keyword argument 'ttl_seconds'`.

- [ ] **Step 3: Implement `ttl_seconds` support**

Replace the full contents of `backend/app/cache.py` with:

```python
# backend/app/cache.py
import asyncio
from datetime import date, datetime
from typing import Any, Dict, Optional, Tuple


class MarketCache:
    """In-memory cache with a per-key asyncio.Lock, supporting two expiry modes.

    Day-scoped (default, ttl_seconds=None): values expire when the wall-clock
    date changes, since data like fundamentals/market history is only ever
    refreshed once per calendar day at most.

    TTL-scoped (ttl_seconds given): values expire after a fixed number of
    elapsed seconds, for data that needs finer-grained freshness than a full
    calendar day (e.g. intraday daily-change percentages, refreshed every
    30 minutes).
    """

    def __init__(self) -> None:
        self._store: Dict[str, Tuple[datetime, Any]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def get(
        self,
        key: str,
        ttl_seconds: Optional[float] = None,
        today: Optional[date] = None,
    ) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        cached_at, value = entry

        if ttl_seconds is not None:
            elapsed = (datetime.now() - cached_at).total_seconds()
            return value if elapsed < ttl_seconds else None

        today = today or date.today()
        return value if cached_at.date() == today else None

    def set(self, key: str, value: Any, today: Optional[date] = None) -> None:
        cached_at = datetime.combine(today, datetime.min.time()) if today is not None else datetime.now()
        self._store[key] = (cached_at, value)

    def lock_for(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]
```

- [ ] **Step 4: Run tests to verify all 9 pass**

```bash
cd ~/develop/workspace/invest-support-web/backend
source .venv/bin/activate
pytest tests/test_cache.py -v
```

Expected: `9 passed`.

- [ ] **Step 5: Run the full backend suite to confirm no regressions in `ref_analysis`/`screening`/router tests**

```bash
cd ~/develop/workspace/invest-support-web/backend
source .venv/bin/activate
pytest -v
```

Expected: all previously-passing tests (26 as of the screener MVP) still pass, plus the 3 new cache tests — `29 passed`.

- [ ] **Step 6: Commit**

```bash
cd ~/develop/workspace/invest-support-web
git add backend/app/cache.py backend/tests/test_cache.py
git commit -m "feat: add ttl_seconds expiry mode to MarketCache"
```

---

### Task 2: Heatmap data helpers (`heatmap.py`)

**Files:**
- Create: `backend/app/heatmap.py`
- Create: `backend/tests/test_heatmap.py`

**Interfaces:**
- Consumes: `MarketCache.get(key, ttl_seconds=None)` / `.set(key, value)` / `.lock_for(key)` (Task 1), `DataLoader.get_sp500_tickers()`, `DataLoader.get_stock_fundamentals(tickers, market_name="us")`, `DataLoader.get_daily_changes(tickers)` (all pre-existing, unmodified, in `modules/data_loader.py`)
- Produces: `async def get_heatmap_fundamentals(cache, loader) -> pd.DataFrame` and `async def get_daily_changes_cached(cache, loader, tickers: list) -> dict`. Task 3's router calls both directly.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_heatmap.py
import asyncio
from unittest.mock import MagicMock

import pandas as pd

from app.cache import MarketCache
from app.heatmap import get_daily_changes_cached, get_heatmap_fundamentals


def _make_loader():
    loader = MagicMock()
    loader.get_sp500_tickers.return_value = ["AAPL", "FISV"]
    loader.get_stock_fundamentals.return_value = pd.DataFrame(
        {
            "Ticker": ["AAPL", "FISV"],
            "Name": ["Apple Inc.", float("nan")],
            "Sector": ["Technology", float("nan")],
            "MarketCap": [3_500_000_000_000, 5_000_000_000],
            "Price": [230.0, 20.0],
            "PER": [28.1, 15.0],
            "ROE": [147.9, 10.0],
        }
    )
    loader.get_daily_changes.return_value = {
        "AAPL": {"change": 1.2, "after_hours_change": None},
        "FISV": {"change": -0.5, "after_hours_change": 0.1},
    }
    return loader


def test_get_heatmap_fundamentals_calls_sp500_tickers_and_fundamentals():
    loader = _make_loader()
    cache = MarketCache()

    result = asyncio.run(get_heatmap_fundamentals(cache, loader))

    loader.get_sp500_tickers.assert_called_once()
    loader.get_stock_fundamentals.assert_called_once_with(["AAPL", "FISV"], market_name="us")
    assert result.loc[result["Ticker"] == "FISV", "Sector"].iloc[0] == "Unknown"
    assert result.loc[result["Ticker"] == "FISV", "Name"].iloc[0] == "FISV"


def test_get_heatmap_fundamentals_reuses_cache_same_day():
    loader = _make_loader()
    cache = MarketCache()

    asyncio.run(get_heatmap_fundamentals(cache, loader))
    asyncio.run(get_heatmap_fundamentals(cache, loader))

    assert loader.get_stock_fundamentals.call_count == 1


def test_get_daily_changes_cached_calls_loader_once_within_ttl():
    loader = _make_loader()
    cache = MarketCache()

    result_1 = asyncio.run(get_daily_changes_cached(cache, loader, ["AAPL", "FISV"]))
    result_2 = asyncio.run(get_daily_changes_cached(cache, loader, ["AAPL", "FISV"]))

    assert loader.get_daily_changes.call_count == 1
    assert result_1 == result_2 == loader.get_daily_changes.return_value


def test_get_daily_changes_cached_recomputes_after_ttl_expires():
    from datetime import datetime, timedelta

    loader = _make_loader()
    cache = MarketCache()

    asyncio.run(get_daily_changes_cached(cache, loader, ["AAPL", "FISV"]))
    cache._store["daily_changes:us"] = (
        datetime.now() - timedelta(seconds=2000),
        loader.get_daily_changes.return_value,
    )
    asyncio.run(get_daily_changes_cached(cache, loader, ["AAPL", "FISV"]))

    assert loader.get_daily_changes.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/develop/workspace/invest-support-web/backend
source .venv/bin/activate
pytest tests/test_heatmap.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.heatmap'`.

- [ ] **Step 3: Implement `heatmap.py`**

```python
# backend/app/heatmap.py
import pandas as pd


async def get_heatmap_fundamentals(cache, loader) -> pd.DataFrame:
    """S&P 500 펀더멘털(Name/Sector/MarketCap/Price/PER/ROE)을 날짜단위로 캐싱해 반환한다.

    스크리너(`screening.py`)가 쓰는 것과 동일한 `us_fundamentals.csv` 디스크 캐시(7일)를
    그대로 재사용하므로, 같은 날 스크리너를 먼저 조회했다면 네트워크 재수집이 없다.
    """
    key = "heatmap_fundamentals:us"
    cached = cache.get(key)
    if cached is not None:
        return cached

    lock = cache.lock_for(key)
    async with lock:
        cached = cache.get(key)
        if cached is not None:
            return cached

        tickers = loader.get_sp500_tickers()
        fund_df = loader.get_stock_fundamentals(tickers, market_name="us")
        fund_df = fund_df.copy()
        fund_df["Sector"] = fund_df["Sector"].fillna("Unknown")
        fund_df["Name"] = fund_df["Name"].fillna(fund_df["Ticker"])

        cache.set(key, fund_df)
        return fund_df


async def get_daily_changes_cached(cache, loader, tickers: list) -> dict:
    """당일 등락률을 30분 TTL로 캐싱해 반환한다.

    배치 호출 자체가 실패하면 `DataLoader.get_daily_changes`가 빈 dict를 반환하며,
    그 빈 결과도 그대로 캐시된다 (다음 30분 주기까지 재시도하지 않음 — 실패가 잦은
    상황에서 매 요청마다 재시도 폭주를 방지).
    """
    key = "daily_changes:us"
    cached = cache.get(key, ttl_seconds=1800)
    if cached is not None:
        return cached

    lock = cache.lock_for(key)
    async with lock:
        cached = cache.get(key, ttl_seconds=1800)
        if cached is not None:
            return cached

        changes = loader.get_daily_changes(tickers)
        cache.set(key, changes)
        return changes
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/develop/workspace/invest-support-web/backend
source .venv/bin/activate
pytest tests/test_heatmap.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
cd ~/develop/workspace/invest-support-web
git add backend/app/heatmap.py backend/tests/test_heatmap.py
git commit -m "feat: add cached heatmap fundamentals + daily-changes helpers"
```

---

### Task 3: `GET /api/heatmap` endpoint

**Files:**
- Modify: `backend/app/schemas.py` (add `HeatmapTile`, `HeatmapResponse`)
- Create: `backend/app/routers/heatmap.py`
- Modify: `backend/app/main.py` (register the new router)
- Modify: `backend/tests/conftest.py` (add `get_daily_changes` mock to `fake_loader`)
- Create: `backend/tests/test_heatmap_router.py`

**Interfaces:**
- Consumes: `get_heatmap_fundamentals`, `get_daily_changes_cached` (Task 2), `get_cache`/`get_loader` (existing `app/dependencies.py`)
- Produces: `HeatmapTile`, `HeatmapResponse` Pydantic models. This is the last backend task — Task 5 (frontend API client) is the sole remaining consumer.

- [ ] **Step 1: Add schemas**

```python
# backend/app/schemas.py — append to existing file
class HeatmapTile(BaseModel):
    ticker: str
    name: str
    sector: str
    marketCap: float
    price: float
    change: float
    afterHoursChange: Optional[float] = None
    per: float
    roe: float


class HeatmapResponse(BaseModel):
    changesAvailable: bool
    tiles: list[HeatmapTile]
```

- [ ] **Step 2: Extend the shared `fake_loader` fixture with a `get_daily_changes` mock**

```python
# backend/tests/conftest.py — add this line inside the existing fake_loader() fixture,
# right after the `loader.get_stock_fundamentals.return_value = pd.DataFrame(...)` assignment,
# before the closing `return loader`
    loader.get_daily_changes.return_value = {"AAPL": {"change": 1.2, "after_hours_change": None}}
```

This is safe to add — no existing test calls `get_daily_changes`, so this new mocked attribute has no effect on any currently-passing test.

- [ ] **Step 3: Write the failing router tests**

```python
# backend/tests/test_heatmap_router.py
def test_get_heatmap_returns_tiles(client):
    res = client.get("/api/heatmap")

    assert res.status_code == 200
    body = res.json()
    assert body["changesAvailable"] is True
    assert body["tiles"][0]["ticker"] == "AAPL"
    assert body["tiles"][0]["change"] == 1.2
    assert body["tiles"][0]["price"] == 230.0
    assert body["tiles"][0]["afterHoursChange"] is None


def test_get_heatmap_excludes_zero_or_missing_market_cap(client, fake_loader):
    import pandas as pd

    fake_loader.get_stock_fundamentals.return_value = pd.DataFrame(
        {
            "Ticker": ["AAPL", "ZEROCAP"],
            "Name": ["Apple Inc.", "Zero Cap Co"],
            "Sector": ["Technology", "Technology"],
            "MarketCap": [3_500_000_000_000, 0],
            "Price": [230.0, 5.0],
            "PER": [28.1, 10.0],
            "ROE": [147.9, 5.0],
        }
    )
    fake_loader.get_daily_changes.return_value = {
        "AAPL": {"change": 1.2, "after_hours_change": None},
        "ZEROCAP": {"change": 0.0, "after_hours_change": None},
    }

    res = client.get("/api/heatmap")

    assert res.status_code == 200
    tickers = [t["ticker"] for t in res.json()["tiles"]]
    assert "ZEROCAP" not in tickers
    assert "AAPL" in tickers


def test_get_heatmap_changes_unavailable_when_batch_fails(client, fake_loader):
    fake_loader.get_daily_changes.return_value = {}

    res = client.get("/api/heatmap")

    assert res.status_code == 200
    body = res.json()
    assert body["changesAvailable"] is False
    assert body["tiles"][0]["change"] == 0.0


def test_get_heatmap_returns_503_when_fundamentals_empty(client, fake_loader):
    import pandas as pd

    fake_loader.get_stock_fundamentals.return_value = pd.DataFrame(
        columns=["Ticker", "Name", "Sector", "MarketCap", "Price", "PER", "ROE"]
    )

    res = client.get("/api/heatmap")

    assert res.status_code == 503
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
cd ~/develop/workspace/invest-support-web/backend
source .venv/bin/activate
pytest tests/test_heatmap_router.py -v
```

Expected: all 4 fail with `404 Not Found` (route doesn't exist yet) or a collection error if `client` fixture doesn't yet know about the route — either way, non-passing.

- [ ] **Step 5: Implement the router**

```python
# backend/app/routers/heatmap.py
from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_cache, get_loader
from app.heatmap import get_daily_changes_cached, get_heatmap_fundamentals
from app.schemas import HeatmapResponse, HeatmapTile

router = APIRouter(prefix="/api/heatmap", tags=["heatmap"])


@router.get("", response_model=HeatmapResponse)
async def get_heatmap(cache=Depends(get_cache), loader=Depends(get_loader)) -> HeatmapResponse:
    fund_df = await get_heatmap_fundamentals(cache, loader)
    if fund_df.empty:
        raise HTTPException(status_code=503, detail="market_data_unavailable")

    tickers = fund_df["Ticker"].tolist()
    changes = await get_daily_changes_cached(cache, loader, tickers)
    changes_available = len(changes) > 0

    tiles = []
    for r in fund_df.to_dict(orient="records"):
        market_cap = r.get("MarketCap", 0)
        if market_cap is None or market_cap <= 0:
            continue
        change_info = changes.get(r["Ticker"], {})
        tiles.append(
            HeatmapTile(
                ticker=r["Ticker"],
                name=r["Name"],
                sector=r["Sector"],
                marketCap=market_cap,
                price=r.get("Price", 0),
                change=change_info.get("change", 0.0),
                afterHoursChange=change_info.get("after_hours_change"),
                per=r.get("PER", 0),
                roe=r.get("ROE", 0),
            )
        )

    return HeatmapResponse(changesAvailable=changes_available, tiles=tiles)
```

- [ ] **Step 6: Register the router in `main.py`**

```python
# backend/app/main.py — full replacement
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.heatmap import router as heatmap_router
from app.routers.screener import router as screener_router

app = FastAPI(title="Invest Support API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(screener_router)
app.include_router(heatmap_router)
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
cd ~/develop/workspace/invest-support-web/backend
source .venv/bin/activate
pytest -v
```

Expected: all previously-passing tests still pass, plus the 4 new heatmap router tests — `33 passed`.

- [ ] **Step 8: Commit**

```bash
cd ~/develop/workspace/invest-support-web
git add backend/app/schemas.py backend/app/routers/heatmap.py backend/app/main.py backend/tests/conftest.py backend/tests/test_heatmap_router.py
git commit -m "feat: add GET /api/heatmap endpoint"
```

---

### Task 4: Manual backend E2E smoke test

**Files:** none (verification only)

**Interfaces:** none — validates Tasks 1-3 together against real data before frontend work begins.

- [ ] **Step 1: Start the backend**

```bash
cd ~/develop/workspace/invest-support-web/backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Expected: starts with no import errors, both `screener` and `heatmap` routers registered (check `http://127.0.0.1:8000/docs` shows both).

- [ ] **Step 2: Hit the heatmap endpoint**

```bash
curl -s http://127.0.0.1:8000/api/heatmap | python3 -m json.tool | head -30
```

Expected: JSON with `changesAvailable: true` and a `tiles` array of ~500 S&P 500 stocks. If the on-disk fundamentals cache (`backend/data/us_fundamentals.csv`) is already warm from earlier screener testing, this should be fast (a few seconds); if cold, allow 1-2 minutes for the fundamentals fetch.

- [ ] **Step 3: Confirm the 30-minute cache is working**

```bash
time curl -s http://127.0.0.1:8000/api/heatmap > /dev/null
```

Expected: well under a second on the second call — confirms both the day-scoped fundamentals cache and the TTL-scoped daily-changes cache are being hit, not re-fetched.

- [ ] **Step 4: Spot-check a specific tile's shape**

```bash
curl -s http://127.0.0.1:8000/api/heatmap | python3 -c "
import json, sys
data = json.load(sys.stdin)
tile = data['tiles'][0]
print(tile)
assert isinstance(tile['change'], (int, float))
assert isinstance(tile['price'], (int, float))
assert tile['marketCap'] > 0
print('OK')
"
```

Expected: prints a real tile dict, then `OK`.

No commit for this task — it's a verification checkpoint. If any step fails, fix the underlying task before moving to the frontend.

---

### Task 5: API client (types + `heatmap.ts`)

**Files:**
- Modify: `frontend/src/api/types.ts` (add `HeatmapTile`, `HeatmapResponse`)
- Create: `frontend/src/api/heatmap.ts`

**Interfaces:**
- Consumes: backend response shape from Task 3 (`HeatmapResponse` — field names match exactly, camelCase on both sides)
- Produces: `getHeatmap(): Promise<HeatmapResponse>` — Task 7's `HeatmapPage` calls this directly.

- [ ] **Step 1: Add the types**

```ts
// frontend/src/api/types.ts — append
export interface HeatmapTile {
  ticker: string
  name: string
  sector: string
  marketCap: number
  price: number
  change: number
  afterHoursChange: number | null
  per: number
  roe: number
}

export interface HeatmapResponse {
  changesAvailable: boolean
  tiles: HeatmapTile[]
}
```

- [ ] **Step 2: Implement the API client function**

```ts
// frontend/src/api/heatmap.ts
import type { HeatmapResponse } from "./types"

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"

export async function getHeatmap(): Promise<HeatmapResponse> {
  const res = await fetch(`${BASE_URL}/api/heatmap`)
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${await res.text()}`)
  }
  return res.json() as Promise<HeatmapResponse>
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
git add frontend/src/api/types.ts frontend/src/api/heatmap.ts
git commit -m "feat: add typed API client for heatmap endpoint"
```

---

### Task 6: `MarketHeatmap` chart component

**Files:**
- Create: `frontend/src/components/MarketHeatmap.tsx`

**Interfaces:**
- Consumes: `HeatmapTile[]` (Task 5's types)
- Produces: `<MarketHeatmap tiles={...} />` — a presentational component taking `tiles: HeatmapTile[]` as its only prop. Task 7 renders it.

- [ ] **Step 1: Implement `MarketHeatmap`**

```tsx
// frontend/src/components/MarketHeatmap.tsx
import Plot from "react-plotly.js"
import type { HeatmapTile } from "@/api/types"

interface MarketHeatmapProps {
  tiles: HeatmapTile[]
}

function formatMarketCap(n: number): string {
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`
  return `$${n.toFixed(0)}`
}

export function MarketHeatmap({ tiles }: MarketHeatmapProps) {
  // Same flat labels/parents 2-level pattern as SectorTreemap (screener page):
  // Plotly's treemap trace requires every `parents` value to also appear in
  // `labels`, or it treats it as an implied root — and tolerates only ONE such
  // value. A real market has 10+ sectors, so each sector needs its own
  // explicit label node (parent: "", value: 0, branchvalues: "remainder") or
  // Plotly refuses to render ("Multiple implied roots").
  const sectors = Array.from(new Set(tiles.map((t) => t.sector || "Unknown")))

  const labels = [...sectors, ...tiles.map((t) => `${t.name} (${t.ticker})`)]
  const parents = [...sectors.map(() => ""), ...tiles.map((t) => t.sector || "Unknown")]
  const values = [...sectors.map(() => 0), ...tiles.map((t) => Math.max(t.marketCap, 1e-6))]
  const colors = [
    ...sectors.map((sector) => {
      const sectorTiles = tiles.filter((t) => (t.sector || "Unknown") === sector)
      const totalCap = sectorTiles.reduce((sum, t) => sum + t.marketCap, 0)
      if (totalCap === 0) return 0
      return sectorTiles.reduce((sum, t) => sum + t.change * t.marketCap, 0) / totalCap
    }),
    ...tiles.map((t) => t.change),
  ]
  const text = [
    ...sectors.map(() => ""),
    ...tiles.map((t) => `${t.change >= 0 ? "+" : ""}${t.change.toFixed(2)}%`),
  ]
  const hovertext = [
    ...sectors.map((sector) => sector),
    ...tiles.map((t) => {
      const lines = [
        `${t.name} (${t.ticker})`,
        `현재가: $${t.price.toFixed(2)}`,
        `등락률: ${t.change >= 0 ? "+" : ""}${t.change.toFixed(2)}%`,
        `시가총액: ${formatMarketCap(t.marketCap)}`,
        `PER: ${t.per.toFixed(1)} / ROE: ${t.roe.toFixed(1)}%`,
      ]
      if (t.afterHoursChange !== null) {
        lines.push(
          `애프터마켓 등락률: ${t.afterHoursChange >= 0 ? "+" : ""}${t.afterHoursChange.toFixed(2)}%`,
        )
      }
      return lines.join("<br>")
    }),
  ]

  const maxAbsChange = Math.max(...tiles.map((t) => Math.abs(t.change)), 1)

  return (
    <Plot
      data={[
        {
          type: "treemap",
          labels,
          parents,
          values,
          branchvalues: "remainder",
          marker: {
            colors,
            colorscale: "RdYlGn",
            cmid: 0,
            cmin: -maxAbsChange,
            cmax: maxAbsChange,
          },
          text,
          hovertext,
          hoverinfo: "text",
        },
      ]}
      layout={{
        title: { text: "S&P 500 마켓 히트맵 (박스 크기: 시가총액, 색상: 당일 등락률)" },
        margin: { t: 30, l: 10, r: 10, b: 10 },
        height: 700,
      }}
      style={{ width: "100%" }}
      useResizeHandler
    />
  )
}
```

- [ ] **Step 2: Verify it compiles**

```bash
cd ~/develop/workspace/invest-support-web/frontend
npx tsc --noEmit
```

Expected: no type errors.

- [ ] **Step 3: Commit**

```bash
cd ~/develop/workspace/invest-support-web
git add frontend/src/components/MarketHeatmap.tsx
git commit -m "feat: add MarketHeatmap treemap component"
```

---

### Task 7: `HeatmapPage` with 30-minute polling + nav switcher in `App.tsx`

**Files:**
- Create: `frontend/src/pages/HeatmapPage.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `getHeatmap` (Task 5), `MarketHeatmap` (Task 6), shadcn/ui `Badge` (already installed, Task 9 of the screener MVP)
- Produces: `<HeatmapPage />`. `App.tsx` now renders either `<ScreenerPage />` or `<HeatmapPage />` based on local state — no routing library is introduced for just 2 pages, consistent with this project's YAGNI approach so far.

- [ ] **Step 1: Implement `HeatmapPage`**

```tsx
// frontend/src/pages/HeatmapPage.tsx
import { useEffect, useRef, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { getHeatmap } from "@/api/heatmap"
import type { HeatmapResponse } from "@/api/types"
import { MarketHeatmap } from "@/components/MarketHeatmap"

const POLL_INTERVAL_MS = 30 * 60 * 1000

export function HeatmapPage() {
  const [data, setData] = useState<HeatmapResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  // A plain `data` check inside the effect's closure would always read the
  // value from the initial render (the effect body only runs once, on
  // mount, since its dependency array is empty) and would never reflect
  // state set by an earlier poll. A ref is mutated in place and always
  // reflects the latest value, so a later poll's failure can correctly
  // tell whether an earlier poll already succeeded.
  const hasDataRef = useRef(false)

  useEffect(() => {
    let ignore = false

    const fetchHeatmap = () => {
      getHeatmap()
        .then((res) => {
          if (!ignore) {
            setData(res)
            setError(null)
            hasDataRef.current = true
          }
        })
        .catch((err) => {
          // A polling refresh failing shouldn't blank out an already-rendered
          // heatmap — only surface an error banner if we have no data yet.
          if (!ignore && !hasDataRef.current) {
            setError(err instanceof Error ? err.message : "알 수 없는 오류")
          }
        })
    }

    fetchHeatmap()
    const interval = setInterval(fetchHeatmap, POLL_INTERVAL_MS)

    return () => {
      ignore = true
      clearInterval(interval)
    }
  }, [])

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-8">
      <h1 className="text-xl font-semibold">🗺️ 마켓 히트맵 (S&P 500)</h1>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {data && !data.changesAvailable && (
        <Badge variant="destructive">
          당일 등락률 데이터를 가져오지 못해 중립색으로 표시됩니다
        </Badge>
      )}

      {data && <MarketHeatmap tiles={data.tiles} />}
      {!data && !error && <p className="text-sm text-muted-foreground">로딩 중...</p>}
    </div>
  )
}
```

- [ ] **Step 2: Wire a simple nav switcher into `App.tsx`**

```tsx
// frontend/src/App.tsx
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { ScreenerPage } from "@/pages/ScreenerPage"
import { HeatmapPage } from "@/pages/HeatmapPage"

type Page = "screener" | "heatmap"

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
      </nav>
      {page === "screener" ? <ScreenerPage /> : <HeatmapPage />}
    </div>
  )
}

export default App
```

- [ ] **Step 3: Manual browser verification**

```bash
# terminal 1
cd ~/develop/workspace/invest-support-web/backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000

# terminal 2
cd ~/develop/workspace/invest-support-web/frontend && npm run dev -- --port 5173
```

Open `http://localhost:5173`. Confirm: the nav bar shows both buttons, defaults to the screener page, clicking "마켓 히트맵" switches to the heatmap page and it loads real S&P 500 data with a treemap colored by daily change (red/green diverging around 0), hovering a tile shows the full text block (name, price, change, market cap, PER/ROE, and after-hours line only when present). Switching back to "퀀트 스크리너" and back to "마켓 히트맵" should not re-fetch unnecessarily fast/slow in a broken way (a quick manual toggle is fine — the polling interval only matters over a much longer time horizon than manual testing can observe, so just confirm the initial load works and there's no crash on remount). Stop both servers.

- [ ] **Step 4: Commit**

```bash
cd ~/develop/workspace/invest-support-web
git add frontend/src/pages/HeatmapPage.tsx frontend/src/App.tsx
git commit -m "feat: add HeatmapPage with 30-minute polling and app nav switcher"
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

- [ ] **Step 2: Walk through both pages**

Open `http://localhost:5173`. Confirm the screener page (from the prior MVP) still works exactly as before (regression check — this feature must not have broken it), then switch to the heatmap page and confirm real data renders with correct hover content for at least 3 different tiles across different sectors (including one mega-cap and one smaller-cap stock, to sanity-check the box-size scaling still reads sensibly).

- [ ] **Step 3: Verify the error path**

Stop the backend server while the frontend is on the heatmap page. Reload — confirm the error banner (`text-destructive` paragraph) appears rather than a blank page or crash.

- [ ] **Step 4: Verify no duplicate data collection with the screener page**

Restart the backend fresh (`rm -rf data logs` first). Load the screener page for US market (this fetches and disk-caches `us_fundamentals.csv`), then switch to the heatmap page. Confirm via backend terminal logs that the heatmap page's fundamentals fetch is a cache hit (`Using cached us fundamentals from data/us_fundamentals.csv`), not a second full S&P 500 download — this is the same underlying disk cache the screener already populated.

- [ ] **Step 5: Report status**

No commit for this task. If all steps pass, this feature is complete.

---

## Self-Review Notes

- **Spec coverage:** `ttl_seconds` cache extension (Task 1), both cached helpers with disk-cache reuse (Task 2), the endpoint with all 4 error/edge cases from the spec's error table (Task 3), 30-min polling (Task 7), hover content order including conditional after-hours line and 2-decimal price (Task 6), US-only scope, no tile-click interaction, flat 2-level treemap reusing the screener's implied-roots fix (Task 6) — all covered.
- **Type consistency:** `HeatmapTile`/`HeatmapResponse` field names are camelCase and identical between `backend/app/schemas.py` and `frontend/src/api/types.ts`, checked against each producing task.
- **No placeholders:** every step has literal file contents or literal commands with expected output.
