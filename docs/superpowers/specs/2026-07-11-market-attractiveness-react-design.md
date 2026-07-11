# 시장 지수 및 매력도 분석 React 전환 — 설계 문서

## 배경 및 목적

`invest-support-web` 프로젝트의 세 번째 기능 전환이다. 퀀트 스크리너(MVP)와 마켓 히트맵에 이어, 원본 Streamlit 앱의 **시장 지수 및 매력도 분석**(`docs/attractiveness_model.md` 참고, 원본 `app.py`의 `🌍 시장 지수 분석` 메뉴)을 React로 옮긴다.

## 범위

원본 페이지는 매력도/매크로 분석 외에 **LPPL 버블 진단 섹션**과 **AI 투자 리포트 버튼(Gemini)**을 한 화면에 포함하고 있으나, 이 둘은 원본 마이그레이션 스펙(`2026-07-11-react-frontend-migration-design.md`)에서 이미 별도 기능으로 분류되어 향후 과제로 남겨져 있다. 이번 전환에서는 이 둘을 제외한다:

**포함:**
- 시장 선택(S&P500/NASDAQ/KOSPI/KOSDAQ) + 기간 선택(1y/2y/3y/5y)
- 매력도 점수 게이지 + 권장 주식 투자 비중(목표비중) 게이지
- 6개 팩터 점수(추세/매크로/신용/유동성/Breadth/심리) 카드
- LPPL 오버레이 없는 순수 가격 라인 차트
- 국채 2Y/10Y/30Y 5년 차트 + 장단기 스프레드(10Y-2Y) 차트
- 글로벌 매크로 6종 미니차트(DXY/BEI Proxy/Gold/Oil/VIX/BTC)

**제외 (다음 단계로 이연):**
- LPPL 버블 진단 섹션 및 가격차트 LPPL 오버레이
- AI 투자 전략 리포트 버튼(Gemini 연동)
- 국채금리 "실시간(5분봉)" 토글 — 5년 장기추세만 제공. 실시간 5분봉은 별도 기능인 "실시간 마켓 모니터"와 성격이 겹치므로 이연.

**중요한 구현 뉘앙스**: "목표비중 게이지"는 원본에서 매력도 점수와 LPPL 위험점수를 결합해 산출한다(`calculate_target_weight(score, danger_score)`). LPPL 섹션 UI는 이번 범위에서 빠지지만, 목표비중 게이지 자체는 포함 범위이므로 **백엔드는 LPPL 피팅을 계속 내부적으로 수행하되 화면에는 그 세부 결과(Tc, R², 위험등급 등)를 노출하지 않는다** — 스크리너의 포지션사이징 엔드포인트가 이미 쓰는 것과 동일한 패턴(`get_ref_analysis`가 LPPL을 내부용으로만 계산).

## 아키텍처

```
backend/app/
├── attractiveness.py   # 신규: get_market_attractiveness(market_name, period, cache, loader, engine)
├── schemas.py          # 추가: AttractivenessResponse 및 하위 스키마
└── routers/
    └── attractiveness.py  # 신규: GET /api/attractiveness/{marketName}?period=...

frontend/src/
├── api/attractiveness.ts   # 신규: getAttractiveness(marketName, period)
├── components/
│   ├── ScoreGauges.tsx       # 매력도 게이지 + 목표비중 게이지 (Plotly indicator)
│   ├── FactorScores.tsx      # 6개 팩터 점수 카드
│   ├── YieldCharts.tsx       # 국채 2Y/10Y/30Y 차트 + 스프레드 차트
│   └── MacroMiniCharts.tsx   # DXY/BEI/Gold/Oil/VIX/BTC 6개 미니차트
└── pages/AttractivenessPage.tsx  # 시장/기간 선택 + 위 4개 컴포넌트 조립
```

`get_market_attractiveness`는 한 번의 호출로 다음을 모두 수집·계산한다: 기준 지수 가격(`DataLoader.get_market_history`), 장단기 금리차(`DataLoader.get_yield_spread`), 섹터 브레드스(`DataLoader.get_sector_data` → `AnalysisModel.calculate_breadth_score`), 유동성 4종(DXY/US10Y/Gold/BTC + VIX → `calculate_liquidity_score`), 신용스프레드(HYG/IEF), 5-Factor 매력도(`calculate_attractiveness`), LPPL(`run_lppl_fit`, 내부용), 목표비중(`calculate_target_weight`). 캐시 키 `attractiveness:{market_name}:{period}`로 날짜단위 캐싱(스크리너의 `screening.py`/`ref_analysis.py`와 동일한 double-checked locking 패턴).

