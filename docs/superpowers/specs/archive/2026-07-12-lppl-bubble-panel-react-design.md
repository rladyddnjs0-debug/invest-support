# LPPL Bubble Panel React Migration — Design Spec

## Goal

Add the market-index-level LPPL ("Log-Periodic Power Law") bubble diagnosis panel to `invest-support-web`'s market attractiveness page (시장 지수 분석). This is one of two LPPL surfaces in the original Streamlit app; the other (per-stock LPPL popup on the screener page) is explicitly out of scope for this spec — it needs a new per-ticker detail-popup UI pattern that doesn't exist in `invest-support-web` yet, and was deferred by the user to a separate future feature.

## Background: what's already computed

`backend/app/attractiveness.py`'s `get_market_attractiveness` already calls `engine.run_lppl_fit(prices)` — this call already exists today, solely to feed `danger_score` into `calculate_target_weight` for the "권장 주식 투자 비중" gauge. The rest of `run_lppl_fit`'s return value is discarded. This spec adds no new expensive computation: it extracts more fields from the same already-computed result and adds them to the existing response.

`run_lppl_fit`'s full return shape (`modules/models.py`):
```python
{
    'params': {...},                      # LPPL curve fit parameters
    'fitted': np.ndarray,                 # predicted price curve, daily, from data.index[0] through 30 days past the last actual price point
    'tc_date': pd.Timestamp,              # predicted critical-point date
    'confidence_score': float,            # danger_score / 100
    'danger_score': float,                # 0-100
    'is_bubble': bool,                    # danger_score >= config.bubble_threshold (70)
    'details': {...},                     # sub-score breakdown, not surfaced in this UI
    'r_squared': float,
}
```
If no valid LPPL window pattern was found, it returns a smaller dict with only `danger_score`, `is_bubble`, `details`, `regime_msg` — no `fitted`/`tc_date`/`r_squared`.

