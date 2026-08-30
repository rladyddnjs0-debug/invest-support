# 마켓 히트맵 React 전환 — 설계 문서

## 배경 및 목적

`invest-support-web`(React+FastAPI) 프로젝트의 두 번째 기능 전환이다. 첫 번째(퀀트 스크리너, `2026-07-11-react-frontend-migration-design.md`)에 이어, 원본 Streamlit 앱의 8개 기능 중 **마켓 히트맵**(`docs/market_heatmap.md` 참고)을 React로 옮긴다. 남은 6개 기능(시장 매력도, LPPL, 밸류에이션, 실시간 모니터, AI 리포트, 설정)은 이번 범위 밖이며, 사용자가 세 기능(시장 지수분석/마켓 히트맵/실시간 마켓 모니터) 중 가장 가볍다고 판단한 이 기능을 먼저 진행한다.

## 범위

- **시장**: US(S&P 500)만. KR은 원본과 동일하게 이번에도 제외.
- **인터랙션**: 원본과 동일하게 타일 클릭 등 인터랙션 없음. 순수 시각화 + 마우스 오버 정보만.
- **자동 갱신**: 원본 Streamlit에는 없던 기능이지만, 이번 React 버전에서는 프론트엔드가 30분마다 자동으로 재조회한다(사용자 결정 — 원본은 폴링 없이 사용자 상호작용 시에만 갱신).
- **hover 정보**: 현재가(달러, 소수점 둘째자리) / 등락률 / 시가총액(사람이 읽기 쉬운 단위) / PER / ROE / (애프터마켓 시각에만) 애프터마켓 등락률.

## 아키텍처

```
backend/app/
├── cache.py          # 수정: get()/set()에 ttl_seconds 옵션 추가 (기존 날짜단위 로직 유지)
├── heatmap.py         # 신규: get_heatmap_fundamentals(), get_daily_changes_cached()
├── schemas.py         # 추가: HeatmapTile, HeatmapResponse
└── routers/
    └── heatmap.py      # 신규: GET /api/heatmap

frontend/src/
├── api/heatmap.ts      # 신규: getHeatmap() + 타입
├── components/MarketHeatmap.tsx   # 신규: SectorTreemap과 동일한 2단계 flat labels/parents 패턴 재사용
└── pages/HeatmapPage.tsx  # 신규: 최초 로드 + 30분 주기 폴링(ignore 플래그로 stale-fetch 방지)
```

## 백엔드 상세

### `cache.py`의 `ttl_seconds` 확장

`MarketCache.get(key, ttl_seconds=None, today=None)` / `set(key, value, today=None)`: `ttl_seconds`가 주어지면 저장 시각과의 경과초로 판단하고, 없으면 기존 날짜 단위(자정 기준) 로직을 그대로 쓴다. 내부 저장은 항상 `datetime`으로 통일하고, 날짜단위 비교 시에는 `.date()`로 변환해 비교한다 — 기존 스크리너의 `cache.get(key)` 호출부(`ttl_seconds` 생략)는 코드 변경 없이 그대로 동작해야 한다.

### `heatmap.py` 헬퍼 (스크리너의 `screening.py`/`ref_analysis.py`와 동일한 캐시 패턴)

- `get_heatmap_fundamentals(cache, loader)`: `loader.get_sp500_tickers()` + `loader.get_stock_fundamentals(tickers, market_name="us")`. 캐시 키 `heatmap_fundamentals:us`, 날짜단위(`ttl_seconds` 미지정). 스크리너가 이미 쓰는 `us_fundamentals.csv` 디스크 캐시(7일)를 그대로 재사용하므로, 같은 날 스크리너를 먼저 조회했다면 네트워크 재수집이 없다.
- `get_daily_changes_cached(cache, loader)`: `loader.get_daily_changes(tickers)`. 캐시 키 `daily_changes:us`, `ttl_seconds=1800`.
- 둘 다 기존 헬퍼와 동일하게 `cache.lock_for(key)`로 double-checked locking 적용.

### `GET /api/heatmap`

market 파라미터 없음 (US 전용이므로 경로에 넣지 않음). 두 헬퍼 결과를 `Ticker` 기준으로 병합한다.

