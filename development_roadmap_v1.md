# 🚀 Invest Support Dashboard: CLI-based Development Roadmap (v1.1)

이 문서는 투자 분석 엔진의 고도화 및 CLI 기반 실험 아키텍처 구축을 위한 상세 로드맵입니다.

---

## 1. CLI 아키텍처 및 설정 관리 (Core)
핵심 로직을 인터페이스(GUI/CLI)로부터 분리하고, 실험의 재현성을 확보합니다.

### ① 파라미터 외부화 및 유효성 검증 (Configuration & Validation)
- **현황**: `danger_score(70)`, `vol(0.18)` 등 주요 임계값이 코드 내에 하드코딩됨.
- **개선**: `config.yaml`로 모든 파라미터 분리 및 **Pydantic** 모델을 통한 유효성 검증 도입.
- **세부 과제**:
    - `modules/config.py` 신설: 설정 로드 및 타입 체크 로직 통합.
    - 하드코딩된 상수들을 `settings.ENV_VAR` 형태로 전면 교체.

### ② 환경 의존성 제거 (Decoupling)
- **목표**: Streamlit Context 없이도 작동하는 순수 Python 엔진 라이브러리화.
- **수정 포인트**: `data_loader.py` 내의 `add_script_run_ctx` 등 GUI 종속 코드 제거 및 추상화.

---

## 2. 핵심 엔진 고도화 및 안정성 확보

### 📊 [Market Attractiveness] 점수 연속성 및 가중치 스무딩
- **목표**: 국면 전환 시 점수가 급등락하는 '문턱 효과(Threshold effect)' 방지.
- **개선**: 
    - 가중치 변경 시 **시그모이드 함수** 또는 **이동평균(SMA)**을 적용하여 국면 전환을 부드럽게 표현.
    - 신규 팩터 도입 시 USD/KRW 단위 정규화(Normalization) 프로세스 표준화.

### 🛡️ [LPPL Engine] 성능 최적화 및 캐싱
- **목표**: 높은 연산 부하를 관리하고 CLI 반응성 개선.
- **개선**:
    - **Caching Layer**: 동일 티커/파라미터 조합에 대해 `joblib` 또는 `redis`를 활용한 결과 캐싱.
    - **Adaptive Sampling**: 초기 탐색 결과가 나쁠 경우 반복 횟수를 조기에 종료(Early stopping)하는 로직 검토.

### 🔍 [Quant Screener] API 추상화 및 데이터 정규화
- **목표**: 다중 데이터 소스(Alpha Vantage, Quandl 등) 지원.
- **수정 포인트**: 
    - `BaseFetcher` 추상 클래스 설계.
    - 소스별로 다른 필드명과 데이터 단위를 통일하는 **Data Transformer** 레이어 구축.

---

## 3. 검증 및 자동화 (Validation & CI/CD)

### ✅ 전략 스냅샷 테스트 (Historical Snapshot Testing)
- **기능**: 코드 수정 시 주요 역사적 변곡점에서 모델이 어떻게 반응하는지 자동 검증.
- **대상**: 2008년 금융위기, 2020년 코로나 팬데믹, 2022년 금리 인상기.
- **CLI 명령**: `python manage.py test-historical --event covid-19`

### 🔄 CI/CD 파이프라인 연동
- **내용**: GitHub Actions를 통해 `push` 시 핵심 전략의 **전진 분석(Walk-forward analysis)** 수행 및 벤치마크 대비 수익률 저하 여부 체크.

---

## 4. AI 에이전트(Gemini) 인터페이스 고도화
- **추론 투명성**: AI가 산출한 리스크 점수의 근거(어떤 팩터가 가장 크게 기여했는지)를 요약 출력.
- **인터랙티브 디버깅**: AI에게 "현재 DXY 가중치를 0.1 늘렸을 때 매력도 변화는?"과 같은 가상 시나리오(What-if) 질문 지원.

---

## 💡 개발 가이드라인
1. **Surgical Updates**: 기존의 검증된 로직을 수정할 때는 반드시 유닛 테스트를 먼저 작성하십시오.
2. **Data Integrity**: 데이터 소스를 추가할 때 가장 먼저 해야 할 일은 '단위 정규화'와 '결측치 처리 규칙' 정의입니다.
3. **Efficiency**: CPU 집약적인 LPPL 연산은 가급적 백그라운드 프로세스나 캐시를 활용하십시오.

---
*Last Updated: 2026-05-10*
