# 📈 스토캐스틱 & 윌리엄스 %R 매수/매도 타이밍

## 1. 목적
종목 상세 팝업(`show_stock_details`)에서 스토캐스틱(Stochastic)과 윌리엄스 %R(Williams %R) 두 보조지표를
함께 사용해, 과매도/과매수 구간을 벗어나는 순간(돌파)을 매수·매도 타이밍 신호로 제공합니다.

## 2. 지표 계산
- **Stochastic (14, 3, 3)**
  - Fast%K = (Close - 14일 최저가) / (14일 최고가 - 14일 최저가) × 100
  - %K(Slow%K) = Fast%K의 3일 이동평균
  - %D = %K의 3일 이동평균
- **Williams %R (14)**
  - %R = (14일 최고가 - Close) / (14일 최고가 - 14일 최저가) × -100
  - 별도 스무딩 없이 원값을 그대로 사용

두 지표 모두 최고가/최저가 구간이 0이 되는 경우(장기 횡보)는 나눗셈 오류 대신 결측치로 처리합니다.
최신 봉의 High/Low/Close가 비어 있으면(예: 장중 미확정 캔들) 직전 유효 거래일 기준으로 계산합니다.

## 3. 신호 판정 로직
직전 거래일 대비 오늘 임계값을 돌파했는지로 판정하며, 두 지표가 **같은 날 동시에** 돌파해야 확정 신호입니다.

| 조건 | 신호 |
|---|---|
| %K가 20 상향 돌파 **AND** %R이 -80 상향 돌파 | 🎯 매수 확정 |
| %K가 80 하향 돌파 **AND** %R이 -20 하향 돌파 | 🚫 매도 확정 |
| 둘 중 하나만 돌파 | 👀 관심 (약한 신호) |
| 돌파 없음 | ⏸️ 중립 |

돌파는 "직전 봉은 임계값 밖, 오늘 봉은 임계값 안"인 순간만 인식합니다. 돌파 이후 값이 그대로 유지되어도
새로운 돌파가 아니므로 신호는 다시 중립으로 돌아갑니다 — 순간적인 타이밍 신호이지, 지속적인 상태 표시가
아닙니다.

## 4. 설정
모든 기간·임계값은 `config.yaml`의 `stoch_williams` 섹션에서 조정 가능합니다.

```yaml
stoch_williams:
  k_period: 14
  k_smooth: 3
  d_period: 3
  wr_period: 14
  stoch_oversold: 20
  stoch_overbought: 80
  wr_oversold: -80
  wr_overbought: -20
```

## 5. 구현 위치
- 계산/판정 로직: `modules/models.py`의 `AnalysisModel.calculate_stoch_williams`,
  `classify_stoch_williams_signal`, `calculate_stoch_williams_signal`
- 화면 표시: `app.py`의 `show_stock_details` 팝업, LPPL 분석 아래 섹션
