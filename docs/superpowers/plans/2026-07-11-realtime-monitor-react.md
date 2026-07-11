# Real-time Market Monitor React Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real-time market monitor page to `invest-support-web` — 9 TradingView widgets (index futures, VIX/oil/gold, forex/BTC) plus 3 treasury-yield mini-charts (5-minute bars) — per `docs/superpowers/specs/2026-07-11-realtime-monitor-react-design.md`.

**Architecture:** This feature is mostly frontend work. A shared `TradingViewWidget` component loads TradingView's external script exactly once per page (module-level singleton promise) and instantiates a widget per container on mount, cleaning up by removing its container on unmount. One thin backend endpoint (`GET /api/realtime/yield/{name}`) wraps `DataLoader.get_market_history(name, period="1d", interval="5m")` directly — no new app-level caching, since the existing disk-level intraday cache (1-hour freshness, already in `modules/data_loader.py`, unmodified) is sufficient for a single-ticker fetch.

**Tech Stack:** Same as the existing project — Python 3.14 / FastAPI / Pydantic v2 / pandas (backend) — TypeScript / Vite / React / Tailwind CSS / shadcn/ui / react-plotly.js (frontend). No new dependencies (TradingView's script is loaded directly via a `<script>` tag, not an npm package).

## Global Constraints

- 9 TradingView widgets, exact symbols and layout from the original Streamlit app: **지수선물** (나스닥100 `CAPITALCOM:US100`, S&P500 `CAPITALCOM:US500`, 다우30 `CAPITALCOM:US30`, height 450) — **매크로&공포지수** (VIX `CAPITALCOM:VIX`, WTI유가 `CAPITALCOM:OIL_CRUDE`, 국제금 `CAPITALCOM:GOLD`, height 400) — **외환/원자재** (원달러 `FX_IDC:USDKRW`, 달러인덱스 `CAPITALCOM:DXY`, 비트코인 `BINANCE:BTCUSDT`, height 400).
- 3 treasury-yield mini-charts (US30Y/US10Y/US5Y, 5-minute bars via Yahoo Finance/`DataLoader`, since TradingView doesn't support these symbols) — same 매크로&공포지수 section as VIX/oil/gold, height 400.
- Yield mini-charts poll every 5 minutes on the frontend (matching the bar granularity), using the same `ignore`-flag pattern as the heatmap feature's polling.
- TradingView script load failures are NOT surfaced as error banners — an empty widget container is acceptable (matches the original's lack of any such handling).
- `PricePoint` schema (fields `date: str`, `value: float`) may already exist in `backend/app/schemas.py` if the market-attractiveness plan (`2026-07-11-market-attractiveness-react.md`) has been executed first — reuse it if present, only add it if missing (see Task 1, Step 1).
- `main.py` and `App.tsx` changes are additive, not full-file replacements assuming one specific prior state — this plan does not assume whether the heatmap or attractiveness plans have executed yet.

---

## File Structure

```
backend/app/
├── schemas.py           # MODIFY: add PricePoint (if not already present) + YieldChartResponse
├── main.py              # MODIFY: register the new realtime router
└── routers/
    └── realtime.py         # NEW: GET /api/realtime/yield/{name}
backend/tests/
└── test_realtime_router.py  # NEW: router-level tests

frontend/src/
├── api/
│   ├── types.ts           # MODIFY: add YieldChartResponse type (if not already present via PricePoint)
│   └── realtime.ts         # NEW: getYieldChart(name)
├── components/
│   ├── TradingViewWidget.tsx  # NEW: shared script-loader singleton + per-instance widget lifecycle
│   └── YieldMiniChart.tsx     # NEW: 5-min-polling treasury yield mini-chart
├── pages/
│   └── RealtimeMonitorPage.tsx  # NEW: 3-section grid assembling all 12 widgets
└── App.tsx                # MODIFY: add a nav option for this page
```

---

### Task 1: `GET /api/realtime/yield/{name}` endpoint

**Files:**
- Modify: `backend/app/schemas.py`
- Create: `backend/app/routers/realtime.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_realtime_router.py`

**Interfaces:**
- Consumes: `DataLoader.get_market_history(name, period="1d", interval="5m")` (pre-existing, unmodified), `get_loader` (existing `app/dependencies.py`)
- Produces: `YieldChartResponse` Pydantic model. Task 3's frontend API client is the sole consumer.

- [ ] **Step 1: Add schemas**

First check whether `PricePoint` already exists in `backend/app/schemas.py`:

```bash
grep -n "class PricePoint" backend/app/schemas.py
```

If it's ALREADY present (e.g. the market-attractiveness plan ran first), skip adding it and only append `YieldChartResponse`. If it's NOT present, add both:

```python
# backend/app/schemas.py — append to existing file (only add PricePoint if grep above found nothing)
class PricePoint(BaseModel):
    date: str
    value: float


class YieldChartResponse(BaseModel):
    current: float
    changePct: float
    series: list[PricePoint]
```

- [ ] **Step 2: Write the failing router tests**

```python
# backend/tests/test_realtime_router.py
from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_loader
from app.main import app


@pytest.fixture
def realtime_loader():
    loader = MagicMock()
    dates = pd.date_range("2026-07-11 09:30", periods=3, freq="5min")
    loader.get_market_history.return_value = pd.DataFrame({"Close": [4.20, 4.22, 4.25]}, index=dates)
    return loader


@pytest.fixture
def realtime_client(realtime_loader):
    app.dependency_overrides[get_loader] = lambda: realtime_loader
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_yield_chart_returns_series(realtime_client, realtime_loader):
    res = realtime_client.get("/api/realtime/yield/US10Y")

    assert res.status_code == 200
    body = res.json()
    assert body["current"] == 4.25
    assert len(body["series"]) == 3
    realtime_loader.get_market_history.assert_called_once_with("US10Y", period="1d", interval="5m")


def test_get_yield_chart_returns_503_when_data_unavailable(realtime_client, realtime_loader):
    realtime_loader.get_market_history.return_value = None

    res = realtime_client.get("/api/realtime/yield/US10Y")

    assert res.status_code == 503


def test_get_yield_chart_invalid_name_returns_422(realtime_client):
    res = realtime_client.get("/api/realtime/yield/US7Y")
    assert res.status_code == 422
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd ~/develop/workspace/invest-support-web/backend
source .venv/bin/activate
pytest tests/test_realtime_router.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.routers.realtime'` (or a collection error referencing it).

- [ ] **Step 4: Implement the router**

```python
# backend/app/routers/realtime.py
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_loader
from app.schemas import YieldChartResponse

YieldName = Literal["US30Y", "US10Y", "US5Y"]

router = APIRouter(prefix="/api/realtime", tags=["realtime"])


@router.get("/yield/{name}", response_model=YieldChartResponse)
async def get_yield_chart(name: YieldName, loader=Depends(get_loader)) -> YieldChartResponse:
    data = loader.get_market_history(name, period="1d", interval="5m")
    if data is None or data.empty:
        raise HTTPException(status_code=503, detail="yield_data_unavailable")

    close = data["Close"]
    change_pct = float((close.iloc[-1] / close.iloc[0] - 1) * 100) if len(close) > 1 else 0.0
    return YieldChartResponse(
        current=float(close.iloc[-1]),
        changePct=change_pct,
        series=[{"date": str(idx), "value": float(v)} for idx, v in close.items()],
    )
```

- [ ] **Step 5: Register the router in `main.py`**

```python
# backend/app/main.py — add this import near the other router imports
from app.routers.realtime import router as realtime_router
```

```python
# backend/app/main.py — add this line near the other app.include_router(...) calls
app.include_router(realtime_router)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd ~/develop/workspace/invest-support-web/backend
source .venv/bin/activate
pytest -v
```

Expected: all previously-passing tests still pass, plus the 3 new realtime router tests.

- [ ] **Step 7: Commit**

```bash
cd ~/develop/workspace/invest-support-web
git add backend/app/schemas.py backend/app/routers/realtime.py backend/app/main.py backend/tests/test_realtime_router.py
git commit -m "feat: add GET /api/realtime/yield/{name} endpoint"
```

---

### Task 2: Manual backend E2E smoke test

**Files:** none (verification only)

**Interfaces:** none — validates Task 1 against real data.

- [ ] **Step 1: Start the backend**

```bash
cd ~/develop/workspace/invest-support-web/backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 2: Hit the endpoint for each yield name**

```bash
curl -s http://127.0.0.1:8000/api/realtime/yield/US30Y | python3 -m json.tool | head -20
curl -s http://127.0.0.1:8000/api/realtime/yield/US10Y | python3 -m json.tool | head -20
curl -s http://127.0.0.1:8000/api/realtime/yield/US5Y | python3 -m json.tool | head -20
```

Expected: each returns real 5-minute-bar data (`current` a plausible yield percentage like 4.x, `series` with several points — fewer points outside market hours since intraday data only accumulates during the trading session).

No commit for this task — it's a verification checkpoint.

---

### Task 3: API client (`realtime.ts`)

**Files:**
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/api/realtime.ts`

**Interfaces:**
- Consumes: backend response shape from Task 1
- Produces: `getYieldChart(name): Promise<YieldChartResponse>` — Task 5's `YieldMiniChart` calls this directly.

- [ ] **Step 1: Add the types**

First check whether `PricePoint` already exists in `frontend/src/api/types.ts`:

```bash
grep -n "interface PricePoint" frontend/src/api/types.ts
```

If already present, skip it and only append `YieldChartResponse`/`YieldName`. If not present, add both:

```ts
// frontend/src/api/types.ts — append (only add PricePoint if grep above found nothing)
export interface PricePoint {
  date: string
  value: number
}

export type YieldName = "US30Y" | "US10Y" | "US5Y"

export interface YieldChartResponse {
  current: number
  changePct: number
  series: PricePoint[]
}
```

- [ ] **Step 2: Implement the API client function**

```ts
// frontend/src/api/realtime.ts
import type { YieldChartResponse, YieldName } from "./types"

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"

export async function getYieldChart(name: YieldName): Promise<YieldChartResponse> {
  const res = await fetch(`${BASE_URL}/api/realtime/yield/${name}`)
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${await res.text()}`)
  }
  return res.json() as Promise<YieldChartResponse>
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
git add frontend/src/api/types.ts frontend/src/api/realtime.ts
git commit -m "feat: add typed API client for realtime yield endpoint"
```

---

### Task 4: `TradingViewWidget` component

**Files:**
- Create: `frontend/src/components/TradingViewWidget.tsx`

**Interfaces:**
- Consumes: nothing from this project (wraps an external third-party script)
- Produces: `<TradingViewWidget symbol={...} height={...} interval={...} />` — a presentational component. Task 6 renders 9 instances of it.

- [ ] **Step 1: Implement `TradingViewWidget`**

```tsx
// frontend/src/components/TradingViewWidget.tsx
import { useEffect, useId, useRef } from "react"

declare global {
  interface Window {
    TradingView?: {
      widget: new (options: Record<string, unknown>) => unknown
    }
  }
}

let scriptPromise: Promise<void> | null = null

// TradingView's tv.js exposes a global `window.TradingView` once loaded and
// supports creating multiple independent widget instances from it — the
// script itself only needs to load once per page, not once per widget. This
// module-level singleton promise ensures concurrent widget mounts (all 9 on
// this page mount together) share one script load instead of racing to
// insert duplicate <script> tags.
function loadTradingViewScript(): Promise<void> {
  if (scriptPromise) return scriptPromise
  scriptPromise = new Promise((resolve, reject) => {
    if (window.TradingView) {
      resolve()
      return
    }
    const script = document.createElement("script")
    script.src = "https://s3.tradingview.com/tv.js"
    script.onload = () => resolve()
    script.onerror = () => reject(new Error("Failed to load TradingView script"))
    document.head.appendChild(script)
  })
  return scriptPromise
}

interface TradingViewWidgetProps {
  symbol: string
  height?: number
  interval?: string
}

export function TradingViewWidget({ symbol, height = 400, interval = "5" }: TradingViewWidgetProps) {
  const rawId = useId()
  const containerId = `tv_${rawId.replace(/[^a-zA-Z0-9]/g, "_")}`
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false

    loadTradingViewScript()
      .then(() => {
        if (cancelled || !containerRef.current || !window.TradingView) return
        new window.TradingView.widget({
          autosize: true,
          symbol,
          interval,
          timezone: "Asia/Seoul",
          theme: "dark",
          style: "1",
          locale: "kr",
          toolbar_bg: "#f1f3f6",
          enable_publishing: false,
          hide_side_toolbar: false,
          allow_symbol_change: true,
          container_id: containerId,
        })
      })
      .catch(() => {
        // TradingView script failures are not surfaced as error banners —
        // an empty widget container is the accepted degraded state, matching
        // the original Streamlit app's lack of any such handling.
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, interval, containerId])

  return <div id={containerId} ref={containerRef} style={{ height, width: "100%" }} />
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
git add frontend/src/components/TradingViewWidget.tsx
git commit -m "feat: add TradingViewWidget component"
```

---

### Task 5: `YieldMiniChart` component

**Files:**
- Create: `frontend/src/components/YieldMiniChart.tsx`

**Interfaces:**
- Consumes: `getYieldChart` (Task 3)
- Produces: `<YieldMiniChart name={...} label={...} />`. Task 6 renders 3 instances of it.

- [ ] **Step 1: Implement `YieldMiniChart`**

```tsx
// frontend/src/components/YieldMiniChart.tsx
import { useEffect, useRef, useState } from "react"
import Plot from "react-plotly.js"
import { getYieldChart } from "@/api/realtime"
import type { YieldChartResponse, YieldName } from "@/api/types"

const POLL_INTERVAL_MS = 5 * 60 * 1000

interface YieldMiniChartProps {
  name: YieldName
  label: string
  height?: number
}

export function YieldMiniChart({ name, label, height = 400 }: YieldMiniChartProps) {
  const [data, setData] = useState<YieldChartResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const hasDataRef = useRef(false)

  useEffect(() => {
    let ignore = false

    const fetchYield = () => {
      getYieldChart(name)
        .then((res) => {
          if (!ignore) {
            setData(res)
            setError(null)
            hasDataRef.current = true
          }
        })
        .catch((err) => {
          if (!ignore && !hasDataRef.current) {
            setError(err instanceof Error ? err.message : "데이터를 가져올 수 없습니다.")
          }
        })
    }

    fetchYield()
    const interval = setInterval(fetchYield, POLL_INTERVAL_MS)

    return () => {
      ignore = true
      clearInterval(interval)
    }
  }, [name])

  if (error && !data) {
    return (
      <div>
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="text-sm text-destructive">{error}</p>
      </div>
    )
  }

  if (!data) {
    return (
      <div>
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="text-sm text-muted-foreground">로딩 중...</p>
      </div>
    )
  }

  return (
    <Plot
      data={[
        {
          type: "scatter",
          mode: "lines",
          x: data.series.map((p) => p.date),
          y: data.series.map((p) => p.value),
          line: { color: "#ffdd57" },
        },
      ]}
      layout={{
        title: { text: `${data.current.toFixed(3)}% (${data.changePct >= 0 ? "+" : ""}${data.changePct.toFixed(3)}%)` },
        height,
        margin: { l: 10, r: 10, t: 40, b: 10 },
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
git add frontend/src/components/YieldMiniChart.tsx
git commit -m "feat: add YieldMiniChart component with 5-minute polling"
```

---

### Task 6: `RealtimeMonitorPage` + nav update

**Files:**
- Create: `frontend/src/pages/RealtimeMonitorPage.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `TradingViewWidget` (Task 4), `YieldMiniChart` (Task 5)
- Produces: `<RealtimeMonitorPage />`. `App.tsx` gains a nav option for this page.

- [ ] **Step 1: Implement `RealtimeMonitorPage`**

```tsx
// frontend/src/pages/RealtimeMonitorPage.tsx
import { TradingViewWidget } from "@/components/TradingViewWidget"
import { YieldMiniChart } from "@/components/YieldMiniChart"

export function RealtimeMonitorPage() {
  return (
    <div className="mx-auto max-w-6xl space-y-6 p-8">
      <h1 className="text-xl font-semibold">🚀 실시간 마켓 모니터 (5분봉)</h1>

      <section className="space-y-2">
        <h2 className="text-lg font-medium">📊 주요 지수 선물</h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div>
            <p className="text-sm text-muted-foreground">나스닥 100 (US100)</p>
            <TradingViewWidget symbol="CAPITALCOM:US100" height={450} />
          </div>
          <div>
            <p className="text-sm text-muted-foreground">S&P 500 (US500)</p>
            <TradingViewWidget symbol="CAPITALCOM:US500" height={450} />
          </div>
          <div>
            <p className="text-sm text-muted-foreground">다우 30 (US30)</p>
            <TradingViewWidget symbol="CAPITALCOM:US30" height={450} />
          </div>
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-medium">🌐 실시간 매크로 & 공포 지수</h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <YieldMiniChart name="US30Y" label="미국채 30년물 수익률 (30Y)" />
          <YieldMiniChart name="US10Y" label="미국채 10년물 수익률 (10Y)" />
          <YieldMiniChart name="US5Y" label="미국채 5년물 수익률 (5Y)" />
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div>
            <p className="text-sm text-muted-foreground">변동성 지수 (VIX)</p>
            <TradingViewWidget symbol="CAPITALCOM:VIX" />
          </div>
          <div>
            <p className="text-sm text-muted-foreground">WTI 유가 (Oil)</p>
            <TradingViewWidget symbol="CAPITALCOM:OIL_CRUDE" />
          </div>
          <div>
            <p className="text-sm text-muted-foreground">국제 금 시세 (Gold)</p>
            <TradingViewWidget symbol="CAPITALCOM:GOLD" />
          </div>
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-medium">💱 외환 및 핵심 지표</h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div>
            <p className="text-sm text-muted-foreground">원/달러 환율 (USDKRW)</p>
            <TradingViewWidget symbol="FX_IDC:USDKRW" />
          </div>
          <div>
            <p className="text-sm text-muted-foreground">달러 인덱스 (DXY)</p>
            <TradingViewWidget symbol="CAPITALCOM:DXY" />
          </div>
          <div>
            <p className="text-sm text-muted-foreground">비트코인 (BTC/USD)</p>
            <TradingViewWidget symbol="BINANCE:BTCUSDT" />
          </div>
        </div>
      </section>
    </div>
  )
}
```

- [ ] **Step 2: Add a nav option to `App.tsx`**

First read the current `frontend/src/App.tsx` to see which other pages (heatmap, attractiveness) already exist — this plan does not assume a fixed prior state. Add a `"realtime"` entry to whatever `Page` union / nav button list / render-branch structure is already there, following the exact same pattern as the existing entries (a `Button` with `variant={page === "realtime" ? "default" : "outline"}`, and a `{page === "realtime" && <RealtimeMonitorPage />}` render branch). If `App.tsx` currently renders only `<ScreenerPage />` with no nav bar yet (i.e. neither the heatmap nor attractiveness plans have executed), use this as the full replacement:

```tsx
// frontend/src/App.tsx — use as full replacement ONLY if no other page-switching nav exists yet;
// otherwise, add the "realtime" entry to the existing Page union/nav/render-branch pattern instead
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { ScreenerPage } from "@/pages/ScreenerPage"
import { RealtimeMonitorPage } from "@/pages/RealtimeMonitorPage"

type Page = "screener" | "realtime"

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
          variant={page === "realtime" ? "default" : "outline"}
          onClick={() => setPage("realtime")}
        >
          실시간 마켓 모니터
        </Button>
      </nav>
      {page === "screener" && <ScreenerPage />}
      {page === "realtime" && <RealtimeMonitorPage />}
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

Open `http://localhost:5173`, click into the realtime monitor tab. Confirm: all 9 TradingView widget containers render actual embedded charts (not blank boxes — open browser dev tools and confirm no repeated/duplicate script-tag insertions if you toggle away and back to this tab), and all 3 yield mini-charts show real 5-minute-bar data with a title showing current yield % and change. Stop both servers.

- [ ] **Step 4: Commit**

```bash
cd ~/develop/workspace/invest-support-web
git add frontend/src/pages/RealtimeMonitorPage.tsx frontend/src/App.tsx
git commit -m "feat: add RealtimeMonitorPage with TradingView widgets and yield charts"
```

---

### Task 7: Full end-to-end verification

**Files:** none (verification only)

**Interfaces:** none — final acceptance check for this feature.

- [ ] **Step 1: Start both servers fresh**

```bash
# terminal 1
cd ~/develop/workspace/invest-support-web/backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000

# terminal 2
cd ~/develop/workspace/invest-support-web/frontend && npm run dev -- --port 5173
```

- [ ] **Step 2: Walk through the realtime monitor page**

Confirm all 9 TradingView widgets load (each shows a real live/delayed chart, not an empty box) and all 3 yield mini-charts show real data with sensible values (roughly 3-5% for current 2026 treasury yields).

- [ ] **Step 3: Verify no script duplication on remount**

Switch away to another tab and back to the realtime monitor tab a few times. Confirm via browser dev tools (Elements panel, search for `<script src="https://s3.tradingview.com/tv.js">`) that only ONE such script tag exists in the document, regardless of how many times the page remounts — this confirms the module-level singleton promise in `TradingViewWidget` is working as intended.

- [ ] **Step 4: Verify the yield error path**

Stop the backend. Confirm the 3 yield mini-charts show "데이터를 가져올 수 없습니다." rather than crashing (the 9 TradingView widgets are unaffected by the backend being down, since they don't depend on it).

- [ ] **Step 5: Verify no regression on other pages**

Confirm the screener page (and heatmap/attractiveness pages, if implemented) still work exactly as before.

No commit for this task. If all steps pass, this feature is complete.

---

## Self-Review Notes

- **Spec coverage:** all 9 TradingView widgets with exact symbols/layout (Task 6), 3 yield mini-charts with 5-min polling (Task 5), script-load-failure handling (no error banner, Task 4), yield-fetch-failure handling (503 + per-widget error text, Task 1/5), no new app-level caching (Task 1 relies on `modules/data_loader.py`'s existing disk cache) — all covered.
- **Type consistency:** `YieldChartResponse`/`PricePoint`/`YieldName` identical camelCase field names between `backend/app/schemas.py` and `frontend/src/api/types.ts`, with explicit handling for the case where `PricePoint` was already added by the market-attractiveness plan.
- **No placeholders:** every step has literal file contents or literal commands with expected output. The one place this plan gives conditional instructions instead of a fixed diff (`App.tsx`, Task 6 Step 2) is because the actual prior file content genuinely depends on which other feature plans have executed first — the plan explains exactly how to detect and handle each case rather than leaving it vague.
