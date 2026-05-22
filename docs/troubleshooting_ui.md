# 🛠️ UI Troubleshooting & Debugging Guide

이 문서는 Streamlit 기반 대시보드 개발 중 반복적으로 발생하는 UI 관련 문제와 그 해결책을 기록한 기술 부채 관리 문서입니다. 향후 유사한 오류 발생 시 이 가이드를 우선 참조하십시오.

---

## 1. 상세 분석 팝업(`st.dialog`) 자동 닫힘 현상

### ❌ 현상
팝업 내부에서 버튼(예: LPPL 분석 실행, AI 리포트 생성)을 클릭하면 팝업이 즉시 닫혀버리는 현상.

### 🔍 원인 (Streamlit Rerun Model)
Streamlit은 사용자의 모든 상호작용(버튼 클릭 등) 시 코드 전체를 처음부터 다시 실행합니다. 팝업 호출 조건인 `st.session_state.active_ticker`가 코드 실행 도중 초기화되거나, 호출 위치가 실행 경로에서 벗어나면 팝업이 소멸됩니다.

### ✅ 해결책: Persistent Dialog 패턴
1.  **State 기반 트리거**: `active_ticker`를 전역 상태로 관리하고, 팝업 내 **[분석 종료]** 버튼을 누르기 전까지는 `None`으로 초기화하지 않습니다.
2.  **`@st.fragment` 도입**: 팝업 내 하위 로직을 프래그먼트로 분리합니다.
    ```python
    @st.fragment
    def render_analysis():
        if st.button("실행"):
            # 로직 수행
            st.rerun() # 전체 앱이 아닌 프래그먼트만 다시 실행하여 팝업 유지
    ```
3.  **메뉴 이동 시 초기화**: 사이드바 메뉴 클릭 시에는 `active_ticker = None`을 명시하여 의도치 않은 팝업 재출현을 방지합니다.

---

## 2. 종목 변경 시 TradingView 차트 미갱신

### ❌ 현상
A 종목을 본 후 B 종목을 클릭했으나, 차트가 여전히 A 종목의 데이터를 표시하거나 빈 화면으로 남는 현상.

### 🔍 원인 (DOM Reusability)
브라우저와 Streamlit의 컴포넌트 렌더링 최적화 과정에서 동일한 HTML `id`를 가진 컨테이너가 발견되면 기존 인스턴스를 재사용하려 합니다. TradingView JS 위젯은 한 번 로드된 ID에 바인딩되면 내부 심볼만 바꾸는 데 한계가 있습니다.

### ✅ 해결책: Unique Container ID
각 종목별로 고유한 ID를 부여하여 브라우저가 강제로 새 인스턴스를 생성하게 합니다.
```python
# Ticker 기반 고유 ID 생성 (특수문자 제거)
tv_id = f"tv_chart_{ticker.replace('.', '_')}"
tv_html = f'<div id="{tv_id}"></div>...' # HTML 내 ID 적용
```

---

## 3. 테이블 선택 시 StreamlitAPIException 또는 무한 루프

### ❌ 현상
`st.dataframe`의 행을 클릭하면 `StreamlitAPIException` (cannot be modified after instantiation) 오류가 발생하거나 페이지가 무한 새로고침되는 현상.

### 🔍 원인
1.  **시점 위반**: Streamlit은 위젯이 렌더링된 이후에 해당 위젯의 세션 상태를 직접 수정하는 것을 금지합니다.
2.  **중복 실행**: 행 선택 시 `st.rerun()`이 트리거되는데, 선택 상태가 초기화되지 않으면 매 Rerun마다 선택 조건이 참(True)이 되어 무한 루프에 빠집니다.

### ✅ 해결책: Deferred State Clearing (지연된 초기화) 패턴
위젯 렌더링 **이전**에 상태를 초기화하도록 플래그 기반의 지연 처리를 수행합니다.

1.  **플래그 설정 (이벤트 핸들러)**:
    ```python
    if event.selection.rows:
        st.session_state.active_ticker = selected_ticker
        st.session_state.should_clear_table = True # 다음 실행 때 지우라는 신호
        st.rerun()
    ```

2.  **플래그 소비 (스크립트 최상단)**:
    ```python
    # 위젯(st.dataframe)이 정의되기 전 위치해야 함
    if st.session_state.get('should_clear_table'):
        st.session_state["table_key"] = {"selection": {"rows": [], "columns": []}}
        st.session_state.should_clear_table = False
    ```

---

## 💡 개발 시 주의사항
- **Surgical Reruns**: 가능하면 `st.rerun()` 대신 `@st.fragment`를 통한 부분 업데이트를 지향하십시오.
- **State Cleanup**: `st.session_state`에 쓰기 작업을 할 때는 해당 상태를 소비(Consume)하는 곳이 어디인지, 그리고 언제 비워줘야 하는지(Cleanup)를 항상 설계에 포함하십시오.
- **Side Effects**: 메뉴 이동 버튼과 같은 글로벌 내비게이션은 모든 팝업 및 임시 상태를 초기화하는 'Reset' 역할을 겸해야 합니다.

---
*Last Updated: 2026-05-10*