## 백엔드 응답 스키마

```python
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
    status: str  # "정상" | "평탄화" | "역전"
    series: list[PricePoint]

class YieldsInfo(BaseModel):
    us2y: YieldMetric
    us10y: YieldMetric
    us30y: YieldMetric

class MacroIndicators(BaseModel):
    dxy: MacroMetric
    beiProxy: MacroMetric   # TIP/IEF 가격 비율 (기대 인플레이션 대용치)
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
    weights: MacroWeights   # 스크리너에서 이미 정의된 스키마 재사용 (필드 완전히 동일: trend/macro/sentiment/liquidity/breadth/credit)
    yieldSpread: YieldSpreadInfo
    yields: YieldsInfo
    macro: MacroIndicators
```

`GET /api/attractiveness/{marketName}?period=2y` — `marketName`: `S&P500`/`NASDAQ`/`KOSPI`/`KOSDAQ` (Literal 타입), `period`: `1y`/`2y`/`3y`/`5y` (Literal 타입).

## 프론트엔드 상세

- **`AttractivenessPage.tsx`**: 시장(4개)·기간(4개) 선택 UI + `getAttractiveness(marketName, period)` 호출. 시장/기간 변경 시 스크리너의 `ScreenerPage`와 동일하게 `ignore` 플래그로 stale-fetch 방지.
- **`ScoreGauges.tsx`**: Plotly `indicator`(`gauge+number`) 2개 — 매력도 점수(0~100, 빨강/회색/초록 3단 배경, height 200)와 목표비중(%, cyan 바, height 180). 원본과 동일한 임계값(0-40/40-75/75-100).
- **`FactorScores.tsx`**: 6개 팩터 점수 카드 그리드, 원본의 `help` 텍스트를 짧은 설명으로 그대로 이식.
- **가격 라인 차트**: 별도 컴포넌트 없이 `AttractivenessPage.tsx`에 인라인 Plotly `scatter` 트레이스로 — LPPL 오버레이 없는 단순 라인 하나뿐이라 별도 파일을 둘 만큼 복잡하지 않음.
- **`YieldCharts.tsx`**: 2Y/10Y/30Y 현재금리 숫자 3개 + 통합 라인차트(3색) + 스프레드 영역차트(0선 빨간 점선).
- **`MacroMiniCharts.tsx`**: DXY/BEI/Gold/Oil/VIX/BTC 6개, 2열 그리드, 각각 현재값+모멘텀%(1개월) + 미니 라인차트(height 180, 원본과 동일 색상: gold=금색, oil=orangered, vix=mediumpurple, btc=orange).

## 에러 핸들링

| 상황 | 처리 |
|---|---|
| 기준 지수 가격 데이터 조회 실패 | `503` + 프론트 에러 배너, 페이지 렌더링 중단 |
| 개별 매크로/국채 티커 조회 실패 (예: BTC, HYG) | 해당 지표만 `current:0, momPct:0, series:[]` 반환, 프론트는 그 위젯만 "데이터 없음" 표시, 나머지는 정상 렌더링 |
| 신용스프레드(HYG/IEF) 조회 실패 | `AnalysisModel.calculate_attractiveness`가 이미 내부적으로 `credit_score=50` 기본값 처리 (기존 로직 그대로 재사용, 별도 처리 불필요) |
| 시장/기간 변경 중 이전 요청 응답 도착 | `ignore` 플래그로 무시 |

## 테스트

- **백엔드**: `attractiveness.py`의 `get_market_attractiveness`는 스크리너의 `ref_analysis.py`/`screening.py`와 동일한 방식(mock 기반, 캐시 재사용 확인)으로 단위 테스트. 개별 티커 실패(예: BTC `None` 반환) 시 해당 지표만 기본값 처리되는지 별도 테스트. 라우터 레벨 정상/503 케이스 테스트.
- **프론트엔드**: 자동화 테스트 강제 안 함. 브라우저 실동작 검증(헤드리스 Playwright)으로 4개 시장 × 대표 기간 조합을 최소 1회씩 확인.

## 향후 확장 (이번 범위 밖)

- LPPL 버블 진단 섹션 (별도 스펙)
- AI 투자 전략 리포트 (별도 스펙)
- 국채금리 실시간(5분봉) 모드