Thresholds (`engine.config.bubble_threshold` = 70.0, `engine.config.warning_threshold` = 40.0, from `modules/config.py`'s `settings.lppl`) drive a 3-tier status: 정상 (< 40) / 경계 (40-69) / 위험 (≥ 70). This mirrors the original Streamlit app's `l_status` logic (`app.py` lines ~476-484).

## API contract

Extend `GET /api/attractiveness/{marketName}?period=...`'s existing response with one new field:

```ts
interface LPPLInfo {
  dangerScore: number        // 0-100
  status: string             // "정상" | "경계" | "위험"
  tcDate: string | null       // "YYYY-MM-DD"; null if no valid LPPL fit
  rSquared: number | null     // null if no valid LPPL fit
  fittedSeries: PricePoint[]  // [] if no valid LPPL fit
}

interface AttractivenessResponse {
  // ...existing fields unchanged...
  lppl: LPPLInfo
}
```

- `fittedSeries` dates are generated server-side the same way the original Streamlit code did: `pd.date_range(start=prices.index[0], periods=len(fitted), freq='D')` — calendar days (not trading days), zipped with the `fitted` values into `PricePoint { date, value }`.
- Status is computed server-side (`dangerScore >= bubble_threshold` → "위험", `>= warning_threshold` → "경계", else "정상") — consistent with this project's existing pattern of returning Korean display strings directly in response bodies (e.g. `regime`, `riskLevel`, `action` already do this; only *query params* use ASCII slugs per the screener regime convention).
- No new cache entry needed — this rides on the existing `attractiveness:{market}:{period}` day-scoped cache key, since it's derived from data already fetched and computed within that same cached call.
- Backward compatible: existing consumers of `AttractivenessResponse` are unaffected by the added field.

## Frontend

### New component: `LPPLBubblePanel.tsx`

Props:
```ts
interface LPPLBubblePanelProps {
  marketName: string
  priceSeries: PricePoint[]
  lppl: LPPLInfo
}
```

Layout (placed in `AttractivenessPage.tsx` directly below the existing "{market} 가격 추이" price chart, above `YieldCharts` — matching the original Streamlit app's section ordering):

1. **Section heading**: `📊 {marketName} LPPL 버블 진단`
2. **Guide disclosure**: a `Button` toggling a `useState` boolean to show/hide an explanatory text block (collapsed by default, matching the original's `expanded=False`). No new shadcn primitive needed — plain conditional render. Content is a plain-text (non-LaTeX) description of: what LPPL detects (super-exponential price acceleration / herd-behavior oscillation), what the danger score's 4 sub-conditions mean (B<0, 0.1<m<0.9, 6<ω<13, R²>0.8), what Tc means, what R² means.
3. **4 metric cards** (reuse `FactorScores.tsx`'s grid-card visual pattern): 위험 점수 (`dangerScore.toFixed(1)} / 100`), 위험 등급 (`status`), 예상 임계점 (`tcDate` formatted, or "N/A" if null), 모델 신뢰도 R² (`rSquared?.toFixed(4)` or "N/A" if null).
4. **Warning banner**: shown when `status !== "정상" && tcDate !== null` — text: `"주의: {marketName} 시장에서 버블 형성 징후가 감지되었습니다. Tc({tcDate}) 전후 변동성에 유의하세요."` Styled with an amber/warning Tailwind treatment (not a shadcn Alert component — none exists yet; a simple styled `<div>` matching the existing `text-destructive`/muted-foreground text-color conventions used elsewhere in this codebase).
5. **Chart** (Plotly, `xaxis`/`yaxis` `automargin: true` from the start — this session hit the same clipping bug 3 separate times from omitting this):
   - Actual price line: `priceSeries`, color `#3273dc` (existing convention, matches the page's own price chart above it)
   - LPPL fitted/prediction line (only if `fittedSeries.length > 0`): dashed, `#ff8c00` (orange — original used cyan on a dark Plotly theme; this app's charts are light-themed, so orange gives clearer contrast against the blue actual-price line on a white background)
   - Vertical dashed red line at `tcDate` (Plotly `shapes`, only if `tcDate` is set)
   - Y-axis range clamped to `[min(priceSeries) * 0.8, max(priceSeries) * 1.2]` only when a fitted overlay is present (matches original's rationale: guards against the fitted curve's tail swinging far outside the actual price range and squashing the visible chart)
6. If `fittedSeries` is empty: skip the chart's fitted overlay and vline, and show an info line: `"현재 시장에서는 유의미한 버블 패턴(LPPL)이 감지되지 않았습니다. 추세가 안정적이거나 신호가 약한 상태입니다."` (matches original's else-branch copy)

### Bonus fix (same file, low-risk, user-approved)

`AttractivenessPage.tsx`'s existing price chart (the "{market} 가격 추이" one, currently missing `xaxis: {automargin: true}`) gets the same automargin fix applied in this same plan, since it's the same recurring clipping bug pattern already fixed elsewhere this session and we're already touching this exact file.

## Testing

- Backend: extend `test_attractiveness_router.py` with cases for (a) a valid LPPL fit (mock `run_lppl_fit` returning the full dict — assert `lppl.dangerScore`/`status`/`tcDate`/`rSquared`/`fittedSeries` all populated and correctly mapped) and (b) no valid fit (mock returning only `danger_score`/`is_bubble` — assert `tcDate`/`rSquared` are `null` and `fittedSeries` is `[]`), plus a case per status tier (정상/경계/위험) to verify the threshold math.
- Frontend: no automated tests (matches this project's established pattern — frontend features are manually/live verified via browser, not unit-tested, per the original React migration spec's approved approach). Manual verification: load the attractiveness page for a market currently showing a real LPPL pattern (if none currently trigger one, verify the "no pattern detected" info path renders correctly, and note in the plan that the developer should try other markets/periods to find a real triggered case if possible) and confirm the panel renders, the guide toggles, the warning banner appears/disappears correctly, and the chart's overlay + Tc vline render without axis clipping.

## Explicitly out of scope

- Per-stock/per-ticker LPPL popup (screener page) — separate future feature, needs a new stock-detail-popup UI pattern.
- AI investment report generation referencing LPPL — separately deferred feature.
- Exposing `details` (the 4 sub-score breakdown: regime/fit/stability/timing/consistency/macro) in the UI — not shown in this panel; available in the API's discarded-but-computed data if a future spec wants it, but the tooltip-style breakdown text from the original Streamlit `help=` parameter is not reproduced here to keep scope contained.