```json
{
  "changesAvailable": true,
  "tiles": [
    {
      "ticker": "AAPL", "name": "Apple Inc.", "sector": "Technology",
      "marketCap": 3500000000000, "price": 123.45,
      "change": 4.84, "afterHoursChange": null,
      "per": 28.1, "roe": 147.9
    }
  ]
}
```

- `changesAvailable`: `get_daily_changes_cached`가 빈 dict를 반환하면 `false`, 전종목 `change: 0`.
- 개별 종목만 등락률 누락 시 그 종목만 `change: 0` (별도 플래그 없음 — 범위 최소화).
- `marketCap`이 결측이거나 0 이하인 종목은 `tiles`에서 제외.

## 프론트엔드 상세

### `MarketHeatmap.tsx`

`SectorTreemap`(Task 12, 스크리너)과 동일한 flat `labels`/`parents`/`values` 2단계 패턴(섹터 노드 `parent: ""`, `value: 0`, `branchvalues: "remainder"`, Plotly의 "multiple implied roots" 문제를 이미 해결한 방식 그대로 재사용)을 쓰되, 색상 로직만 다르다:

- **색상**: `change`를 0 중심 발산형(`RdYlGn`)으로. `marker.cmid: 0`으로 중심 고정. 섹터 노드 색상은 해당 섹터 종목들의 `change` 시총가중평균.
- **타일 텍스트**: 회사명 아래 `+4.84%`/`-1.39%` 형식.
- **Hover**: `formatMarketCap(n): "$4.58T"` 유틸 함수 신규 작성. 순서:
  ```
  Apple Inc. (AAPL)
  현재가: $123.45
  등락률: +4.84%
  시가총액: $3.50T
  PER: 28.1 / ROE: 147.9%
  (애프터마켓이면) 애프터마켓 등락률: +0.32%
  ```

### `HeatmapPage.tsx`

최초 로드 + `setInterval`로 30분마다 자동 재조회. Task 11에서 겪은 stale-fetch 문제를 처음부터 반영해 `ignore` 플래그로 클린업한다.

```tsx
useEffect(() => {
  let ignore = false
  const fetchHeatmap = () => {
    getHeatmap()
      .then((res) => { if (!ignore) setData(res) })
      .catch((err) => { if (!ignore) setError(err instanceof Error ? err.message : "알 수 없는 오류") })
  }
  fetchHeatmap()
  const interval = setInterval(fetchHeatmap, 30 * 60 * 1000)
  return () => { ignore = true; clearInterval(interval) }
}, [])
```

## 에러 핸들링

| 상황 | 처리 |
|---|---|
| 펀더멘털 조회 실패 | `503` + 프론트 에러 배너, 트리맵 미렌더링 |
| 당일 등락률 전체 조회 실패 | `200` + `changesAvailable: false`, 전종목 `change: 0`, 경고 배너("당일 등락률 데이터를 가져오지 못해 중립색으로 표시됩니다") + 트리맵은 계속 렌더링 |
| 개별 종목 등락률 누락 | 그 종목만 `change: 0`, 별도 안내 없음 |
| 시가총액 결측/0 이하 | 응답에서 제외 |
| 30분 폴링 중 네트워크 순단 | 기존 데이터 유지, 에러 배너로 화면을 덮지 않고 조용히 다음 주기 재시도 |

## 테스트

- **백엔드**: `test_cache.py`에 `ttl_seconds` 분기 테스트 추가(초단위 만료 확인 + 기존 날짜단위 테스트 유지). `heatmap.py`의 두 헬퍼는 `screening.py`/`ref_analysis.py`와 동일한 방식(mock 기반, 캐시 재사용/TTL 초과 재계산 확인)으로 단위 테스트. 라우터 레벨 정상/실패 케이스 테스트.
- **프론트엔드**: 자동화 테스트는 강제하지 않고 브라우저 실동작 검증(헤드리스 Playwright)으로 확인. 30분 폴링은 실제로 기다릴 수 없으므로 `setInterval` 로직은 코드 리뷰로, 최초 로드 동작만 라이브로 확인한다.

## 향후 확장 (이번 범위 밖)

- KR(KOSPI) 지원
- 기간 선택 토글(1주/1개월/YTD)
- 타일 클릭 시 종목 상세 팝업 연동
