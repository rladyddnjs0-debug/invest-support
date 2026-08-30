# 퀀트 스크리너 — 12-1 모멘텀 통일 설계 문서

## 배경

`QuantScreener`가 사용하는 `Momentum` 팩터는 시장별로 산출 방식이 다르고, 둘 다 최근 1개월의 단기 반전(reversal) 효과에 그대로 노출되어 있다.

- **US** (`modules/data_loader.py`의 `get_stock_fundamentals`, batch 다운로드 구간): `yf.download(tickers, period="1y", ...)`로 받은 1년치 종가에서 `mom = (curr_price / start_price - 1) * 100` — **최근 12개월 총수익률**.
- **KR** (같은 함수, pykrx 분기): `krx_stock.get_market_price_change_by_ticker(six_months_ago, date_str)` — **최근 6개월 총수익률**.

학계에서 표준으로 쓰이는 모멘텀 정의는 "12-1 모멘텀"(과거 12개월 수익률에서 최근 1개월을 제외)이다. 최근 1개월을 제외하는 이유는 단기 주가는 평균회귀(mean-reversion) 경향이 있어, 이를 포함하면 모멘텀 팩터의 예측력이 오염되기 때문이다. 현재 US/KR 모두 이 표준을 따르지 않을 뿐 아니라 서로 다른 기준 기간을 쓰고 있어, 두 시장의 모멘텀 점수를 같은 스크리너 로직(`pct_rank`)으로 비교하는 것 자체가 일관성이 없다.

## 결정: 12-1 모멘텀으로 통일, 추가 API 호출 없이 구현

`(과거 12개월 시점 가격) → (과거 1개월 시점 가격)` 구간의 수익률을 US/KR 공통 정의로 사용한다.

### US

이미 `period="1y"`로 일봉 시계열 전체를 배치 다운로드하고 있으므로, 추가 다운로드 없이 시계열 내에서 두 시점의 가격을 위치 기반(positional) 인덱싱으로 찾아 계산한다. 날짜가 아니라 행 위치를 쓰는 이유는 `yfinance`가 이미 주말/휴장일을 제외한 거래일만 반환하므로, "21 거래일 전"이 곧 "약 1개월 전"의 합리적인 근사이기 때문이다.

- `price_col`(종가 시리즈, `dropna()` 적용됨)의 마지막 값을 `t_now`, **끝에서 22번째 값**(`price_col.iloc[-22]`, 즉 최근 21거래일을 제외한 지점)을 `t_1mo`, **첫 번째 값**(`price_col.iloc[0]`, 배치 다운로드 구간의 시작점 ≈ 12개월 전)을 `t_12mo`로 삼는다.
- `mom = (price_col.iloc[-22] / price_col.iloc[0] - 1) * 100`.
- 시계열 길이가 22개 미만(신규 상장 등)이면 `t_1mo`를 구할 수 없으므로 기존처럼 `info.get('52WeekChange', 0) * 100`으로 폴백한다.

### KR

`krx_stock.get_market_price_change_by_ticker(start, end)`는 두 날짜 사이의 등락률을 반환하는 API이므로, 호출 구간의 날짜만 조정하면 된다.

- 기존: `start = target_date - 180일`, `end = target_date`.
- 변경: `start = target_date - 13개월(약 395일)`, `end = target_date - 1개월(약 30일)`.
- 이 구간에 데이터가 없는 신규 상장 종목은 기존과 동일하게 `Momentum: 0`으로 폴백한다(현재 코드의 `if pure_ticker in df_momentum.index else 0` 로직 그대로 유지).

### 캐시 재사용 경로(대량 배치의 `old_row` 폴백)

`fetch_single_ticker` 내 `is_large_batch and not force_download and old_row is not None` 분기는 가격/모멘텀을 이전 캐시에서 재사용한다. 이 경로는 이번 변경과 무관하게 그대로 유지한다 — 캐시된 `Momentum` 값도 다음 강제 갱신(`force_download`) 또는 캐시 만료 시 새 12-1 정의로 자연스럽게 교체된다.

## 비목표 (Out of scope)

- 모멘텀 팩터에 변동성 조정(리스크 조정 모멘텀) 적용 — 별도 향후 과제.
- 모멘텀 lookback 기간을 `config.yaml`에서 조정 가능하게 만드는 것 — 지금은 12-1을 하드코딩된 표준으로 삼고, 필요해지면 나중에 설정화한다(YAGNI).
- US의 `52WeekChange` 폴백 로직 자체를 12-1 기준으로 바꾸는 것 — 폴백은 드문 예외 상황(신규 상장)이므로 기존 근사치를 유지한다.

## 테스트

`tests/test_data_loader.py`에 다음 케이스를 추가한다:
- US: 합성 1년치 일봉 시계열(선형 또는 계단형 가격)을 만들어, 최근 1개월 구간의 급등/급락을 포함시킨 뒤 12-1 모멘텀이 이 구간을 제외한 값으로 계산되는지 검증(최근 12개월 총수익률로 계산했을 때와 다른 값이 나와야 함).
- US: 시계열 길이가 21영업일 미만인 경우 `52WeekChange` 폴백이 사용되는지 검증.
- KR: `krx_stock.get_market_price_change_by_ticker`를 모킹하여 호출 인자(`start`, `end` 날짜)가 각각 `target_date - 13개월`, `target_date - 1개월`인지 검증.
