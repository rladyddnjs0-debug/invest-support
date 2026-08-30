# 퀀트 스크리너 — 섹터 중립화 랭킹 설계 문서

## 배경

`QuantScreener.run_screening()`은 PER/PBR/ROE/영업이익률/매출성장률/모멘텀의 백분위 순위를 **전체 유니버스**(예: S&P 500 500개 전 종목) 기준으로 계산한다. 그러나 이 지표들은 업종별로 구조적 수준 차이가 크다(기술주는 PER이 구조적으로 높고, 금융주는 ROE가 구조적으로 높음). 전체 풀 기준 랭킹은 "업종 내 상대적으로 저평가/고퀄리티"가 아니라 "전체 시장에서 절대적으로 낮은 PER/높은 ROE"를 찾는 셈이라, 저PER·고ROE 섹터(금융·에너지 등)로 스크리닝 결과가 구조적으로 쏠릴 수 있다.

## 데이터 제약

- **US**: `DataLoader.get_stock_fundamentals()`가 `info.get('sector', 'N/A')`로 야후의 실제 업종 분류(Technology, Financial Services 등)를 제공한다 → 섹터 중립화가 의미 있게 작동한다.
- **KR**: 같은 함수가 `'Sector': 'KOSPI' if ... else 'KOSDAQ'`로 **상장 시장명**을 "Sector"로 채운다 — 실제 업종 분류가 아니다. 따라서 KR은 이번 범위에서 섹터 중립화를 적용하지 않는다(적용해도 사실상 KOSPI/KOSDAQ 두 그룹으로만 나뉘어 의미가 없음). KR 업종 데이터 확보(pykrx WICS 등)는 별도 향후 과제로 분리한다.

## 결정: 그룹 내 백분위 랭킹, US만 적용

`QuantScreener.run_screening(df, regime, sector_neutral=False)`에 신규 파라미터를 추가한다. 기본값 `False`는 기존 동작(전체 풀 랭킹)과 100% 동일하다. `True`일 때 `Sector` 컬럼으로 그룹화한 뒤 그룹 내에서만 백분위 순위를 계산한다.

- **적용 팩터**: 가치(PER/PBR)·퀄리티(ROE/영업이익률)·성장성(매출성장률)·모멘텀 4개 팩터 전부 동일하게 그룹 내 랭킹으로 통일한다(팩터별로 다르게 처리하면 코드 분기와 해석이 복잡해짐).
- **적자 기업 페널티(`max_val + 100`) 로직은 변경하지 않는다**: 전체 풀 기준 최댓값+100은 어차피 어떤 섹터의 최댓값보다도 크므로, 섹터별로 그룹 랭킹을 해도 해당 섹터 내에서 여전히 최하위로 정확히 떨어진다.
- **작은 섹터 그룹 문제**: S&P 500 GICS 11개 섹터는 가장 작은 섹터도 20개 이상 종목을 포함하므로, 그룹이 너무 작아 백분위가 불안정해지는 문제는 현재 유니버스에서 실질적으로 발생하지 않는다. 별도의 최소 그룹 크기 폴백 로직은 두지 않는다.
- **표시(UI)**: 별도 UI 변경 없음. 기존 스크리너 테이블에 이미 `Sector` 컬럼과 `FinalScore`가 표시되고 있으므로, 계산 방식만 바뀌고 화면 구성은 그대로 유지한다.

## 호출부 변경

| 위치 | 변경 |
| :--- | :--- |
| `app.py:1090` (종목 스크리너 페이지) | `screener.run_screening(fund_df, regime_choice, sector_neutral=(market_name_key == "us"))` |
| `modules/backtester.py:40` (`run_backtest`) | `self.screener.run_screening(hist_fund_df, regime_choice, sector_neutral=(market_name == "us"))` — 화면의 실시간 스크리닝과 동일한 기준으로 "현재 상위 종목" 선정 |
| `modules/models.py:627` (`calculate_rebalancing`) | **변경 없음.** 포트폴리오는 US/KR 종목이 섞여 있을 수 있어 이번 범위에서 제외 |

## 구현 스케치

```python
def run_screening(self, df, regime, sector_neutral=False):
    ...
    def pct_rank(col, ascending):
        if sector_neutral and 'Sector' in df_clean.columns:
            return df_clean.groupby('Sector')[col].rank(ascending=ascending, pct=True)
        return df_clean[col].rank(ascending=ascending, pct=True)

    df_clean['score_value'] = pct_rank('PER', False) * 50 + pct_rank('PBR', False) * 50
    df_clean['score_quality'] = pct_rank('ROE', True) * 50 + pct_rank('ProfitMargin', True) * 50
    df_clean['score_growth'] = pct_rank('RevenueGrowth', True) * 100
    if 'Momentum' in df_clean.columns:
        df_clean['score_momentum'] = pct_rank('Momentum', True) * 100
    else:
        df_clean['score_momentum'] = 50
    ...
```
(적자 기업 페널티 처리 블록은 그대로 유지)

## 비목표 (Out of scope)

- KR 시장 실제 업종 데이터 확보(pykrx WICS 등) 및 KR 섹터 중립화 적용
- `calculate_rebalancing`(포트폴리오 리밸런싱)에 섹터 중립화 적용
- 최소 섹터 그룹 크기 폴백 로직 (현재 유니버스에서 불필요)
- 신규 UI 컬럼/표시 요소 추가 (기존 Sector 컬럼 + FinalScore로 충분)

## 테스트

`tests/test_models.py`에 `QuantScreener.run_screening` 신규 테스트를 추가한다:
- 2개 섹터로 구성된 작은 데이터셋 구성: 전체 기준으로는 중간 순위지만 자기 섹터 내에서는 최고인 종목을 포함.
- `sector_neutral=False`(또는 기본값)일 때와 `sector_neutral=True`일 때를 비교하여, 후자에서 해당 종목의 `score_value`(또는 `FinalScore`)가 더 높게 나오는지 검증.
- `sector_neutral=True`이지만 `Sector` 컬럼이 없는 경우 예외 없이 전체 풀 기준으로 폴백하는지 검증.
- 기존 동작 회귀 확인: `sector_neutral` 파라미터를 생략했을 때(기본값 `False`) 기존 테스트 스위트가 그대로 통과해야 한다(현재 `QuantScreener`에 대한 유닛 테스트가 없으므로, 이번에 추가하는 회귀 테스트가 사실상 최초의 기준선이 된다).
