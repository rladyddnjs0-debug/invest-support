# 백테스트 Look-ahead Bias 정직화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 퀀트 스크리너의 "1년 전 성과 백테스트" 기능이 실제로는 오늘 시점 펀더멘털로 종목을 선정한다는 사실을 UI/문서에 정확히 반영해, look-ahead bias를 사용자가 명확히 인지하도록 한다.

**Architecture:** 계산 로직(`backtester.py`의 수익률/샤프지수/MDD 계산)은 전혀 건드리지 않는다. `app.py`의 사용자 노출 문구, `modules/backtester.py`의 docstring, `docs/quant_screener.md`의 설명을 사실에 맞게 교체하고, 화면에 명시적인 bias 경고를 추가한다.

**Tech Stack:** Streamlit (`st.warning`), Markdown 문서. 신규 의존성 없음.

## Global Constraints

- 계산 로직(수익률/샤프지수/MDD) 자체는 절대 변경하지 않는다 (스펙의 "결정" 섹션).
- `get_historical_fundamentals` 함수명은 변경하지 않는다 (스펙의 "비목표" 섹션 — docstring이 이미 정직함).
- 진짜 point-in-time 펀더멘털 복원은 이번 범위에서 제외한다 (스펙의 "비목표" 섹션, 별도 과제로 분리됨).
- 참조 스펙: `docs/superpowers/specs/2026-07-04-backtest-honest-relabel-design.md`

---

### Task 1: UI 문구, docstring, 문서를 사실에 맞게 교체

**Files:**
- Modify: `app.py:1331-1381` (스크리너 페이지의 백테스트 섹션)
- Modify: `modules/backtester.py:13-16` (`run_backtest` docstring)
- Modify: `docs/quant_screener.md` (5절 "성과 검증 (Backtesting)")

**Interfaces:**
- Consumes: 없음 (신규 함수/클래스 없음, 기존 `backtester.run_backtest(market_type, regime_choice)` 호출 시그니처는 변경하지 않음)
- Produces: 없음 (이 태스크가 계획의 유일한 태스크이며, 순수 텍스트 변경이라 후속 태스크가 참조할 신규 인터페이스가 없음)

- [ ] **Step 1: `app.py`의 백테스트 섹션 텍스트 교체**

`app.py`에서 아래 블록(1331~1341번째 줄 부근):

```python
        # --- 백테스트 시뮬레이션 섹션 ---
        st.markdown("---")
        st.subheader("📊 퀀트 전략 과거 성과 시뮬레이션")
        st.markdown("""
        현재 선택된 **레짐 가중치**를 바탕으로, **정확히 1년 전**에 선정된 상위 10개 종목에 투자했을 때의 성과를 확인합니다.
        (한국: 펀더멘털+모멘텀 복합 / 미국: 모멘텀 중심)
        """)
        
        if st.button("🚀 1년 전 성과 백테스트 실행", width="stretch"):
            with st.spinner('1년 전 시장 데이터를 분석하고 성과를 계산 중...'):
```

를 다음으로 교체한다:

```python
        # --- 백테스트 시뮬레이션 섹션 ---
        st.markdown("---")
        st.subheader("📊 현재 상위 종목의 최근 1년 성과 (참고용)")
        st.markdown("""
        현재 **레짐 가중치**로 오늘 기준 상위 10개 종목을 선정한 뒤, 그 종목들이 지난 1년간 실제로 어떤 수익률을 기록했는지 보여줍니다.
        (한국: 펀더멘털+모멘텀 복합 / 미국: 모멘텀 중심)
        """)
        st.warning(
            "⚠️ 이 결과는 '1년 전에 이 전략을 썼다면 어땠을까'를 검증하는 진짜 백테스트가 아닙니다. "
            "종목 선정 자체가 **오늘 시점의 펀더멘털 데이터**로 이뤄지기 때문에, 현재 펀더멘털이 좋은 "
            "종목은 최근 1년간 주가도 함께 오른 경우가 많아 실제보다 낙관적인 결과가 나올 수 있습니다 "
            "(사전관찰 편향, look-ahead bias)."
        )
        
        if st.button("🚀 현재 상위 종목 최근 1년 성과 조회", width="stretch"):
            with st.spinner('상위 종목의 최근 1년 성과를 분석 중...'):
```

- [ ] **Step 2: 결과 표시부의 "1년 전 선정되었던" 문구 교체**

`app.py`에서 아래 줄(1378번째 줄 부근):

```python
                    with st.expander("📌 1년 전 선정되었던 Top 10 종목 보기"):
```

를 다음으로 교체한다:

```python
                    with st.expander("📌 오늘 기준으로 선정된 Top 10 종목 보기"):
```

- [ ] **Step 3: `modules/backtester.py`의 `run_backtest` docstring 교체**

`modules/backtester.py`에서:

```python
    def run_backtest(self, market_type, regime_choice, lookback_days=365):
        """
        1년 전 시점의 Top 10 종목을 선정하고 현재까지의 성과를 계산합니다.
        """
```

를 다음으로 교체한다:

```python
    def run_backtest(self, market_type, regime_choice, lookback_days=365):
        """
        '오늘 시점'의 펀더멘털로 선정한 Top 10 종목이 지난 1년간 기록한 실제 수익률을 계산합니다.
        주의: 종목 선정에 사용하는 펀더멘털은 항상 최신 데이터이며 base_date 시점으로 되돌아가지
        않으므로, 이는 전략의 사전 예측력을 검증하는 진짜 point-in-time 백테스트가 아니라
        참고용 성과 조회 기능입니다 (look-ahead bias 있음).
        """
```

- [ ] **Step 4: `docs/quant_screener.md`의 5절 교체**

`docs/quant_screener.md`에서:

