# 마켓 히트맵 (Finviz 스타일) — 설계 문서

## 배경 및 목적

Finviz의 시장 히트맵처럼, S&P 500 전 종목을 섹터별로 묶어 시가총액 크기와 당일 등락률 색상으로 한눈에 보여주는 신규 메뉴를 추가한다. 프로젝트의 최초 목적이 이 히트맵이었으며, 지금까지 만든 시장 지수 분석/스크리너/밸류에이션 기능과 병행하여 새 사이드바 메뉴로 제공한다.

## 범위 (v1)

- **시장**: US (S&P 500)만. KR(KOSPI200)은 이번 범위에서 제외.
- **색상 지표**: 당일 등락률(%)만. 기간 선택 토글(1주/1개월/YTD 등)은 이번 범위에서 제외.
- **인터랙션**: 타일 클릭 등 인터랙션 없음. 순수 시각화만 (기존 종목 상세 팝업 연동 없음).
- **갱신 주기**: 당일 등락률은 자동 짧은 캐시(30분)로 갱신. 별도 새로고침 버튼 없음.

향후 KR 지원, 기간 토글, 타일 클릭 연동은 별도 스펙으로 확장 가능하나 이번 구현에는 포함하지 않는다.

## 재사용 vs 신규

기존 `종목 스크리너` 페이지(`app.py`)에 이미 Finviz와 거의 동일한 구조의 `px.treemap`이 있다 (Market → Sector → 종목, 크기=시가총액, 색상=퀀트 종합점수). 이 패턴을 재사용하되 색상 지표만 당일 등락률로 교체한다.

`DataLoader.get_stock_fundamentals()`가 반환하는 필드 중:
- **재사용**: `Name`, `Sector`, `MarketCap` — 순수 기업정보/펀더멘털 값이며 7일 파일 캐시로 충분 (박스 크기는 하루이틀 오래돼도 비율이 거의 안 바뀜)
- **재사용 안 함**: `Price`, `Momentum` — `Momentum`은 1년(미국)/6개월(한국) 수익률이라 "당일" 등락률과 무관하고, `Price`도 최대 7일까지 오래될 수 있어 당일 색상 지표로 부적합

따라서 당일 등락률만을 위한 신규 경량 함수를 별도로 추가한다.

## 아키텍처 / 데이터 흐름

1. `loader.get_sp500_tickers()` — 기존 함수 재사용 (위키 스크래핑 + 폴백)
2. `loader.get_stock_fundamentals(tickers, market_name="us")` — 기존 스크리너와 **동일한 파일 캐시** 재사용 (7일 만료). `Sector`, `MarketCap`, `Name` 획득.
3. **[신규]** `DataLoader.get_daily_changes(tickers) -> dict[str, float]`
   - `yf.download(tickers, period="2d", interval="1d", group_by='ticker')` 배치 1회 호출
   - 각 티커의 최근 2개 종가로 `(마지막 종가 / 그 전날 종가 - 1) * 100` 계산
   - 데이터가 없는 티커는 결과 dict에서 조용히 제외 (예외 발생 없이)
   - 배치 호출 자체가 실패하면 빈 dict `{}` 반환 (개별 재시도/백오프는 두지 않음 — 배치 1회 호출이라 리스크가 낮고, 실패 시 상위에서 "0%로 표시" 폴백으로 충분)
4. **[신규]** app.py의 `get_cached_daily_changes(tickers)` — `@st.cache_data(ttl=1800)`로 감싼 얇은 래퍼. 기존 `get_cached_historical_per`와 동일한 패턴. 30분 이내 재호출은 캐시 반환.
5. 2번과 4번 결과를 `Ticker` 기준 merge 후 데이터 정리:
   - `Sector`가 결측/빈 문자열이면 `'Unknown Sector'`로 대체 (기존 스크리너 트리맵과 동일한 처리)
   - `DisplayName = Name + " (" + Ticker + ")"` (기존 스크리너 트리맵과 동일한 구성)
   - `MarketCap`을 숫자로 강제 변환 후 0/결측 행 제외
6. `px.treemap`으로 렌더링:
   - `path=[px.Constant("S&P 500"), 'Sector', 'DisplayName']`
   - `values='MarketCap'`
   - `color='DayChange'`, `color_continuous_scale='RdYlGn'`, `color_continuous_midpoint=0`
   - `range_color=[-max_abs_change, max_abs_change]`로 0 중심 대칭 보장

## 신규 메뉴

- 사이드바에 `🗺️ 마켓 히트맵` 버튼을 `🔍 종목 스크리너` 바로 다음에 추가 (다른 메뉴 버튼들과 동일한 `st.session_state.menu` 토글 패턴, 메뉴 전환 시 `active_ticker = None` 초기화도 동일하게 적용)
- 페이지 타이틀: "🗺️ 마켓 히트맵 (S&P 500)"
- 설명 문구: "섹터별 시가총액 비중과 당일 등락률을 한눈에 보여주는 실시간 히트맵입니다."
- 트리맵은 전체 폭, `height=700`
- hover 시 `PER`, `ROE` 등 보조 정보 표시
- 하단 캡션: "펀더멘털(시총/섹터) 캐시는 최대 7일, 등락률은 최대 30분 주기로 갱신됩니다."

## 에러 처리

| 상황 | 처리 |
|---|---|
| `get_stock_fundamentals` 빈 결과 | `st.error`로 안내 후 렌더링 중단 (스크리너와 동일 패턴) |
| `get_daily_changes` 배치 호출 전체 실패 | 빈 dict → 전 종목 등락률 0%(중립색) 처리 + "당일 등락률 데이터를 가져오지 못했습니다" 안내 |
| 일부 종목만 등락률 조회 실패 | 해당 종목만 0% 처리 + "N개 종목은 당일 등락률을 가져오지 못해 0%로 표시됩니다" 캡션 |
| `MarketCap`이 0/결측 | 해당 행 필터링 후 트리맵에서 제외 (렌더링 오류 방지) |

## 테스트

- `tests/test_data_loader.py`에 `get_daily_changes` 유닛 테스트 추가:
  - `yf.download`를 모킹해 2일치 멀티인덱스 OHLC를 주고 정확한 등락률(%) 계산 검증
  - 데이터 없는 티커가 dict에서 조용히 빠지는지 확인 (KeyError 미발생)
  - 배치 다운로드 자체가 예외를 던지는 경우 빈 dict 반환 확인
- `modules/models.py`(LPPL/밸류에이션/퀀트스코어링) 변경 없음 — 기존 기능 회귀 없음
- 구현 후 로컬 Streamlit 서버 + 헤드리스 브라우저로 실제 렌더링 스크린샷 확인 (이번 세션에서 다른 기능들 검증 때 쓴 것과 동일한 방식)

## 비목표 (Out of scope)

- KR(KOSPI200) 히트맵
- 기간 선택 토글(1주/1개월/YTD)
- 타일 클릭 시 종목 상세 팝업 연동
- 당일 등락률 데이터에 대한 재시도/백오프 로직 (배치 1회 호출이라 우선순위 낮음)
