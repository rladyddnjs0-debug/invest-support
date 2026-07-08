# 퀀트 스크리너 — 펀디멘털 가치평가 항목 재설계 설계 문서

## 배경

`QuantScreener.run_screening()`의 밸류 팩터(`score_value`)는 현재 PER·PBR 두 지표만 50/50으로 합산한다(`modules/models.py:549-552`). 두 지표 모두 "이익/자산 대비 주가"만 보기 때문에:

- 자본구조(부채 수준)가 크게 다른 기업 간 비교가 왜곡된다 — 부채로 이익을 늘린 기업이 PER상 저평가로 보일 수 있음.
- 배당이라는, 밸류 투자자가 실제로 중요하게 보는 주주환원 성과가 전혀 반영되지 않는다.

이번 작업은 PER/PBR에 **EV/EBITDA**(자본구조 보정)와 **배당수익률**(주주환원)을 더해 밸류 팩터를 확장한다.

## 데이터 제약

- **US** (`DataLoader.get_stock_fundamentals`, `modules/data_loader.py:210-264`): `yfinance`의 `info` 딕셔너리에 `enterpriseToEbitda`, `dividendYield`가 이미 존재한다 — 추가 API 호출 없이 바로 가져올 수 있다.
- **KR** (pykrx 경로, `modules/data_loader.py:135-166`): `df_krx = get_market_fundamental_by_ticker(...)`가 이미 `DIV`(배당수익률) 컬럼을 포함하지만, 현재 코드는 이를 읽지 않고 버린다 — 배당수익률은 신규 API 호출 없이 바로 확보 가능하다. 반면 EV/EBITDA는 기업가치(EV) 계산에 필요한 부채·현금 데이터를 pykrx가 제공하지 않아 이번 범위에서 KR에는 적용하지 않는다(섹터중립화가 US에만 적용된 것과 동일한 패턴 — [[project-invest-support-status]] Item B 참고). KR의 EV/EBITDA 확보는 향후 과제로 남긴다.

## 결정: 가용 지표 동적 균등분배

`score_value`를 "PER 50% + PBR 50%" 하드코딩에서, **그 시점에 데이터가 있는 밸류 지표를 자동으로 균등분배**하는 방식으로 바꾼다. 시장명을 코드에 하드코딩하지 않고, 컬럼 존재 여부로 US/KR을 자연스럽게 분기한다(기존 `'Momentum' in df_clean.columns` 폴백 패턴과 동일한 사상).

- **저평가일수록 좋은 지표**(`ascending=False`로 백분위): `PER`, `PBR`, (있으면) `EV_EBITDA`
- **높을수록 좋은 지표**(`ascending=True`로 백분위): `DividendYield`
- 가중치는 `100 / (전체 지표 개수)`로 균등 분배:
  - **US**: PER·PBR·EV_EBITDA·DividendYield → 각 25%
  - **KR**: PER·PBR·DividendYield → 각 33.3%(EV_EBITDA 컬럼 자체가 없음)
- 섹터중립화(`sector_neutral=True`)는 기존 `pct_rank` 헬퍼를 그대로 재사용하므로 신규 지표에도 자동 적용된다. 별도 작업 불필요.

### 결측/부실 데이터 처리

- `EV_EBITDA`: PER/PBR과 동일하게 취급한다. EBITDA 적자(음수) 또는 데이터 없음(0/NaN)인 경우, 기존 "적자 기업 페널티" 블록(`for col in ['PER', 'PBR']: ...`)의 대상 컬럼에 `EV_EBITDA`를 추가해 해당 종목이 그 지표에서 최하위(`max_val + 100`)로 떨어지게 한다.
- `DividendYield`: 페널티 로직 대상이 **아니다**. 무배당 기업의 0은 "데이터 없음"이 아니라 정당한 값이며, `ascending=True` 백분위 랭킹에서 자연스럽게 최하위 근처로 랭크되면 충분하다.

## 라이브 검증이 필요한 리스크

과거 Item D(레짐 자동계산 `period=6mo→2y`)에서, "이 정도면 충분할 것"이라는 가정이 실제 다운스트림 가드 조건과 어긋나 유닛 테스트를 모두 통과하고도 기능이 무력화된 적이 있다([[feedback-dev-workflow]]). 이번 작업에도 유사한 리스크가 있어 구현 단계에서 반드시 실제 값으로 확인한다:

1. **`yfinance`의 `dividendYield` 단위**: 버전에 따라 소수(`0.015` = 1.5%)로 반환되던 것이 최근 버전에서는 이미 퍼센트 숫자(`1.5`)로 바뀌었다는 보고가 있다. 기존 코드는 `returnOnEquity`/`profitMargins`/`revenueGrowth`를 모두 "소수 → `*100`" 관례로 다루고 있으므로, 실제 설치된 `yfinance` 버전에서 몇 개 종목에 대해 라이브로 값을 찍어보고 `*100` 필요 여부를 확정한다.
2. **pykrx `DIV` 컬럼 단위**: PER/PBR/EPS/BPS와 마찬가지로 이미 절대 숫자(퍼센트 그대로, 예: `1.53`)일 것으로 예상되지만 라이브 호출로 확인한다.
3. 두 시장의 `DividendYield` 최종 단위(퍼센트 스케일)가 서로 일치해야 `pct_rank` 자체는 순위만 쓰므로 시장 간 비교엔 영향 없지만, 화면 표시(`{:.2f}%` 포맷)가 왜곡되지 않도록 확인한다.

