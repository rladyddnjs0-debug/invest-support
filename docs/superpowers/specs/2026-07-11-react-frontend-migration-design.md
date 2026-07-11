# 퀀트 스크리너 React 전환 (MVP) — 설계 문서

## 배경 및 목적

현재 `invest-support`는 Streamlit 단일 앱으로 8개 기능(시장 매력도, LPPL 버블 진단, 퀀트 스크리너, 마켓 히트맵, 펀더멘털 밸류에이션, 실시간 모니터, AI 투자 리포트, 설정)을 제공한다. 이번 전환의 목적은 **학습/커리어** — React와 프론트엔드/백엔드 분리 아키텍처를 익히는 것이다.

전면 재작성이 아니라 **프론트엔드만 React로, 백엔드는 기존 Python 분석 엔진(`modules/`)을 FastAPI로 래핑**하는 방향으로 진행한다. 8개 기능을 한 번에 옮기지 않고, 가장 인터랙티브 UI 요소(테이블·차트·필터)가 풍부한 **퀀트 스크리너를 첫 MVP**로 전환한다.

## 범위 (MVP)

**포함:**
- 시장 선택(US S&P500 / KR KOSPI200) + 레짐 자동판정(수동 override 가능)
- 팩터 스코어링 랭킹 테이블 (Value/Quality/Growth/Momentum → FinalScore)
- 다차원 시각화: 섹터별 트리맵, 상위 3종목 레이더 차트, 종합점수 바 차트, 가치-효율성 산점도
- 실전 포지션 사이징 가이드 (리스크 패리티 + LPPL 위험 결합 비중/수량 계산)

**제외 (다음 단계로 이연):**
- 테이블 행 클릭 시 LPPL 버블 판단 팝업
- AI 투자 리포트 팝업
- 뉴스 요약
- 마켓 히트맵, 실시간 모니터, 펀더멘털 밸류에이션 등 나머지 7개 기능
- 실시간 데이터 수집 진행률 표시(progress bar) — REST 단발 요청/응답 구조와 맞지 않아 이연. 향후 SSE/WebSocket 도입 시 재검토.
- 배포(호스팅) — 로컬 개발 환경 완성 후 별도 단계에서 결정

## 저장소 및 기존 앱과의 관계

새 저장소 `~/develop/workspace/invest-support-web`을 생성한다. 기존 `invest-support`(Streamlit 앱)는 그대로 유지하고 계속 배포/운영한다. `modules/`(`data_loader.py`, `models.py`, `config.py`, `logger.py`)는 새 저장소로 **복사**하여 독립적으로 관리한다 — 심볼릭 링크나 패키지 공유는 하지 않으며, 두 앱이 각자 독립적으로 진화할 수 있게 한다.

`modules/ai_reporter.py`는 MVP 범위(스크리너)에 필요 없고 `streamlit`(`st.secrets`)에 의존하므로 이번에는 복사하지 않는다.

## 기술 스택

| 영역 | 선택 |
|---|---|
| 프론트엔드 언어 | TypeScript |
| 프론트엔드 빌드 | Vite + React |
| 스타일링 | Tailwind CSS + shadcn/ui |
| 차트 | Plotly.js (`react-plotly.js`) — 기존 Streamlit의 Plotly 설정(treemap/radar/scatter/bar) 재사용 가능 |
| 백엔드 | Python + FastAPI |
| 백엔드 분석 엔진 | 기존 `modules/data_loader.py`, `modules/models.py` (수정 없이 재사용) |

## 저장소 구조

```
invest-support-web/
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI 앱 진입점
│   │   ├── modules/               # invest-support/modules에서 복사 (data_loader, models, config, logger)
│   │   ├── routers/
│   │   │   └── screener.py        # 3개 엔드포인트
│   │   └── schemas.py             # Pydantic 응답 모델
│   ├── config.yaml                # invest-support/config.yaml 복사
│   ├── data/                      # 펀더멘털/시장히스토리 디스크 캐시 (기존과 동일한 파일 캐시 방식)
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── api/                   # fetch 래퍼
    │   ├── components/
    │   │   ├── ScreenerTable.tsx
    │   │   ├── SectorTreemap.tsx
    │   │   ├── FactorRadar.tsx
    │   │   ├── ScoreBarChart.tsx
    │   │   ├── ValueEfficiencyScatter.tsx
    │   │   └── PositionSizingPanel.tsx
    │   ├── pages/ScreenerPage.tsx
    │   └── App.tsx
    ├── tailwind.config.js
    └── package.json
```

## API 설계

### `GET /api/screener/{market}/regime`
`market`: `us` | `kr`. 기준지수(S&P500/KOSPI)로 `AnalysisModel.calculate_attractiveness` 호출해 자동 레짐 계산.

응답: `{ autoRegime: string | null, weights: { value, quality, growth, momentum } }`

`autoRegime`이 `null`이면 자동 계산 실패 — 프론트는 수동 레짐 선택 UI를 자동 활성화한다 (원본의 폴백 로직과 동일).

### `GET /api/screener/{market}?regime={regime}`
`DataLoader.get_stock_fundamentals` (디스크 캐시, 7일 TTL) → `QuantScreener.run_screening(sector_neutral=(market=="us"))`.

