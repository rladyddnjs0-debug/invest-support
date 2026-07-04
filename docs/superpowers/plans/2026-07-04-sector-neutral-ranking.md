# 섹터 중립화 랭킹 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `QuantScreener.run_screening()`이 `sector_neutral=True`일 때 PER/PBR/ROE/영업이익률/매출성장률/모멘텀의 백분위 순위를 전체 유니버스가 아니라 `Sector` 그룹 내에서 계산하도록 하고, US 시장(실제 업종 데이터가 있는 곳)에서만 이를 켠다.

**Architecture:** `run_screening`에 `sector_neutral=False`(기본값) 파라미터를 추가해 하위 호환을 유지한다. 내부적으로 각 팩터의 `.rank()` 호출을 `sector_neutral` 여부에 따라 전체 풀 또는 `groupby('Sector')` 기준으로 분기하는 작은 헬퍼로 통일한다. 호출부(`app.py`의 스크리너 페이지, `backtester.py`의 백테스트)에서 US 시장일 때만 `sector_neutral=True`를 전달한다.

**Tech Stack:** pandas `groupby().rank()`. 신규 의존성 없음.

## Global Constraints

- 기본값(`sector_neutral=False`)은 기존 동작과 100% 동일해야 한다 (스펙: "기존 동작과 100% 동일").
- 적자 기업 페널티(`max_val + 100`) 로직은 변경하지 않는다 (스펙: "로직을 변경하지 않는다" — 글로벌 최댓값+100이 섹터별 최댓값보다 항상 크므로 그대로 두어도 섹터 내 최하위로 정확히 떨어짐).
- KR 시장에는 `sector_neutral`을 켜지 않는다 (스펙: "KR은 이번 범위에서 섹터 중립화를 적용하지 않는다" — KR의 `Sector` 필드는 실제 업종이 아니라 "KOSPI"/"KOSDAQ" 상장 시장명).
- `calculate_rebalancing`(`modules/models.py:627`)은 변경하지 않는다 (스펙: "포트폴리오는 US/KR 종목이 섞여 있을 수 있어 이번 범위에서 제외").
- 신규 UI 요소는 추가하지 않는다 — 기존 `Sector` 컬럼과 `FinalScore` 표시로 충분하다 (스펙 "비목표").
- 참조 스펙: `docs/superpowers/specs/2026-07-04-sector-neutral-ranking-design.md`

---

### Task 1: `QuantScreener.run_screening`에 `sector_neutral` 파라미터 추가

**Files:**
- Modify: `modules/models.py:471-526` (`QuantScreener.run_screening`)
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: 없음 (표준 라이브러리 pandas만 사용, 기존 `self.weights`, `logger` 그대로 사용)
- Produces: `QuantScreener.run_screening(self, df, regime, sector_neutral=False) -> pd.DataFrame` — 기존 반환 형식(정렬된 DataFrame, `score_value`/`score_quality`/`score_growth`/`score_momentum`/`FinalScore` 컬럼 포함)은 동일하다. `sector_neutral=True`이고 `df`에 `'Sector'` 컬럼이 있으면 그룹 내 랭킹을, 그렇지 않으면(컬럼 없음) 기존 전체 풀 랭킹으로 자동 폴백한다. Task 2가 이 파라미터를 호출부에서 사용한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_models.py` 파일 맨 끝에 아래 테스트 3개를 추가한다 (파일 상단에 이미 `import pytest`, `import pandas as pd`, `import numpy as np`, `from modules.models import AnalysisModel`가 있으므로 `QuantScreener`만 추가로 import한다):

```python
from modules.models import QuantScreener