## 호출부 변경

| 위치 | 변경 |
| :--- | :--- |
| `modules/data_loader.py` (US 정밀 분석 경로, `fetch_single_ticker` 내부) | `data` 딕셔너리에 `EV_EBITDA': info.get('enterpriseToEbitda', 0)`, `'DividendYield': ...` 추가. `is_large_batch` 캐시 재사용 경로에도 두 필드를 `old_row`에서 캐리오버 |
| `modules/data_loader.py` (KR pykrx 경로) | `fundamental_data.append({...})` 딕셔너리에 `'DividendYield': row.get('DIV', 0)` 추가. `EV_EBITDA` 키는 추가하지 않음(컬럼 자체 부재) |
| `modules/models.py::QuantScreener.run_screening` | `required_cols`에 `DividendYield` 추가. 적자 페널티 루프 대상에 `EV_EBITDA`(존재 시) 추가. `score_value` 계산을 동적 균등분배로 교체 |
| `app.py` (`requested_cols`, `format_dict`, `column_config`, 라인 1136/1142/1157 부근) | `DividendYield`, `EV_EBITDA` 컬럼 표시 추가. Value 팩터 설명 문구(라인 1125) 갱신 |
| `docs/quant_screener.md` | 밸류 팩터 절에 EV/EBITDA(US 전용)·배당수익률(US/KR 공통) 추가 설명 |

## 구현 스케치

```python
# modules/models.py::run_screening
required_cols = ['PER', 'PBR', 'ROE', 'Momentum', 'RevenueGrowth', 'ProfitMargin', 'DividendYield']
...

value_low_better = ['PER', 'PBR'] + (['EV_EBITDA'] if 'EV_EBITDA' in df_clean.columns else [])
for col in value_low_better:
    mask = (df_clean[col] <= 0)
    if mask.any():
        max_val = df_clean.loc[~mask, col].max() if not df_clean.loc[~mask, col].empty else 100
        df_clean.loc[mask, col] = max_val + 100

value_high_better = ['DividendYield']
n_value_factors = len(value_low_better) + len(value_high_better)
weight_each = 100 / n_value_factors

df_clean['score_value'] = sum(pct_rank(c, False) for c in value_low_better) * weight_each \
    + sum(pct_rank(c, True) for c in value_high_better) * weight_each
```

## 비목표 (Out of scope)

- KR 시장 EV/EBITDA 적용 (부채/현금 데이터 미확보 — 향후 과제)
- PSR, FCF Yield 등 추가 밸류 지표 (이번엔 EV/EBITDA·배당수익률 2개로 한정)
- `score_value` 가중치의 `config.yaml` 노출/튜닝 가능화 (균등분배 하드코딩으로 충분하다고 판단)
- `calculate_rebalancing`(포트폴리오 리밸런싱) 로직 변경 — `run_screening`의 밸류 스코어만 영향받고, 리밸런싱은 스크리닝 결과(상위 N종목)를 그대로 입력받으므로 자동 반영됨
- Item F(팩터 가중치 통계적 검증) — 여전히 Item A 미해결 상태로 보류 중, 이번 작업과 무관

## 테스트

`tests/test_models.py`에 `QuantScreener.run_screening` 테스트 추가:
- **US 형태**(4개 밸류 컬럼 모두 존재) 데이터셋: `score_value`가 4개 지표 균등가중(각 25%) 합으로 계산되는지 검증.
- **KR 형태**(`EV_EBITDA` 컬럼 없음) 데이터셋: `score_value`가 3개 지표 균등가중(각 33.3%) 합으로 계산되는지 검증 — 기존 회귀 테스트(있다면)가 여전히 통과하는지 확인.
- `EV_EBITDA <= 0` 또는 결측인 종목이 해당 지표에서 최하위로 떨어지는지 검증(PER/PBR 기존 테스트와 동일한 방식).
- `DividendYield == 0`(무배당) 종목이 페널티 없이 정상적으로 최하위 근처 백분위를 받는지 검증(다른 컬럼 대비 `max_val + 100` 같은 예외값이 섞이지 않는지 확인).

`tests/test_data_loader.py`(또는 해당 없으면 신규):
- `yfinance.Ticker.info`를 모킹하여 `enterpriseToEbitda`, `dividendYield` 필드가 결과 딕셔너리의 `EV_EBITDA`/`DividendYield`로 정확히 매핑되는지 검증.
- `pykrx` 응답을 모킹하여 `DIV` 컬럼이 `DividendYield`로 매핑되는지, `EV_EBITDA` 키가 KR 결과에는 아예 존재하지 않는지 검증.

**구현 단계에서 반드시 수행**: 위 "라이브 검증이 필요한 리스크" 절의 실제 API 호출 확인 — 유닛 테스트만으로는 단위 변환 버그를 잡을 수 없었던 과거 사례([[project-invest-support-status]])를 반복하지 않기 위함.