```markdown
## 5. 성과 검증 (Backtesting)
전략의 신뢰도를 높이기 위해 '1년 전 시점'의 데이터를 활용한 성과 검증 기능을 제공합니다.
*   **포인트-인-타임 분석**: 1년 전 기준일의 펀더멘털(KR) 및 모멘텀 데이터를 추출하여 당시의 Top 10 종목을 선정합니다.
*   **누적 수익률 비교**: 선정된 10개 종목의 동일 비중 포트폴리오 성과를 해당 시장 지수(KOSPI 또는 S&P 500)와 실시간으로 비교 시각화합니다.
*   **알파(Alpha) 도출**: 시장 대비 초과 수익률을 계산하여 현재 설정된 레짐 가중치의 유효성을 검증합니다.
```

를 다음으로 교체한다:

```markdown
## 5. 현재 상위 종목의 최근 1년 성과 (참고용, 진짜 백테스트 아님)
현재 레짐 가중치로 **오늘 시점** 펀더멘털을 기준으로 Top 10을 선정한 뒤, 그 종목들의 최근 1년 실제 수익률을 보여주는 참고 기능입니다.
*   **⚠️ Look-ahead Bias 주의**: 종목 선정 자체가 오늘 시점 데이터로 이뤄지므로, "1년 전에 이 전략을 썼다면 어땠을까"를 검증하는 진짜 point-in-time 백테스트가 아닙니다. 현재 펀더멘털이 좋은 종목은 최근 주가도 함께 오른 경우가 많아, 여기서 계산되는 초과수익은 실제 실전 성과보다 낙관적으로 나올 수 있습니다.
*   **누적 수익률 비교**: 선정된 10개 종목의 동일 비중 포트폴리오 성과를 해당 시장 지수(KOSPI 또는 S&P 500)와 비교 시각화합니다. 계산 자체(수익률/샤프지수/MDD)는 정확하지만, "레짐 가중치의 유효성을 검증한다"는 의미로 해석해서는 안 됩니다.
*   **향후 개선 과제**: 과거 분기 재무제표 + 과거 주가를 결합해 진짜 point-in-time 펀더멘털을 복원하는 것이 근본적인 해결책이며, 11절(향후 개선 방향)에 이미 등재되어 있습니다.
```

- [ ] **Step 5: 정적 검사**

Run: `cd /Users/youngwonkim/develop/workspace/invest-support && source .venv/bin/activate && python3 -m pyflakes app.py modules/backtester.py`
Expected: 새로 추가/수정한 코드와 관련된 `undefined name` 오류가 없어야 함 (기존에 있던 무관한 f-string 경고는 무시)

- [ ] **Step 6: 전체 테스트 스위트 회귀 확인**

Run: `cd /Users/youngwonkim/develop/workspace/invest-support && source .venv/bin/activate && python3 -m pytest -q`
Expected: 기존 테스트 개수 그대로 전부 PASS (텍스트 변경이므로 신규/실패 테스트 없어야 함)

- [ ] **Step 7: 로컬 서버로 실제 렌더링 확인**

Run:
```bash
cd /Users/youngwonkim/develop/workspace/invest-support
pkill -f "streamlit run app.py" 2>/dev/null; sleep 1
source .venv/bin/activate
nohup streamlit run app.py --server.headless true --server.port 8501 > /tmp/streamlit_backtest_relabel.log 2>&1 &
for i in $(seq 1 30); do curl -sf http://localhost:8501/_stcore/health > /dev/null 2>&1 && break; sleep 1; done
```
그 다음 Playwright(이번 세션에서 다른 기능 검증 때 쓴 것과 동일한 헤드리스 브라우저 방식)로:
1. `http://localhost:8501` 접속 후 새로고침(모듈이 아니라 `app.py` 텍스트만 바뀌었으므로 프로세스 재시작 없이도 반영되지만, 확실히 하려면 재시작된 프로세스로 접속)
2. 사이드바에서 "🔍 종목 스크리너" 클릭 (US 또는 KR 아무 시장이나 선택, 데이터 로딩 대기)
3. 페이지 하단의 백테스트 섹션까지 스크롤
4. 스크린샷 촬영 후 육안 확인: 제목이 "현재 상위 종목의 최근 1년 성과 (참고용)"으로 보이는지, `st.warning` 노란 박스에 look-ahead bias 경고 문구가 보이는지, 버튼 라벨이 "현재 상위 종목 최근 1년 성과 조회"로 보이는지
5. (선택) 버튼을 클릭해 기존과 동일하게 정상 동작(에러 없이 결과 또는 "데이터 부족" 메시지가 뜨는지)하는지 확인 — 미국 시장은 티커 수가 많아 시간이 오래 걸릴 수 있으므로 필수는 아님

Expected: 새 문구가 정확히 표시되고, 기존 버튼 동작에는 변화가 없음

- [ ] **Step 8: Commit**

```bash
cd /Users/youngwonkim/develop/workspace/invest-support
git add app.py modules/backtester.py docs/quant_screener.md
git commit -m "docs: honestly relabel backtest as look-ahead-biased reference metric"
```

---

## Self-Review Notes

- **스펙 커버리지**: 스펙의 "변경 대상" 1~3번(app.py, backtester.py, quant_screener.md)이 Step 1~4에 모두 반영됨. "비목표"(point-in-time 복원, 함수명 변경, 계산 로직 변경)는 의도적으로 이 계획에 포함하지 않음.
- **플레이스홀더 스캔**: "TODO"/"적절히 처리" 등 모호한 지시 없음, 모든 스텝에 정확한 before/after 텍스트 포함.
- **타입/시그니처 일관성**: 이 계획은 단일 태스크이며 신규 함수/인터페이스를 도입하지 않으므로 태스크 간 시그니처 불일치 위험이 없음.
