# LPPL Bubble Panel React Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the market-index-level LPPL bubble diagnosis panel (danger score, Tc date, R², fitted-curve chart overlay) to `invest-support-web`'s market attractiveness page, per `docs/superpowers/specs/2026-07-12-lppl-bubble-panel-react-design.md`.

**Architecture:** `backend/app/attractiveness.py`'s `get_market_attractiveness` already calls `engine.run_lppl_fit(prices)` today (only to feed `danger_score` into the target-weight calc) — this plan extracts more fields from that same already-computed result (no new expensive computation) and adds an `lppl` object to the existing response. The frontend gets one new component (`LPPLBubblePanel.tsx`) wired into the existing `AttractivenessPage.tsx`, right below its price chart.

**Tech Stack:** Same as the rest of this project — Python 3.14 / FastAPI / Pydantic v2 / pandas (backend), TypeScript / Vite / React / Tailwind CSS / shadcn/ui / react-plotly.js (frontend). No new dependencies.

## Global Constraints

- Status is a 3-tier Korean string computed server-side: `dangerScore >= engine.config.bubble_threshold` (70.0) → `"위험"`; `>= engine.config.warning_threshold` (40.0) → `"경계"`; else `"정상"`.
- When `run_lppl_fit` returns no valid window fit (no `"fitted"` key in its result), `tcDate`/`rSquared` must be `null` and `fittedSeries` must be `[]` — never fabricate values.
- `fittedSeries` dates are generated as `pd.date_range(start=prices.index[0], periods=len(fitted), freq="D")` — calendar days, matching the original Streamlit app's exact logic.
- No new backend cache entry — this rides on the existing `attractiveness:{market}:{period}` cache key.
- Frontend chart traces use `#3273dc` (actual price, matches the page's existing price chart) and `#ff8c00` dashed (LPPL fitted/prediction line) — not the original Streamlit app's cyan-on-dark-theme colors, since this app's charts are light-themed.
- Every new/touched Plotly chart in this task gets `xaxis: {automargin: true}` and `yaxis: {automargin: true}` from the start — this exact clipping bug (bottom date labels or left/title text cut off) has recurred 3 separate times this session from omitting it.
- No new automated frontend tests — matches this project's established pattern (frontend features are manually/live browser-verified, not unit-tested).

---

## File Structure

```
backend/app/
├── schemas.py           # MODIFY: add LPPLInfo, add `lppl: LPPLInfo` to AttractivenessResponse
└── attractiveness.py    # MODIFY: extract full LPPL result into the response
backend/tests/
└── test_attractiveness_router.py  # MODIFY: fixture needs engine.config thresholds; add 3 new LPPL-specific tests

frontend/src/
├── api/
│   └── types.ts                    # MODIFY: add LPPLInfo interface, add `lppl: LPPLInfo` to AttractivenessResponse
├── components/
│   └── LPPLBubblePanel.tsx         # NEW: metric cards + guide toggle + warning banner + chart
└── pages/
    └── AttractivenessPage.tsx      # MODIFY: render LPPLBubblePanel; fix pre-existing missing xaxis automargin on the price chart
```

---

### Task 1: Extend `GET /api/attractiveness/{marketName}` with LPPL detail fields

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/attractiveness.py`
- Modify: `backend/tests/test_attractiveness_router.py`

**Interfaces:**
- Consumes: `engine.run_lppl_fit(prices)` (pre-existing, unmodified — already called in this function), `engine.config.bubble_threshold` / `engine.config.warning_threshold` (pre-existing pydantic settings attributes on `AnalysisModel`)
- Produces: `LPPLInfo` Pydantic model, added as `AttractivenessResponse.lppl`. Task 3's frontend component is the sole consumer.

- [ ] **Step 1: Add the `LPPLInfo` schema**

```python
# backend/app/schemas.py — insert directly above `class AttractivenessResponse(BaseModel):`
class LPPLInfo(BaseModel):
    dangerScore: float
    status: str
    tcDate: str | None
    rSquared: float | None
    fittedSeries: list[PricePoint]
```

Then add one field to the existing `AttractivenessResponse` class (do not reorder or touch any other field):

```python
# backend/app/schemas.py — add this line inside class AttractivenessResponse, after `macro: MacroIndicators`
    lppl: LPPLInfo
```

- [ ] **Step 2: Write the failing tests**

First, update the shared `attractiveness_engine` fixture — every test using it will now exercise the new LPPL status-threshold comparison, so `engine.config` needs real numeric values instead of an auto-mocked `MagicMock` (comparing a `MagicMock` to a float with `>=` raises `TypeError`):

```python
# backend/tests/test_attractiveness_router.py — add this line inside the attractiveness_engine fixture,
# right after `engine.run_lppl_fit.return_value = {"danger_score": 18.0}`
    engine.config.bubble_threshold = 70.0
    engine.config.warning_threshold = 40.0
```

Now append these 3 new test functions to the end of the file:

```python
def test_get_attractiveness_lppl_full_fit_returns_bubble_status(attractiveness_client, attractiveness_engine):
    attractiveness_engine.run_lppl_fit.return_value = {
        "danger_score": 85.0,
        "is_bubble": True,
        "fitted": [100.0, 100.5, 101.0, 101.5, 102.0],
        "tc_date": pd.Timestamp("2024-02-15"),
        "r_squared": 0.87,
    }

    res = attractiveness_client.get("/api/attractiveness/S%26P500?period=2y")

    assert res.status_code == 200
    body = res.json()
    assert body["lppl"]["dangerScore"] == 85.0
    assert body["lppl"]["status"] == "위험"
    assert body["lppl"]["tcDate"] == "2024-02-15"
    assert body["lppl"]["rSquared"] == 0.87
    assert body["lppl"]["fittedSeries"] == [
        {"date": "2024-01-01", "value": 100.0},
        {"date": "2024-01-02", "value": 100.5},
        {"date": "2024-01-03", "value": 101.0},
        {"date": "2024-01-04", "value": 101.5},
        {"date": "2024-01-05", "value": 102.0},
    ]


def test_get_attractiveness_lppl_warning_tier_status(attractiveness_client, attractiveness_engine):
    attractiveness_engine.run_lppl_fit.return_value = {"danger_score": 50.0, "is_bubble": False}

    res = attractiveness_client.get("/api/attractiveness/S%26P500?period=2y")

    assert res.status_code == 200
    assert res.json()["lppl"]["status"] == "경계"


def test_get_attractiveness_lppl_no_fit_returns_null_fields(attractiveness_client, attractiveness_engine):
    attractiveness_engine.run_lppl_fit.return_value = {"danger_score": 10.0, "is_bubble": False}

    res = attractiveness_client.get("/api/attractiveness/S%26P500?period=2y")

    assert res.status_code == 200
    body = res.json()
    assert body["lppl"]["status"] == "정상"
    assert body["lppl"]["tcDate"] is None
    assert body["lppl"]["rSquared"] is None
    assert body["lppl"]["fittedSeries"] == []
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd ~/develop/workspace/invest-support-web/backend
source .venv/bin/activate
pytest tests/test_attractiveness_router.py -v
```

Expected: the 3 new tests FAIL with `KeyError: 'lppl'` (the response body has no `lppl` key yet), and the existing `test_get_attractiveness_returns_full_response` test also FAILS validating the response model (Pydantic will reject the response for missing the now-required `lppl` field) — this is expected until Step 4 is done.

- [ ] **Step 4: Implement the extraction logic**

```python
# backend/app/attractiveness.py — add this helper function above `async def get_market_attractiveness`
def _lppl_info(lppl_res, danger_score: float, prices: pd.Series, engine) -> dict:
    if danger_score >= engine.config.bubble_threshold:
        status = "위험"
    elif danger_score >= engine.config.warning_threshold:
        status = "경계"
    else:
        status = "정상"

    tc_date = None
    r_squared = None
    fitted_series: list[dict] = []
    if lppl_res and "fitted" in lppl_res:
        tc_date = lppl_res["tc_date"].strftime("%Y-%m-%d")
        r_squared = float(lppl_res["r_squared"])
        fitted = lppl_res["fitted"]
        dates = pd.date_range(start=prices.index[0], periods=len(fitted), freq="D")
        fitted_series = [{"date": str(d.date()), "value": float(v)} for d, v in zip(dates, fitted)]

    return {
        "dangerScore": danger_score,
        "status": status,
        "tcDate": tc_date,
        "rSquared": r_squared,
        "fittedSeries": fitted_series,
    }
```

Update the docstring (it currently claims LPPL detail is never exposed — no longer true):

```python
# backend/app/attractiveness.py — replace the existing docstring's LPPL line
    """market_name(S&P500/NASDAQ/KOSPI/KOSDAQ)의 5-Factor 매력도 + 목표비중 + 매크로/국채
    데이터를 한 번에 수집·계산해 당일 캐시에 저장한다.

    LPPL 피팅은 목표비중 산출과 버블 진단 패널(danger_score/Tc/R²/fitted curve) 양쪽에
    쓰인다 — 이미 계산된 동일한 run_lppl_fit 결과를 재사용할 뿐 추가 연산은 없다.
    """
```

Then, immediately after the existing line `target_weight = engine.calculate_target_weight(attr_res["score"], danger_score)` (do not change the two lines above it — `lppl_res = engine.run_lppl_fit(prices)` and `danger_score = lppl_res["danger_score"] if lppl_res else 0.0` stay exactly as they are):

```python
        lppl_info = _lppl_info(lppl_res, danger_score, prices, engine)
```

Finally, add one field to the `result` dict literal, directly after the existing `"macro": {...}` block's closing brace (i.e. as the last key in `result`):

```python
            "lppl": lppl_info,
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd ~/develop/workspace/invest-support-web/backend
source .venv/bin/activate
pytest tests/test_attractiveness_router.py -v
```

Expected: all tests pass, including the pre-existing ones.

- [ ] **Step 6: Run the full backend suite**

```bash
pytest -v
```

Expected: all previously-passing tests across the whole backend still pass (this task did not touch any other router).

- [ ] **Step 7: Commit**

```bash
cd ~/develop/workspace/invest-support-web
git add backend/app/schemas.py backend/app/attractiveness.py backend/tests/test_attractiveness_router.py
git commit -m "feat: expose LPPL bubble diagnosis detail in attractiveness endpoint"
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

- [ ] **Step 2: Hit the endpoint for each of the 4 markets**

```bash
curl -s "http://127.0.0.1:8000/api/attractiveness/S%26P500?period=2y" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['lppl'])"
curl -s "http://127.0.0.1:8000/api/attractiveness/NASDAQ?period=2y" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['lppl'])"
curl -s "http://127.0.0.1:8000/api/attractiveness/KOSPI?period=2y" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['lppl'])"
curl -s "http://127.0.0.1:8000/api/attractiveness/KOSDAQ?period=2y" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['lppl'])"
```

Expected: each prints a dict with real `dangerScore`/`status` values (0-100 / one of 정상·경계·위험). `tcDate`/`rSquared`/`fittedSeries` will be non-null/non-empty for at least the markets where a real LPPL pattern is currently detected — note in your report which markets did or didn't show a live pattern, since this determines whether Task 4's manual browser check can see a real fitted-curve overlay or only the "no pattern detected" path.

No commit for this task — it's a verification checkpoint.

---

### Task 3: `LPPLBubblePanel` component

**Files:**
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/components/LPPLBubblePanel.tsx`

**Interfaces:**
- Consumes: `AttractivenessResponse.lppl` (Task 1), `AttractivenessResponse.priceSeries` (pre-existing)
- Produces: `<LPPLBubblePanel marketName={...} priceSeries={...} lppl={...} />`. Task 4 renders one instance of it.

- [ ] **Step 1: Add the `LPPLInfo` type**

```ts
// frontend/src/api/types.ts — insert directly above `export interface AttractivenessResponse {`
export interface LPPLInfo {
  dangerScore: number
  status: string
  tcDate: string | null
  rSquared: number | null
  fittedSeries: PricePoint[]
}
```

Then add one field to the existing `AttractivenessResponse` interface (after `macro: MacroIndicators`, do not reorder or touch any other field):

```ts
// frontend/src/api/types.ts — add this line inside interface AttractivenessResponse
  lppl: LPPLInfo
```

- [ ] **Step 2: Implement `LPPLBubblePanel`**

```tsx
// frontend/src/components/LPPLBubblePanel.tsx
import { useState } from "react"
import Plot from "react-plotly.js"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { LPPLInfo, PricePoint } from "@/api/types"

interface LPPLBubblePanelProps {
  marketName: string
  priceSeries: PricePoint[]
  lppl: LPPLInfo
}

export function LPPLBubblePanel({ marketName, priceSeries, lppl }: LPPLBubblePanelProps) {
  const [showGuide, setShowGuide] = useState(false)
  const hasFit = lppl.fittedSeries.length > 0

  const priceValues = priceSeries.map((p) => p.value)
  const yRange = hasFit
    ? [Math.min(...priceValues) * 0.8, Math.max(...priceValues) * 1.2]
    : undefined

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-medium">📊 {marketName} LPPL 버블 진단</h2>

      <Button variant="outline" size="sm" onClick={() => setShowGuide((v) => !v)}>
        📖 LPPL 분석 모델 상세 가이드 {showGuide ? "숨기기" : "보기"}
      </Button>
      {showGuide && (
        <div className="space-y-2 rounded-md border p-4 text-sm text-muted-foreground">
          <p>
            <strong>1. 로그 주기적 전력 법칙(LPPL) 모델이란?</strong> 자산 가격이 단순히
            상승하는 것을 넘어 '초지수적(Super-exponential)'으로 가속화될 때 발생하는 특이
            패턴을 분석합니다. 투자자들의 모방 행동(Herd Behavior)이 극에 달할 때 나타나는
            '미세한 진동'과 '상승 가속'을 수학적으로 포착합니다.
          </p>
          <p>
            <strong>2. 핵심 파라미터 해석</strong> — 위험 점수(Danger Score)는 B &lt;
            0(가속), 0.1 &lt; m &lt; 0.9(성장 구조), 6 &lt; ω &lt; 13(진동 패턴), R² &gt;
            0.8(신뢰도) 등 4대 조건을 합산합니다. 70점 이상은 강력한 버블 신호입니다. 예상
            임계점(Tc)은 가격 가속이 수학적으로 한계에 도달하는 시점입니다 — 반드시 폭락을
            의미하진 않으나, 이 시점 전후로 '추세 반전' 확률이 극대화됩니다. 결정계수(R²)는
            실제 가격이 모델과 얼마나 일치하는지 나타내며, 0.8 이상일 때 신뢰도가 매우
            높습니다.
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">위험 점수</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold">{lppl.dangerScore.toFixed(1)} / 100</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">위험 등급</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold">{lppl.status}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">예상 임계점(Tc)</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold">{lppl.tcDate ?? "N/A"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">모델 신뢰도(R²)</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold">
              {lppl.rSquared !== null ? lppl.rSquared.toFixed(4) : "N/A"}
            </p>
          </CardContent>
        </Card>
      </div>

      {lppl.status !== "정상" && lppl.tcDate && (
        <div className="rounded-md border border-yellow-500/50 bg-yellow-500/10 p-3 text-sm">
          주의: {marketName} 시장에서 버블 형성 징후가 감지되었습니다. Tc({lppl.tcDate}) 전후
          변동성에 유의하세요.
        </div>
      )}

      {!hasFit && (
        <p className="text-sm text-muted-foreground">
          현재 시장에서는 유의미한 버블 패턴(LPPL)이 감지되지 않았습니다. 추세가 안정적이거나
          신호가 약한 상태입니다.
        </p>
      )}

      <Plot
        data={[
          {
            type: "scatter",
            mode: "lines",
            name: "실제 가격",
            x: priceSeries.map((p) => p.date),
            y: priceSeries.map((p) => p.value),
            line: { color: "#3273dc" },
          },
          {
            type: "scatter",
            mode: "lines",
            name: "LPPL 예측",
            x: lppl.fittedSeries.map((p) => p.date),
            y: lppl.fittedSeries.map((p) => p.value),
            line: { color: "#ff8c00", dash: "dot" },
          },
        ]}
        layout={{
          height: 400,
          margin: { l: 10, r: 10, t: 20, b: 30 },
          xaxis: { automargin: true },
          yaxis: { automargin: true, range: yRange },
          shapes:
            hasFit && lppl.tcDate
              ? [
                  {
                    type: "line",
                    x0: lppl.tcDate,
                    x1: lppl.tcDate,
                    yref: "paper",
                    y0: 0,
                    y1: 1,
                    line: { color: "red", dash: "dash", width: 1 },
                  },
                ]
              : [],
        }}
        style={{ width: "100%" }}
        useResizeHandler
      />
    </div>
  )
}
```

Note: the "LPPL 예측" trace is always present in `data`, but its `x`/`y` arrays are empty when `lppl.fittedSeries` is `[]` (no valid fit) — Plotly renders an empty trace as a no-op, so this is simpler and avoids conditional-array-of-mixed-trace-shapes TypeScript friction. Same reasoning applies to `shapes`, which IS conditional (an empty `[]` vs a single-element array) — this compiles cleanly because `shapes` values are plain object literals, not a union with the `data` trace shape (confirmed against this codebase's existing identical `shapes: [{type: "line", ...}]` pattern in `YieldCharts.tsx`, which already compiles cleanly with no `as const`).

- [ ] **Step 3: Verify it compiles**

```bash
cd ~/develop/workspace/invest-support-web/frontend
npx tsc --noEmit
```

Expected: no type errors.

- [ ] **Step 4: Commit**

```bash
cd ~/develop/workspace/invest-support-web
git add frontend/src/api/types.ts frontend/src/components/LPPLBubblePanel.tsx
git commit -m "feat: add LPPLBubblePanel component"
```

---

### Task 4: Wire `LPPLBubblePanel` into `AttractivenessPage` + fix pre-existing price-chart clipping

**Files:**
- Modify: `frontend/src/pages/AttractivenessPage.tsx`

**Interfaces:**
- Consumes: `LPPLBubblePanel` (Task 3), `data.lppl` / `data.priceSeries` / `data.marketName` (Task 1, already flow through `getAttractiveness`'s existing return type since `AttractivenessResponse` was extended in Task 3 Step 1)

- [ ] **Step 1: Import the component**

```tsx
// frontend/src/pages/AttractivenessPage.tsx — add this import alongside the other component imports
import { LPPLBubblePanel } from "@/components/LPPLBubblePanel"
```

- [ ] **Step 2: Render the panel below the price chart, and fix the price chart's missing xaxis automargin**

Find this existing block in `AttractivenessPage.tsx` (the price chart, currently missing `xaxis: {automargin: true}` — the same clipping bug already fixed elsewhere this session):

```tsx
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
              yaxis: { automargin: true },
            }}
            style={{ width: "100%" }}
            useResizeHandler
          />

          <YieldCharts yieldSpread={data.yieldSpread} yields={data.yields} />
```

Replace it with (adds `xaxis: {automargin: true}` and a bigger `margin.b`, then inserts `LPPLBubblePanel` directly after):

```tsx
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
              margin: { l: 20, r: 20, t: 30, b: 30 },
              xaxis: { automargin: true },
              yaxis: { automargin: true },
            }}
            style={{ width: "100%" }}
            useResizeHandler
          />

          <LPPLBubblePanel marketName={data.marketName} priceSeries={data.priceSeries} lppl={data.lppl} />

          <YieldCharts yieldSpread={data.yieldSpread} yields={data.yields} />