def _build_two_sector_df():
    """
    Sector A: PER 10, 20, 30 (종목 A1, A2, A3)
    Sector B: PER 5, 15, 25 (종목 B1, B2, B3)
    전체 풀 기준 PER 오름차순: B1(5) < A1(10) < B2(15) < A2(20) < B3(25) < A3(30)
    -> A1은 전체 6개 중 2번째로 저PER(전체 기준 상위권)이지만,
       Sector A 안에서는 가장 저PER(그룹 내 1위)이므로 sector_neutral일 때 더 높은 score_value를 받아야 한다.
    """
    return pd.DataFrame({
        'Ticker': ['A1', 'A2', 'A3', 'B1', 'B2', 'B3'],
        'Sector': ['A', 'A', 'A', 'B', 'B', 'B'],
        'PER': [10.0, 20.0, 30.0, 5.0, 15.0, 25.0],
        'PBR': [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        'ROE': [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
        'ProfitMargin': [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
        'RevenueGrowth': [5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
        'Momentum': [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    })


def test_run_screening_default_matches_full_pool_ranking():
    screener = QuantScreener()
    df = _build_two_sector_df()

    result = screener.run_screening(df, "Transition (국면 전환)")

    # 전체 풀 기준: B1(PER 5)이 가장 저PER이므로 score_value가 가장 높아야 함
    b1_score = result.loc[result['Ticker'] == 'B1', 'score_value'].iloc[0]
    a1_score = result.loc[result['Ticker'] == 'A1', 'score_value'].iloc[0]
    assert b1_score > a1_score


def test_run_screening_sector_neutral_ranks_within_group():
    screener = QuantScreener()
    df = _build_two_sector_df()

    result = screener.run_screening(df, "Transition (국면 전환)", sector_neutral=True)

    # 섹터 중립화: A1(Sector A 내 최저 PER)이 A2, A3보다 score_value가 높아야 함
    a1_score = result.loc[result['Ticker'] == 'A1', 'score_value'].iloc[0]
    a2_score = result.loc[result['Ticker'] == 'A2', 'score_value'].iloc[0]
    a3_score = result.loc[result['Ticker'] == 'A3', 'score_value'].iloc[0]
    assert a1_score > a2_score > a3_score

    # Sector A 내 최저 PER(A1)과 Sector B 내 최저 PER(B1)은 각자 그룹의 1등이므로 동점(100점)이어야 함
    b1_score = result.loc[result['Ticker'] == 'B1', 'score_value'].iloc[0]
    assert a1_score == pytest.approx(b1_score)


def test_run_screening_sector_neutral_without_sector_column_falls_back():
    screener = QuantScreener()
    df = _build_two_sector_df().drop(columns=['Sector'])

    # Sector 컬럼이 없어도 예외 없이 전체 풀 기준으로 폴백해야 함
    result = screener.run_screening(df, "Transition (국면 전환)", sector_neutral=True)

    b1_score = result.loc[result['Ticker'] == 'B1', 'score_value'].iloc[0]
    a1_score = result.loc[result['Ticker'] == 'A1', 'score_value'].iloc[0]
    assert b1_score > a1_score
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `cd /Users/youngwonkim/develop/workspace/invest-support && source .venv/bin/activate && python3 -m pytest tests/test_models.py -k run_screening -v`
Expected: `test_run_screening_sector_neutral_ranks_within_group`과 `test_run_screening_sector_neutral_without_sector_column_falls_back`이 `TypeError: run_screening() got an unexpected keyword argument 'sector_neutral'`로 FAIL. `test_run_screening_default_matches_full_pool_ranking`은 이미 PASS할 수 있음(현재도 전체 풀 랭킹이 기본 동작이므로) — 그래도 좋다, 이건 회귀 방지용 기준선 테스트다.

- [ ] **Step 3: `run_screening`에 `sector_neutral` 파라미터 구현**

`modules/models.py`에서 아래 블록(471번째 줄부터 시작):

```python
    def run_screening(self, df, regime):
        if df.empty: return df
        
        # 1. 밸류 데이터 전처리 (적자 기업 및 결측치 처리)
        df_clean = df.copy()
        
        # 필수 컬럼 존재 확인 및 수치화
        required_cols = ['PER', 'PBR', 'ROE', 'Momentum', 'RevenueGrowth', 'ProfitMargin']
        for col in required_cols:
            if col not in df_clean.columns:
                logger.warning(f"Column '{col}' missing in screening input. Filling with 0.")
                df_clean[col] = 0.0
            df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce').fillna(0.0)

        # PER, PBR 특수 처리 (낮을수록 좋음, 적자는 최하위)
        for col in ['PER', 'PBR']:
            # 0 이하(적자) 또는 NaN인 경우 해당 컬럼의 최대값 + 100 할당 (최하위 랭킹용)
            mask = (df_clean[col] <= 0)
            if mask.any():
                max_val = df_clean.loc[~mask, col].max() if not df_clean.loc[~mask, col].empty else 100
                df_clean.loc[mask, col] = max_val + 100

        # 2. 랭킹 산출 (낮을수록 점수가 높아야 하므로 ascending=False 적용)
        # 단, 위에서 처리한 '나쁜 값'들이 가장 큰 값을 가지므로 rank(ascending=False) 시 최하위 점수를 받게 됨
        df_clean['score_value'] = (
            df_clean['PER'].rank(ascending=False, pct=True) * 50 + 
            df_clean['PBR'].rank(ascending=False, pct=True) * 50
        )
        
        # 퀄리티 및 성장성 (높을수록 좋으므로 ascending=True)
        df_clean['score_quality'] = (
            df_clean['ROE'].rank(ascending=True, pct=True) * 50 + 
            df_clean['ProfitMargin'].rank(ascending=True, pct=True) * 50
        )
        df_clean['score_growth'] = df_clean['RevenueGrowth'].rank(ascending=True, pct=True) * 100
        
        if 'Momentum' in df_clean.columns:
            df_clean['score_momentum'] = df_clean['Momentum'].rank(ascending=True, pct=True) * 100
        else:
            df_clean['score_momentum'] = 50 
```

를 다음으로 교체한다:

```python
    def run_screening(self, df, regime, sector_neutral=False):
        if df.empty: return df
        
        # 1. 밸류 데이터 전처리 (적자 기업 및 결측치 처리)
        df_clean = df.copy()
        
        # 필수 컬럼 존재 확인 및 수치화
        required_cols = ['PER', 'PBR', 'ROE', 'Momentum', 'RevenueGrowth', 'ProfitMargin']
        for col in required_cols:
            if col not in df_clean.columns:
                logger.warning(f"Column '{col}' missing in screening input. Filling with 0.")
                df_clean[col] = 0.0
            df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce').fillna(0.0)

        # PER, PBR 특수 처리 (낮을수록 좋음, 적자는 최하위)
        for col in ['PER', 'PBR']:
            # 0 이하(적자) 또는 NaN인 경우 해당 컬럼의 최대값 + 100 할당 (최하위 랭킹용)
            mask = (df_clean[col] <= 0)
            if mask.any():
                max_val = df_clean.loc[~mask, col].max() if not df_clean.loc[~mask, col].empty else 100
                df_clean.loc[mask, col] = max_val + 100

        # 섹터 중립화 여부에 따라 전체 풀 또는 섹터 그룹 내 백분위 순위를 계산하는 헬퍼.
        # Sector 컬럼이 없으면(예: 실제 업종 데이터가 없는 시장) 전체 풀 기준으로 자동 폴백한다.
        use_sector_groups = sector_neutral and 'Sector' in df_clean.columns

        def pct_rank(col, ascending):
            if use_sector_groups:
                return df_clean.groupby('Sector')[col].rank(ascending=ascending, pct=True)
            return df_clean[col].rank(ascending=ascending, pct=True)

        # 2. 랭킹 산출 (낮을수록 점수가 높아야 하므로 ascending=False 적용)
        # 단, 위에서 처리한 '나쁜 값'들이 가장 큰 값을 가지므로 rank(ascending=False) 시 최하위 점수를 받게 됨
        df_clean['score_value'] = (
            pct_rank('PER', False) * 50 +
            pct_rank('PBR', False) * 50
        )
        
        # 퀄리티 및 성장성 (높을수록 좋으므로 ascending=True)
        df_clean['score_quality'] = (
            pct_rank('ROE', True) * 50 +
            pct_rank('ProfitMargin', True) * 50
        )
        df_clean['score_growth'] = pct_rank('RevenueGrowth', True) * 100
        
        if 'Momentum' in df_clean.columns:
            df_clean['score_momentum'] = pct_rank('Momentum', True) * 100
        else:
            df_clean['score_momentum'] = 50 
```

(이 아래의 "3. 레짐별 가중치 합산"부터 함수 끝까지는 변경하지 않는다.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /Users/youngwonkim/develop/workspace/invest-support && source .venv/bin/activate && python3 -m pytest tests/test_models.py -k run_screening -v`
Expected: 3개 테스트 모두 PASS

- [ ] **Step 5: 전체 테스트 스위트 회귀 확인**

Run: `cd /Users/youngwonkim/develop/workspace/invest-support && source .venv/bin/activate && python3 -m pytest -q`
Expected: 기존 23개 + 신규 3개 = 26 passed, 0 failed

- [ ] **Step 6: Commit**

```bash
cd /Users/youngwonkim/develop/workspace/invest-support
git add modules/models.py tests/test_models.py
git commit -m "feat: add sector_neutral option to QuantScreener.run_screening"
```

---

### Task 2: 호출부에서 US 시장에만 섹터 중립화 적용

**Files:**
- Modify: `app.py:1090` (종목 스크리너 페이지)
- Modify: `modules/backtester.py:40` (`run_backtest`)

**Interfaces:**
- Consumes: `QuantScreener.run_screening(self, df, regime, sector_neutral=False)` (Task 1에서 정의). Task 1이 이미 병합되어 있으므로 그대로 호출부에 인자만 추가하면 된다.
- Produces: 없음 (이 계획의 마지막 태스크)

- [ ] **Step 1: `app.py`의 스크리너 페이지 호출부 수정**

`app.py`에서 아래 줄(1090번째 줄 부근, `market_name_key` 변수는 이미 이 함수 위쪽에서 "us" 또는 "kr"로 설정되어 있음):

```python
                st.session_state[cache_key] = screener.run_screening(fund_df, regime_choice)
```

를 다음으로 교체한다:

```python
                st.session_state[cache_key] = screener.run_screening(
                    fund_df, regime_choice, sector_neutral=(market_name_key == "us")
                )
```

- [ ] **Step 2: `modules/backtester.py`의 `run_backtest` 호출부 수정**

`modules/backtester.py`에서 아래 줄(40번째 줄, `market_name` 변수는 바로 위 21~31번째 줄에서 "us" 또는 "kr"로 이미 설정됨):

```python
        screened_df = self.screener.run_screening(hist_fund_df, regime_choice)
```

를 다음으로 교체한다:

```python
        screened_df = self.screener.run_screening(
            hist_fund_df, regime_choice, sector_neutral=(market_name == "us")
        )
```

- [ ] **Step 3: 정적 검사**

Run: `cd /Users/youngwonkim/develop/workspace/invest-support && source .venv/bin/activate && python3 -m pyflakes app.py modules/backtester.py`
Expected: 새로 추가한 코드와 관련된 `undefined name` 오류 없음 (기존 무관한 f-string 경고는 무시)

- [ ] **Step 4: 전체 테스트 스위트 재확인**

Run: `cd /Users/youngwonkim/develop/workspace/invest-support && source .venv/bin/activate && python3 -m pytest -q`
Expected: 26 passed, 0 failed (Task 1의 26개 그대로, 이 태스크는 app.py/backtester.py만 건드리므로 테스트 개수 불변)

- [ ] **Step 5: 로컬 서버로 실제 렌더링 확인**

Run:
```bash
cd /Users/youngwonkim/develop/workspace/invest-support
pkill -f "streamlit run app.py" 2>/dev/null; sleep 1
source .venv/bin/activate
nohup streamlit run app.py --server.headless true --server.port 8501 > /tmp/streamlit_sector_neutral.log 2>&1 &
for i in $(seq 1 30); do curl -sf http://localhost:8501/_stcore/health > /dev/null 2>&1 && break; sleep 1; done
```
그 다음 Playwright(이번 세션에서 다른 기능 검증 때 쓴 것과 동일한 헤드리스 브라우저 방식)로:
1. `http://localhost:8501` 접속
2. 사이드바에서 "🔍 종목 스크리너" 클릭, 시장을 "US (S&P500)"로 선택 (기본값)하고 데이터 로딩 대기
3. 결과 테이블이 렌더링되는지, 에러 없이 `Sector`/`FinalScore` 컬럼이 정상적으로 채워지는지 스크린샷으로 확인
4. (선택) 시장을 "KR (KOSPI 200)"로 전환해 KR도 에러 없이 기존과 동일하게 동작하는지 확인 (KR은 `sector_neutral=False`이므로 화면상 랭킹 결과 자체는 이전과 동일해야 함)

Expected: US/KR 모두 에러 없이 정상 렌더링. US 결과의 상위권 종목 구성이 이전(전체 풀 랭킹) 대비 달라질 수 있음(의도된 변화) — 특정 값 검증이 아니라 "에러 없이 렌더링되는지"만 확인하면 된다.

- [ ] **Step 6: Commit**

```bash
cd /Users/youngwonkim/develop/workspace/invest-support
git add app.py modules/backtester.py
git commit -m "feat: enable sector-neutral screener ranking for US market"
```

---

## Self-Review Notes

- **스펙 커버리지**: 스펙의 "결정"(그룹 내 백분위 랭킹, 4개 팩터 전부 통일, 적자 페널티 로직 불변)이 Task 1에, "호출부 변경" 표의 2개 항목(app.py, backtester.py)이 Task 2에 반영됨. `calculate_rebalancing`은 스펙의 "변경 없음" 지시에 따라 어느 태스크에서도 건드리지 않음. "비목표"(KR 업종 데이터 확보, 최소 그룹 크기 폴백, 신규 UI)는 의도적으로 이 계획에서 제외.
- **플레이스홀더 스캔**: "TODO"/"적절히 처리" 등 모호한 지시 없음, 모든 스텝에 실제 코드/명령어 포함.
- **타입/시그니처 일관성**: Task 1에서 정의한 `run_screening(self, df, regime, sector_neutral=False)` 시그니처를 Task 2의 두 호출부에서 동일한 키워드 인자명(`sector_neutral`)으로 사용함. 기존 위치 인자(`df`, `regime`) 순서도 그대로 유지되어 하위 호환 깨지지 않음.
