# invest-support 시스템 확장 고도화 마일스톤

## 마일스톤 01: 펀더멘털 시나리오 가치평가 모듈 (Fundamentals 축)
- [x] config/ 폴더 내에 `valuation_matrix.json`을 생성하여 관심 종목(NVDA, GOOGL)의 목표 멀티플 수치화.
- [x] yfinance API를 연동하여 후행 실적이 아닌 '12M Forward EPS (선행 주당순이익)' 및 월가 컨센서스 추이 자동 추출.
- [x] 실시간 주가를 받아와 현재 위치가 Bull / Base / Bear Case 중 어느 밴드에 속하는지 정량적 퍼센트(%) 지표 산출.

## 마일스톤 02: 계량적 시장 심리 모듈 (Psychology 축)
- [ ] CBOE 또는 대안 API를 통해 S&P 500 지수 및 핵심 빅테크의 옵션 체인(Option Chain) 데이터 파이프라인 구축.
- [ ] 행사가별 콜/풋 미결제약정(Open Interest) 분포를 추적하여 상단 감마 벽(Gamma Wall Upper)과 하단 감마 벽(Gamma Wall Lower) 산출 자동화.
- [ ] 기술적 과매도/과매수 지표(RSI, 200일 이동평균선 이격도)를 감마 월 데이터와 결합한 '심리 과열 지수' 스코어링 모듈 작성[cite: 1].

## 마일스톤 03: 자본 집행 강제 및 알림 인프라 (Execution 축)
- [ ] 현재 300만 원에 멈춰 있는 자본 규모 확장을 위해 시스템 내부의 기계적 분할 배수 룰(3-3-3 규칙) 하드코딩[cite: 1].
- [ ] Telegram Bot API 또는 Slack Webhook 연동 모듈 개발.
- [ ] 단순 가격 변동 알림이 아닌, 사전에 정의된 [Bear 밸류에이션 + 감마 월 하단] 일치 시 "확정 금리 예금 유동성을 깨고 2차 매수 금액(400만 원)을 집행하십시오"라는 액셔너블 텍스트 템플릿 구현[cite: 1].