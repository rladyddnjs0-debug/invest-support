# 🚀 Invest Support Dashboard

데이터 기반의 시장 분석, 버블 탐지, 그리고 AI 리서치를 결합한 통합 투자 의사결정 지원 시스템입니다.

---

## 🌟 핵심 기능 (Core Features)

### 1. 📊 시장 지수 및 매력도 분석 ([상세 로직](docs/attractiveness_model.md))
*   **5-Factor 통합 모델**: 추세, 매크로(10Y-2Y 정교화), 유동성(DXY/BTC), Breadth(섹터), 심리(RSI)를 결합한 종합 시장 매력도 산출.
*   **시그모이드(Sigmoid) 연속성**: 매력도 점수 산출 시 시그모이드 함수를 도입하여 임계점 부근의 점수 급변(Whipsaw)을 방지하고 부드러운 국면 전환 유도.
*   **정교한 매크로 지표**: 3개월물 대용치(^IRX)를 사용하여 스프레드 분석의 정확도 향상.

### 2. 🚨 LPPL 버블 진단 ([상세 로직](docs/lppl_model.md))
*   **초지수적 성장 포착**: Log-Periodic Power Law 모델을 활용하여 시장의 가속화된 오버슈팅 및 임계점(Tc) 예측.
*   **피팅 안정성 고도화**: 초기값 샘플링 확장 및 O-S 조건(가속도 대비 진폭 비율) 검증 강화를 통해 가짜 신호(False Positive) 차단력 향상.
*   **Danger Score**: 피팅 신뢰도와 파라미터 유효성을 결합한 0~100점 사이의 고정밀 위험 지수 제공.

### 3. 🔍 퀀트 종목 스크리너 ([상세 로직](docs/quant_screener.md))
*   **레짐별 가중 전략**: 현재 시장 국면(Risk-on/off)에 맞춰 Value, Quality, Growth, Momentum 팩터 가중치 자동 조정.
*   **다차원 시각화 분석**: 섹터별 분포(Treemap), 상위 종목 팩터 프로필(Radar Chart), 가치-효율성 평면(Scatter)을 통한 입체적 종목 분석.
*   **적자 기업 필터링**: PER/PBR이 음수인 기업을 자동으로 감지하여 랭킹 하위권으로 배정, 안정적 우량주 선별 강화.
*   **하이브리드 배치 수집**: US 시장 데이터 수집 시 배치(Batch) 다운로드와 병렬 처리를 결합하여 기존 대비 3배 이상의 수집 속도 개선.

### 4. 🤖 AI 투자 리포트 ([상세 로직](docs/ai_agent.md))
*   **멀티모달 리서치**: 수치 데이터와 차트 패턴을 AI가 종합 분석하여 전문적인 투자 리포트 생성.
*   **지능형 뉴스 요약**: 개별 종목의 최신 뉴스를 수집하고 AI가 핵심 이슈 및 시장 심리를 요약 분석.

---

### 5. 🛠 중앙 설정 및 시스템 고도화 ([상세 로직](development_roadmap_v1.md))
*   **중앙 설정 관리 (Centralized Config)**: `config.yaml`을 통해 모든 분석 파라미터와 가중치를 코드 수정 없이 외부에서 즉시 조정 가능.
*   **환경 독립적 엔진 (Decoupling)**: Streamlit GUI에 종속되지 않는 순수 Python 라이브러리 구조로 핵심 로직을 분리하여 CLI 및 배치 처리 지원.
*   **성능 최적화**: LPPL 엔진에 `joblib` 기반 디스크 캐싱을 도입하여 연산 속도 극대화.
*   **역사적 스냅샷 테스트**: COVID-19 등 주요 역사적 변곡점에서의 모델 성능을 검증하는 독립 스크립트(`scripts/historical_snapshot.py`) 제공.

---

## 📂 디렉토리 구조 (Directory Structure)
...
*   `config.yaml`: 시스템의 모든 임계값, 가중치, 캐시 설정 등을 담은 중앙 설정 파일.
*   `modules/config.py`: Pydantic 기반의 설정 로드 및 유효성 검증 모듈.
...
*   `scripts/historical_snapshot.py`: 역사적 위기 시점의 모델 성능 재현 테스트 도구.

---

## 🛠 기술 스택 (Technical Specs)