```

- [ ] **Step 3: Verify it compiles**

```bash
cd ~/develop/workspace/invest-support-web/frontend
npx tsc --noEmit
```

Expected: no type errors.

- [ ] **Step 4: Manual browser verification**

```bash
# terminal 1
cd ~/develop/workspace/invest-support-web/backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000

# terminal 2
cd ~/develop/workspace/invest-support-web/frontend && npm run dev -- --port 5173
```

Open `http://localhost:5173`, click into the "시장 지수 분석" tab. Confirm: the LPPL panel renders below the price chart with the 4 metric cards populated, the guide button toggles the explanation text open/closed, the chart renders with no x/y-axis label clipping, and — for whichever market Task 2 found a live LPPL pattern in — the orange dashed prediction line and red dashed Tc vertical line are visible on the chart and the warning banner appears (if `status !== "정상"`). For a market with no live pattern, confirm the "유의미한 버블 패턴이 감지되지 않았습니다" message shows instead and the chart still renders the plain price line without a broken/empty second trace visible. Stop both servers.

- [ ] **Step 5: Commit**

```bash
cd ~/develop/workspace/invest-support-web
git add frontend/src/pages/AttractivenessPage.tsx
git commit -m "feat: render LPPLBubblePanel on the attractiveness page"
```

---

