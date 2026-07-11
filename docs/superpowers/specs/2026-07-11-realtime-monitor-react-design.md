# 실시간 마켓 모니터 React 전환 — 설계 문서

## 배경 및 목적

`invest-support-web` 프로젝트의 네 번째 기능 전환이다. 퀀트 스크리너(MVP), 마켓 히트맵, 시장 지수 및 매력도 분석에 이어, 원본 Streamlit 앱의 **실시간 마켓 모니터**(원본 `app.py`의 `🚀 실시간 마켓 모니터` 메뉴)를 React로 옮긴다.

이 기능은 앞선 세 기능과 성격이 다르다 — 대부분 TradingView 위젯(외부 스크립트 임베딩)을 React에 안전하게 통합하는 프론트엔드 작업이고, 백엔드는 국채수익률(5분봉)용 얇은 엔드포인트 하나만 필요하다.

## 범위

- **TradingView 위젯 9개**: 원본과 동일한 구성 — 지수선물 3개(나스닥100/S&P500/다우30), 매크로&공포지수 중 VIX/WTI유가/국제금 3개, 외환·원자재 3개(원달러환율/달러인덱스/비트코인). 레이아웃도 원본과 동일한 3섹션 구조.
- **국채수익률 미니차트 3개**: US30Y/US10Y/US5Y, 5분봉(Yahoo Finance 경유, TradingView 위젯이 지원하지 않는 심볼의 대체). 5분마다 프론트에서 자동 재조회.
- 종목 상세 팝업의 TradingView 임베딩(원본의 `show_stock_details` 다이얼로그)은 이번 범위 밖 — 그건 스크리너 결과 클릭 시 뜨는 별도 기능이며, 원본 마이그레이션 스펙에서 이미 LPPL/AI리포트 팝업과 함께 제외된 영역이다.

## 아키텍처

```
backend/app/
├── schemas.py           # 추가: YieldChartResponse
└── routers/
    └── realtime.py         # 신규: GET /api/realtime/yield/{name}

frontend/src/
├── api/realtime.ts       # 신규: getYieldChart(name)
├── components/
│   ├── TradingViewWidget.tsx  # 신규: tv.js 스크립트 1회 로드 + 위젯 인스턴스 생성/정리
│   └── YieldMiniChart.tsx     # 신규: 5분마다 폴링하는 국채 수익률 미니차트
└── pages/RealtimeMonitorPage.tsx  # 신규: 3섹션 레이아웃 조립
```

`get_market_history`가 인트라데이(분봉) 데이터를 이미 1시간 주기로 디스크 캐싱하고 있으므로(`modules/data_loader.py` 기존 로직, 수정 없음), 이 기능은 새로운 앱 레벨 `MarketCache` 캐싱을 추가하지 않는다 — 얇은 엔드포인트가 매 요청마다 `loader.get_market_history`를 직접 호출해도, 디스크 캐시가 실제 재다운로드를 막아준다.

## 백엔드 상세

```python
class YieldChartResponse(BaseModel):
    current: float
    changePct: float
    series: list[PricePoint]   # 시장지수분석 기능(2026-07-11-market-attractiveness-react-design.md)의 PricePoint 스키마 재사용
```

`GET /api/realtime/yield/{name}` (`name`: `US30Y`/`US10Y`/`US5Y`, Literal 타입) — `loader.get_market_history(name, period="1d", interval="5m")` 호출 → 데이터 없으면 `503`, 있으면 현재값/등락률/시계열 반환.

## 프론트엔드 상세

**`TradingViewWidget.tsx`**: `tv.js` 스크립트를 모듈 레벨 싱글턴 프로미스(`loadTradingViewScript()`)로 페이지당 한 번만 로드하고, 각 위젯 인스턴스는 이 프로미스를 기다린 후 자신의 고유 컨테이너 DOM에 `new TradingView.widget({...})`를 생성한다. 언마운트 시 TradingView 위젯 자체의 공식 destroy API가 없으므로, 컨테이너 DOM을 제거하는 것으로 정리한다. Props: `symbol: string`, `height?: number`, `interval?: string` (기본 "5").

**`YieldMiniChart.tsx`**: 마켓 히트맵/매력도 분석의 미니차트와 동일한 패턴 — `getYieldChart(name)`을 최초 로드 + 5분마다 `setInterval` 폴링(`ignore` 플래그로 stale-fetch 방지, 마켓 히트맵과 동일 패턴).

**`RealtimeMonitorPage.tsx`**: 원본과 동일한 3섹션 그리드:
1. 주요 지수 선물 3개 (`TradingViewWidget`, height 450): 나스닥100(`CAPITALCOM:US100`), S&P500(`CAPITALCOM:US500`), 다우30(`CAPITALCOM:US30`)
2. 실시간 매크로 & 공포 지수 (height 400): 국채 30Y/10Y/5Y(`YieldMiniChart`) 3개 + VIX(`CAPITALCOM:VIX`)/WTI유가(`CAPITALCOM:OIL_CRUDE`)/국제금(`CAPITALCOM:GOLD`) 3개
3. 외환 및 핵심 지표 3개 (height 400): 원달러(`FX_IDC:USDKRW`), 달러인덱스(`CAPITALCOM:DXY`), 비트코인(`BINANCE:BTCUSDT`)

## 에러 핸들링

| 상황 | 처리 |
|---|---|
| TradingView 스크립트 로드 실패(네트워크 차단 등) | 위젯 컨테이너는 비어있게 유지, 별도 에러 배너 없음 (원본도 위젯 자체 실패 처리 로직 없음 — 동일 수준으로 범위 최소화) |
| 국채수익률(5분봉) 조회 실패 | `503` + 해당 미니차트만 "데이터를 가져올 수 없습니다" 표시, 나머지 위젯은 정상 렌더링 |
| 5분 폴링 중 네트워크 순단 | 기존 데이터 유지, 에러로 화면 덮지 않고 조용히 다음 주기 재시도 (마켓 히트맵과 동일 패턴) |

## 테스트

- **백엔드**: `routers/realtime.py`는 단순 래퍼이므로 정상/503 케이스만 라우터 레벨 테스트.
- **프론트엔드**: 자동화 테스트 강제 안 함. 브라우저 실동작 검증 — TradingView 위젯 9개의 스크립트 로드 성공 및 컨테이너 존재 확인(실제 위젯 내부 iframe 렌더링까지는 헤드리스 환경에서 확인이 제한적일 수 있음, 스크립트 로드+컨테이너 마운트 확인으로 충분), 국채 미니차트 3개가 실제 5분봉 데이터로 렌더링되는지 확인.

## 향후 확장 (이번 범위 밖)

- 종목 상세 팝업의 개별 TradingView 임베딩 (LPPL/AI리포트 팝업과 함께 별도 스펙)