*   **Language**: Python 3.14+
*   **Frontend**: Streamlit (Persistent Dialogs & Updated UI Standards)
*   **Visualization**: Plotly (Interactive Treemaps, Radar Charts, Scatter)
*   **Data Source**: Yahoo Finance (`yfinance` Batch Mode), `pykrx`
*   **AI Model**: Google Gemini 1.5 Pro / Flash
*   **Optimization**: SciPy (Least Squares & Global Optimization prep)

---

## 🚀 시작하기 (Getting Started)

### 1. 환경 설정
```bash
# 가상환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt
```

### 2. API 키 및 보안 설정
*   **로컬 실행**: `.env` 파일을 생성하고 아래 내용을 입력합니다 (이미 `.gitignore`에 포함되어 있어 안전합니다).
*   **GitHub/Streamlit 배포**: Streamlit Community Cloud의 **Secrets** 설정 메뉴에 아래 항목을 입력하세요.

```env
# Google Gemini API Key (필수)
GOOGLE_API_KEY=your_gemini_api_key_here

# KRX(한국거래소) 계정 정보 (선택)
KRX_ID=your_krx_id
KRX_PW=your_krx_password
```

### 3. 기능 제어 (포트폴리오 비활성화 등)
GitHub에 공개 시 개인적인 포트폴리오 기능을 숨기고 싶다면 `config.yaml` 파일을 수정하세요:
```yaml
# config.yaml
portfolio:
  show_portfolio: false  # true로 설정 시 메뉴에 표시됨
```
현재 `.gitignore` 설정으로 인해 `data/portfolio.json` 파일은 GitHub에 올라가지 않습니다.

### 4. 실행
```bash
streamlit run app.py
```

---

## 🔍 주요 시장 커버리지 (Market Coverage)

*   **US**: S&P 500 전 종목 (yfinance 기반 배치 수집)
*   **KR**: KOSPI 200 전 종목 (pykrx 기반 실시간 데이터)
*   **Global Macro**: 환율, 금리(10Y-2Y), 유가, 금, 비트코인, 섹터 ETF 등

---

## 🎯 핵심 철학 및 설계 원칙 (Philosophy)

### 1. 핵심 철학 (Core Philosophy)
*   **"예측"보다는 "대응"**: "언제 오를지"를 맞추는 예측 모델에 집착하기보다, 현재 시장이 "얼마나 위험한지"를 판단하고 그에 맞는 자산 배분 전략을 실행하는 것을 목표로 합니다.
*   **통계적 필터링**: 하나라도 강력한 결격 사유(데이터 부족, 통계적 유의성 미달 등)가 있다면 리스크 점수를 과감하게 낮추어 가짜 신호(False Positive)를 차단합니다.

### 2. 설계 원칙 (Anti-Patterns)
*   **과도한 기술적 지표 배제**: RSI나 이동평균선 등은 보조적인 매력도 산출 용도로만 사용하며, 이를 단독 매매 신호로 사용하지 않습니다.
*   **AI 의존 금지**: AI 리포트는 정량적 분석 결과의 해석을 돕는 도구일 뿐이며, 최종 의사결정은 항상 데이터와 사용자의 판단이 우선합니다.

---

## 📈 개발 로드맵 (Current Status)

- [x] **Phase 1: 시스템 안정화**: 모델 로버스트니스 강화 및 예외 처리.
- [x] **Phase 2: 유동성 + Breadth 통합**: 시장 내부 체력 및 자금 흐름 분석 도입.
- [x] **Phase 3: 퀀트 스크리너 고도화**: S&P 500 및 KOSPI 200 전 종목 실시간 스크리닝 구현.
- [x] **Phase 4: 포지션 사이징 자동화**: 위험 점수 기반의 기계적 비중 관리 시스템 구축.
- [x] **Phase 5: 포트폴리오 리밸런싱**: 실시간 리스크 연동 및 구체적 매매 지침 자동화.
- [x] **Phase 6: 로직 정교화 및 성능 최적화**: 
    - 10Y-2Y 지표 정확도 향상 및 시그모이드 연속성 도입.
    - LPPL 피팅 안정성 및 퀀트 밸류 필터링 강화.
    - US 데이터 수집 속도 최적화 및 다차원 시각화 도입.

---

## ⚖️ 면책 조항 (Disclaimer)
본 프로그램은 투자 참고용으로만 제작되었으며, 모든 투자의 책임은 투자자 본인에게 있습니다. 과거의 성과가 미래의 수익을 보장하지 않습니다.