### Task 5: Full end-to-end verification

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

For S&P500, NASDAQ, KOSPI, and KOSDAQ (via the market selector), confirm the LPPL panel renders without errors for each — either the full bubble-diagnosis path or the no-pattern-detected path, both are acceptable outcomes depending on real current market data.

- [ ] **Step 3: Verify no regression on other pages**

Confirm the screener, heatmap, and realtime-monitor pages still work exactly as before (this task only touched `attractiveness.py`/`AttractivenessPage.tsx`-adjacent files, but a live check is cheap insurance).

- [ ] **Step 4: Check browser console**

Confirm no new console errors appear on the attractiveness page across all 4 markets and both period extremes (`1y` and `5y`).

No commit for this task. If all steps pass, this feature is complete.

---

## Self-Review Notes

- **Spec coverage:** API contract (Task 1), guide disclosure/metric cards/warning banner/chart with fitted overlay + Tc vline + y-range clamp (Task 3), wiring + placement below the price chart (Task 4), the bonus xaxis-automargin fix on the existing price chart (Task 4) — all covered. The explicitly-out-of-scope items (per-stock LPPL popup, AI report, `details` sub-score breakdown) are not implemented here, matching the spec.
- **Type consistency:** `LPPLInfo` field names (`dangerScore`/`status`/`tcDate`/`rSquared`/`fittedSeries`) are identical camelCase across `backend/app/schemas.py`, `frontend/src/api/types.ts`, and every usage site in `LPPLBubblePanel.tsx`.
- **No placeholders:** every step has literal file contents, literal test assertions with concrete expected values, or literal commands with expected output.