응답:
```json
{
  "regime": "Risk-on (안정 성장)",
  "weights": { "value": 0.15, "quality": 0.15, "growth": 0.4, "momentum": 0.3 },
  "sectorNeutral": true,
  "rows": [
    {
      "ticker": "AAPL", "name": "Apple Inc.", "sector": "Technology",
      "finalScore": 82.3, "per": 28.1, "pbr": 45.2, "roe": 147.9, "momentum": 12.4,
      "scoreValue": 40.1, "scoreQuality": 95.0, "scoreGrowth": 60.2, "scoreMomentum": 70.5,
      "marketCap": 3500000000000
    }
  ]
}
```

빈 결과(`rows: []`)는 정상 응답이며 에러가 아니다 — 프론트가 "데이터 없음" 상태로 처리한다.

### `POST /api/screener/{market}/position-sizing`
Body: `{ "regime": string, "totalCapital": number }`

내부적으로 인메모리 캐시에 있는 스크리닝 결과(top 10)를 재사용하거나(§데이터 수집 전략 참고), 없으면 재계산 후 `QuantScreener.calculate_stock_weights` 호출.

응답:
```json
{
  "totalTargetWeightPct": 65.0,
  "positions": [
    { "ticker": "AAPL", "name": "Apple Inc.", "recWeight": 12.5, "shares": 3, "stopLoss": 210.5, "targetPrice": 245.0, "dangerScore": 22 }
  ]
}
```

## 데이터 수집 & 캐싱 전략

REST API는 Streamlit의 `session_state`처럼 요청 간 상태를 자연히 공유하지 않으므로, 신경 쓰지 않으면 아래 두 종류의 중복이 생길 수 있다. 이를 막기 위한 3단 방어:

1. **기존 디스크 캐시 보존 (1차 방어선)**: `DataLoader.get_stock_fundamentals`(7일 TTL), `get_market_history`(1일 TTL)는 수정 없이 그대로 사용한다. API 라우터는 항상 `force_download=False`로 호출하며, 이 값을 임의로 켜지 않는다 — 사용자가 명시적으로 새로고침을 요청하는 경로에서만 `True`로 전달되도록 라우터에서 제어한다.

2. **요청 간 재계산 중복 제거 (인메모리 캐시)**: `regime` → `screener` → `position-sizing` 순서로 호출될 때, 레짐 엔드포인트가 이미 계산한 기준지수 어트랙티브니스+LPPL 피팅(20회 반복, 연산 비용 높음)과 screener 엔드포인트가 이미 산출한 스코어링 결과를 position-sizing이 다시 계산하지 않도록, FastAPI `app.state`에 `(market, date)` 키의 당일 TTL 인메모리 캐시를 두어 재사용한다. 캐시가 비어있으면(서버 재시작 직후 등) 조용히 재계산한다.

3. **동시 요청 경합 방지 (single-flight)**: 디스크 캐시가 콜드 스타트인 상태에서 같은 market에 대한 요청이 겹치면 `yfinance`/`pykrx`에 병렬 중복 다운로드가 나갈 수 있다. market별 `asyncio.Lock`으로 감싸서, 진행 중인 수집이 있으면 뒤따라온 요청은 그 결과를 기다렸다가 재사용한다.

## 에러 핸들링

| 상황 | 처리 |
|---|---|
| 데이터 수집 실패 (rate limit, 네트워크 오류) | `DataLoader`의 기존 재시도(최대 3회)+stale 캐시 폴백을 그대로 물려받음. 그래도 실패하면 `503` + `{ error: "market_data_unavailable" }` → 프론트는 재시도 안내 배너 표시 |
| 레짐 자동 계산 실패 | `autoRegime: null` → 프론트가 수동 선택 UI 자동 활성화 |
| 빈 펀더멘털 데이터 | `rows: []` (에러 아님) → 프론트는 "데이터 없음" 상태, 차트/포지션 사이징 섹션 미렌더링 |
| position-sizing 요청 시 인메모리 캐시 없음 | 자동으로 스크리닝 재수행 후 top 10 산출 (에러 대신 조용히 재계산) |

## 테스트

- **백엔드**: `tests/`의 기존 `modules/` 단위 테스트(`test_data_loader.py`, `test_models.py`)를 새 저장소로 함께 복사해 유지. 여기에 라우터 레벨 테스트 추가 — `TestClient`로 3개 엔드포인트의 정상/실패 케이스(빈 데이터, 레짐 계산 실패) 검증. 실제 `yfinance`/`pykrx` 호출은 mock 처리.
- **프론트엔드**: MVP 단계에서는 컴포넌트 단위 테스트를 필수로 강제하지 않는다 (학습 속도 우선). 각 컴포넌트 완성 시 브라우저에서 직접 동작 확인.

## 배포

프론트엔드는 Vercel, 백엔드는 Render/Fly.io 등을 후보로 고려하되, **이번 스펙에서는 확정하지 않는다.** 로컬 개발 환경(백엔드 `uvicorn --reload`, 프론트 `vite dev`)에서 MVP 완성도를 먼저 높이고, 배포 방식은 다음 단계에서 별도로 결정한다. (백엔드는 디스크 캐시 파일을 유지해야 하므로 persistent disk 지원 여부가 호스팅 선택의 핵심 제약이 될 것으로 예상된다.)

## 향후 확장 (이번 범위 밖)

- 나머지 7개 기능의 단계적 React 전환 (다음 스펙에서 개별 진행)
- 실시간 수집 진행률 (SSE/WebSocket)
- LPPL/AI 리포트 상세 팝업
