# 퀀트 스크리너 — 리스크 패리티 Floor/Cap 설계 문서

## 배경

`QuantScreener.calculate_stock_weights`(`modules/models.py:551`)는 종목별 포지션 비중을 아래와 같이 산출한다.

```python
volatility = returns.tail(20).std()   # 실패 시 기본값 0.02
risk_adj_factor = (1.0 / (volatility + 1e-6)) * (row['FinalScore'] / 100.0)
```

이 역변동성(inverse-volatility) 가중치는 `volatility`가 0에 가까울수록 `risk_adj_factor`가 발산한다. 실제로 유동성이 낮은 종목이나 데이터가 얇은 구간에서는 20일 표준편차가 우연히 매우 작게 나올 수 있고, 이 경우 해당 종목이 정규화(`RecWeight = RiskAdjFactor / total_factor`) 이후에도 포트폴리오 비중 대부분을 차지하는 비정상적인 결과가 나올 수 있다. 여러 종목 간 상관관계까지 고려하는 본격적인 공분산 기반 리스크 패리티 최적화는 개인용 대시보드 규모에 비해 과도한 복잡도이므로(사용자 승인 사항), 이번 범위는 **극단값을 막는 하한(floor)/상한(cap) 가드레일**로 좁힌다.

## 결정: `PortfolioConfig`에 floor/cap 값 추가, 정규화 이후 상한 적용 + 재분배

### 설정값 추가 (`modules/config.py`, `config.yaml`)

```python
class PortfolioConfig(BaseModel):
    show_portfolio: bool = True
    default_capital: int = 10000000
    max_equity_weight_at_high_risk: float = 20.0
    danger_thresholds: List[float] = [50.0, 70.0, 85.0]
    risk_penalties: List[float] = [1.0, 0.8, 0.5, 0.2]
    min_volatility_floor: float = 0.005       # 신규: 20일 변동성 하한 (0.5%)
    max_stock_weight_multiple: float = 3.0    # 신규: 동일비중 대비 최대 배수
```

`config.yaml`의 `portfolio` 섹션에 두 값을 동일한 기본값으로 추가한다.

### ① 변동성 하한 적용

```python
volatility = returns.tail(20).std()
volatility = max(volatility, settings.portfolio.min_volatility_floor)
```

데이터 조회 실패 시 기존 기본값 `0.02`는 이미 `min_volatility_floor`(0.005)보다 크므로 그대로 안전하다. 이 한 줄만 추가하면 `risk_adj_factor`의 분모가 더 이상 0에 근접할 수 없다.

### ② 종목별 최대 비중 상한 적용 (정규화 이후)

기존 정규화:
```python
res_df['RecWeight'] = (res_df['RiskAdjFactor'] / total_factor) * total_target_weight_pct
```

이후, 동일비중(`total_target_weight_pct / N`)의 `max_stock_weight_multiple`배를 넘는 종목의 비중을 상한선으로 자르고, 잘려나간 초과분을 상한에 걸리지 않은 종목들에게 **기존 비중 비율대로** 재분배한다. 종목 수가 적고(스크리너 Top 10 기준) 배수가 3배로 넉넉하므로, 한 번의 재분배로 대부분 수렴하지만 안전하게 최대 5회까지 반복한다.

```python
def _apply_weight_cap(rec_weights, total_target_weight_pct, max_multiple):
    n = len(rec_weights)
    if n == 0:
        return rec_weights
    cap = (total_target_weight_pct / n) * max_multiple
    weights = rec_weights.copy()
    for _ in range(5):
        over_mask = weights > cap
        if not over_mask.any():
            break
        excess = (weights[over_mask] - cap).sum()
        weights[over_mask] = cap
        under_mask = ~over_mask
        under_total = weights[under_mask].sum()
        if under_total <= 0:
            break
        weights[under_mask] += excess * (weights[under_mask] / under_total)
    return weights

res_df['RecWeight'] = _apply_weight_cap(
    res_df['RecWeight'], total_target_weight_pct, settings.portfolio.max_stock_weight_multiple
)
```

- 상한에 걸린 종목이 하나도 없으면(대부분의 정상 케이스) 첫 반복에서 즉시 종료되어 기존 동작과 100% 동일하다.
- 모든 종목이 동시에 상한을 초과하는 극단적 경우(`under_total <= 0`)는 이론상 `max_multiple >= 1`이면 발생하지 않지만(상한의 합이 항상 `total_target_weight_pct`보다 크므로), 방어적으로 루프를 즉시 종료해 무한루프를 막는다.

이 헬퍼 함수는 `QuantScreener` 내부의 private 함수(`_apply_weight_cap` 또는 모듈 레벨 함수)로 추가하며, `calculate_stock_weights`에서만 사용한다.

### `calculate_rebalancing`은 변경하지 않음

`calculate_rebalancing`(`modules/models.py:628`)은 변동성 기반 역가중치를 쓰지 않고 퀀트 스코어 비례 배분만 사용하므로(코드 확인 결과, `1/(vol+1e-6)` 로직이 존재하지 않음) 이번 변경의 대상이 아니다.

## 비목표 (Out of scope)

- 공분산 행렬 기반 진짜 리스크 패리티/평균-분산 최적화 — 사용자 승인에 따라 이번 범위에서 명시적으로 제외.
- `min_volatility_floor`/`max_stock_weight_multiple`의 값 자체를 데이터 기반으로 자동 튜닝하는 것 — 지금은 보수적인 고정 기본값을 `config.yaml`에 두고, 필요시 사용자가 수동 조정.
- 손절가/목표가 산출(`get_trade_guide`) 로직 변경 — floor 적용으로 `Volatility` 표시값이 바뀌면서 손절/목표가가 함께 영향을 받는 것은 의도된 부작용이며 별도 처리 불필요(변동성 하한을 적용해도 극단적으로 타이트한 손절선을 막아준다는 점에서 오히려 개선).

## 테스트

`tests/test_models.py`에 다음 케이스를 추가한다:
- `min_volatility_floor` 적용 전/후 비교: 인위적으로 변동성이 0에 매우 가까운(`std() ≈ 1e-8`) 종목을 포함한 `top_df`로 `calculate_stock_weights`를 호출했을 때, floor 미적용 시 발생했을 극단적 `RiskAdjFactor`가 나오지 않고 `Volatility` 컬럼이 `min_volatility_floor` 이상으로 표시되는지 검증.
- `max_stock_weight_multiple` 캡 동작: 위와 동일한 극단 변동성 종목을 포함해, 정규화 후 해당 종목의 `RecWeight`가 `(total_target_weight_pct / N) * max_stock_weight_multiple`을 초과하지 않는지, 그리고 전체 `RecWeight` 합이 `total_target_weight_pct`와 (부동소수점 오차 범위 내) 일치하는지(초과분이 다른 종목에 정확히 재분배되었는지) 검증.
- 회귀 테스트: 모든 종목의 변동성이 상한/하한에 걸리지 않는 정상 케이스에서, 이번 변경 전후 `RecWeight` 값이 동일하게 유지되는지 확인.
