# 퀀트 스크리너 — 레짐 자동 연동 설계 문서

## 배경

`app.py`의 "🔍 종목 스크리너" 페이지는 스크리닝에 사용할 시장 레짐(Risk-on/Risk-off/Transition)을 `st.sidebar.selectbox`로 완전히 수동 선택하게 되어 있다(`app.py:1054`, 주석: "레짐 수동 선택 또는 자동 연동 (여기선 간단히 선택지로 제공)"). 반면 "⚖️ 포트폴리오 리밸런싱" 페이지(`app.py:949-951`)는 이미 기준 지수 가격을 가져와 `engine.calculate_attractiveness(ref_prices, None)`을 호출하고 그 결과의 `.regime` 필드를 실시간 레짐으로 사용하는 패턴이 구현되어 있다. 스크리너 페이지만 이 패턴을 쓰지 않아, 사용자가 매번 현재 시장 국면을 스스로 판단해서 선택해야 하는 불일치가 있다.

`AnalysisModel.calculate_attractiveness(prices, spread_df, ...)`가 반환하는 `regime` 문자열("Risk-on (안정 성장)" / "Risk-off (위험 관리)" / "Transition (국면 전환)")은 `QuantScreener.weights`의 키와 정확히 동일한 3개 값이므로 그대로 `run_screening`에 전달 가능하다.

## 결정: 기본은 자동 계산, 체크박스로 수동 오버라이드

### 자동 계산 경로

스크리너 페이지에서 시장 선택(`market_type`) 직후, 리밸런싱 페이지와 동일한 방식으로 기준 지수 레짐을 계산한다.

```python
ref_index = "^GSPC" if market_name_key == "us" else "^KS11"
ref_data = loader.get_market_history(ref_index, period="6mo")
auto_regime = None
if ref_data is not None and not ref_data.empty:
    ref_attr = engine.calculate_attractiveness(ref_data['Close'], None)
    auto_regime = ref_attr['regime'] if ref_attr else None
```

`period="6mo"`를 쓰는 이유: `calculate_attractiveness` 내부의 `vol`(20일 변동성)과 `z_score` 계산에 필요한 최소 데이터만 있으면 되고, 리밸런싱 페이지의 `period="2y"`는 LPPL 피팅까지 겸하기 위한 것이라 스크리너 페이지에서는 불필요하게 무겁다. 실패 시(`ref_data`가 비어있거나 `calculate_attractiveness`가 `None` 반환) `auto_regime = None`으로 두고 UI에서 수동 선택으로 자연스럽게 폴백한다(아래 UI 동작 참고).

### UI 동작

```python
use_manual_regime = st.sidebar.checkbox("🔧 레짐 수동 지정", value=False)

if auto_regime and not use_manual_regime:
    regime_choice = auto_regime
    st.sidebar.info(f"자동 계산된 레짐: **{regime_choice}**")
else:
    if not auto_regime:
        st.sidebar.warning("레짐 자동 계산 실패 — 수동으로 선택해주세요.")
    regime_choice = st.sidebar.selectbox(
        "현재 시장 레짐 (가중치 반영)",
        ["Risk-on (안정 성장)", "Risk-off (위험 관리)", "Transition (국면 전환)"],
    )
```

- 체크박스 미선택(기본값) + 자동 계산 성공 → 자동 레짐 사용, 사이드바에 계산된 레짐 표시.
- 체크박스 선택 → 항상 수동 selectbox 노출, 자동 계산값과 무관하게 사용자가 고른 값 사용.
- 자동 계산 실패(`auto_regime is None`) → 체크박스 상태와 무관하게 수동 selectbox 노출(경고 문구 포함).

이후 `regime_choice`는 기존과 동일하게 `screener.run_screening(fund_df, regime_choice, ...)` 호출에 그대로 전달되므로, 스크리닝 로직 자체는 변경하지 않는다.

### 캐싱

기존 캐시 키 `f"screened_{market_type}_{regime_choice}"`는 그대로 유지한다 — `regime_choice`가 자동이든 수동이든 최종적으로 문자열 값 하나로 귀결되므로 캐시 무효화 로직에 변화가 없다.

## 비목표 (Out of scope)

- 리밸런싱 페이지(`app.py:949`)의 레짐 계산 로직 변경 — 이미 자동 연동되어 있으므로 손대지 않는다.
- `calculate_attractiveness` 함수 자체의 로직(레짐 분류 임계값, 가중치 보간 등) 변경 — 이번 작업은 "기존 계산 결과를 스크리너에 연결"하는 배선 작업이며, 레짐 판정 알고리즘 자체는 범위 밖.
- 자동 계산된 레짐의 변경 이력을 추적하거나 알림을 주는 기능.

## 테스트

`tests/test_app` 같은 Streamlit UI 전용 테스트가 현재 프로젝트에 없으므로(기존 관례상 UI 로직은 `app.py`에 인라인으로 두고 단위 테스트 대상은 `modules/`로 한정), 이번 변경의 핵심 로직인 "자동 레짐 계산 → UI 오버라이드 우선순위" 부분은 `app.py`에서 분리하기보다 수동 스모크 테스트로 검증한다:
- 로컬 앱 실행 후 US/KR 각각 스크리너 페이지 진입 시 자동 계산된 레짐이 표시되는지 확인.
- 체크박스를 켰을 때 수동 selectbox가 나타나고 선택값이 화면 하단 "현재 레짐:" 표시와 스크리닝 결과에 반영되는지 확인.
- 네트워크 실패를 흉내내기 위해 `loader.get_market_history`가 빈 DataFrame을 반환하는 경우(모킹 가능하면 유닛 테스트로) 수동 selectbox로 자연 폴백하는지 확인.
