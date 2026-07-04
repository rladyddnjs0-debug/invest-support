# 퀀트 스크리너 — 모멘텀/레짐/리스크패리티 개선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 퀀트 스크리너 방법론 감사(Item C/D/E)를 완료한다 — 모멘텀 팩터를 12-1 정의로 통일하고, 스크리너 페이지의 시장 레짐을 실시간 자동 계산으로 전환하며(수동 오버라이드 유지), 포지션 사이징의 역변동성 가중치에 하한/상한 가드레일을 추가한다.

**Architecture:** 세 항목 모두 기존 함수를 최소 침습적으로 수정한다. 모멘텀은 `modules/data_loader.py`의 기존 배치 다운로드 결과를 그대로 활용해 인덱싱만 바꾸고, 레짐 자동 연동은 이미 리밸런싱 페이지(`app.py:949-951`)에 구현된 `AnalysisModel.calculate_attractiveness()` 패턴을 스크리너 페이지에 재사용하며, 리스크 패리티는 `QuantScreener.calculate_stock_weights`의 정규화 로직 앞뒤에 floor/cap 가드레일을 끼워 넣는다.

**Tech Stack:** Python, pandas, yfinance, pykrx, Streamlit, pytest.

## Global Constraints

- 12-1 모멘텀 정의: 최근 12개월 수익률에서 최근 1개월을 제외한 수익률. US는 21거래일(영업일 기준) 제외, KR은 날짜 구간을 `(오늘-395일, 오늘-30일)`로 조정하여 근사한다. US/KR 모두 이 정의로 통일한다.
- 레짐 자동 계산이 반환하는 문자열은 `QuantScreener.weights`의 키와 정확히 일치하는 3개 값 중 하나여야 한다: `"Risk-on (안정 성장)"`, `"Risk-off (위험 관리)"`, `"Transition (국면 전환)"`.
- `PortfolioConfig`에 `min_volatility_floor: float = 0.005`, `max_stock_weight_multiple: float = 3.0`을 추가하고 `config.yaml`에서 조정 가능하게 한다.
- 공분산 기반 완전 리스크 패리티 최적화, KR 실제 업종 데이터 확보, point-in-time 백테스트 복원은 이번 범위에서 명시적으로 제외한다(사용자 승인 사항).
- 기존 동작 회귀 금지: 세 변경 모두 극단 케이스(짧은 시계열, 자동 계산 실패, 상한/하한 미적용 정상 케이스)에서 기존과 동일하게 동작해야 한다.

---

### Task 1: US 12-1 모멘텀

**Files:**
- Modify: `modules/data_loader.py` (`get_stock_fundamentals` 내부 `fetch_single_ticker` 함수, 가격/모멘텀 계산 블록)
- Test: `tests/test_data_loader.py`

**Interfaces:**
- Consumes: 없음 (기존 `batch_data`, `price_col` 지역 변수만 사용)
- Produces: `fetch_single_ticker`가 채우는 `data['Momentum']` 값의 의미가 "최근 12개월 총수익률"에서 "12-1 모멘텀"으로 변경됨. 이후 태스크(Task 2, 문서화)에서 이 의미 변화를 전제로 한다.

`modules/data_loader.py`의 `get_stock_fundamentals` 안, `fetch_single_ticker` 함수의 가격/모멘텀 계산 블록(아래 코드)을 찾는다:

```python
                # 1. 가격 및 모멘텀 (Batch Data 활용)
                try:
                    if not batch_data.empty:
                        if isinstance(batch_data.columns, pd.MultiIndex):
                            if ticker in batch_data.columns.levels[0]:
                                t_data = batch_data[ticker].dropna()
                            else: t_data = pd.DataFrame()
                        else: t_data = batch_data.dropna()
                            
                        if not t_data.empty:
                            price_col = t_data['Close']
                            if isinstance(price_col, pd.DataFrame): price_col = price_col.iloc[:, 0]
                            curr_price = float(price_col.iloc[-1])
                            start_price = float(price_col.iloc[0])
                            mom = (curr_price / start_price - 1) * 100
                except Exception: pass
```

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_data_loader.py`에 다음 두 테스트를 추가한다 (파일 상단에 이미 있는 `from unittest.mock import patch, MagicMock`, `import pandas as pd` 등을 그대로 사용):

```python
@patch('yfinance.download')
@patch('yfinance.Ticker')
def test_get_stock_fundamentals_us_momentum_excludes_last_month(mock_ticker, mock_download, clean_data_loader):
    loader = clean_data_loader

    # index0=100(12개월 전), index1-7=105, index8=120(1개월 전 시점, 위치 -22),
    # index9-28=80(최근 1개월 구간의 급락), index29=50(현재가)
    closes = [100.0] + [105.0] * 7 + [120.0] + [80.0] * 20 + [50.0]
    assert len(closes) == 30
    mock_df = pd.DataFrame({('Close', 'AAPL'): closes})
    mock_df.columns = pd.MultiIndex.from_tuples([('Close', 'AAPL')])
    mock_download.return_value = mock_df

    mock_info = MagicMock()
    mock_info.info = {
        'shortName': 'Apple Inc.', 'sector': 'Technology', 'currentPrice': 50.0,
        'trailingPE': 30.0, 'priceToBook': 40.0, 'returnOnEquity': 0.5,
        'profitMargins': 0.25, 'revenueGrowth': 0.1, 'marketCap': 2000000000000,
        '52WeekChange': 0.2
    }
    mock_ticker.return_value = mock_info

    res = loader.get_stock_fundamentals(tickers=["AAPL"], market_name="us")

    # 12-1 모멘텀 = (120/100 - 1) * 100 = 20.0 (최근 1개월의 급락은 반영되지 않아야 함)
    assert res.loc[res['Ticker'] == 'AAPL', 'Momentum'].iloc[0] == pytest.approx(20.0)


@patch('yfinance.download')
@patch('yfinance.Ticker')
def test_get_stock_fundamentals_us_momentum_falls_back_when_series_too_short(mock_ticker, mock_download, clean_data_loader):
    loader = clean_data_loader

    # 22거래일 미만이라 12-1 윈도우를 계산할 수 없는 경우
    closes = [100.0, 105.0, 110.0, 115.0, 120.0]
    mock_df = pd.DataFrame({('Close', 'AAPL'): closes})
    mock_df.columns = pd.MultiIndex.from_tuples([('Close', 'AAPL')])
    mock_download.return_value = mock_df

    mock_info = MagicMock()
    mock_info.info = {
        'shortName': 'Apple Inc.', 'sector': 'Technology', 'currentPrice': 120.0,
        'trailingPE': 30.0, 'priceToBook': 40.0, 'returnOnEquity': 0.5,
        'profitMargins': 0.25, 'revenueGrowth': 0.1, 'marketCap': 2000000000000,
        '52WeekChange': 0.3
    }
    mock_ticker.return_value = mock_info

    res = loader.get_stock_fundamentals(tickers=["AAPL"], market_name="us")

    # 시계열이 너무 짧으면 기존과 동일하게 52WeekChange 폴백을 사용해야 함
    assert res.loc[res['Ticker'] == 'AAPL', 'Momentum'].iloc[0] == pytest.approx(30.0)
```

`tests/test_data_loader.py` 상단에 `import pytest`가 없다면 추가한다 (다른 테스트 파일 관례상 이미 있을 가능성이 높으니 먼저 확인).

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_data_loader.py::test_get_stock_fundamentals_us_momentum_excludes_last_month tests/test_data_loader.py::test_get_stock_fundamentals_us_momentum_falls_back_when_series_too_short -v`
Expected: 첫 번째 테스트 FAIL (현재 로직은 `(50/100-1)*100 = -50.0`을 반환하므로 `20.0`과 불일치). 두 번째 테스트는 현재 로직도 `mom=(120/100-1)*100=20.0`이 아니라 `mom != 0`이 되어 폴백을 타지 않으므로 FAIL.

- [ ] **Step 3: 최소 구현**

위 블록을 다음으로 교체한다:

```python
                # 1. 가격 및 모멘텀 (Batch Data 활용, 12-1 모멘텀: 최근 1개월 제외)
                try:
                    if not batch_data.empty:
                        if isinstance(batch_data.columns, pd.MultiIndex):
                            if ticker in batch_data.columns.levels[0]:
                                t_data = batch_data[ticker].dropna()
                            else: t_data = pd.DataFrame()
                        else: t_data = batch_data.dropna()
                            
                        if not t_data.empty:
                            price_col = t_data['Close']
                            if isinstance(price_col, pd.DataFrame): price_col = price_col.iloc[:, 0]
                            curr_price = float(price_col.iloc[-1])
                            if len(price_col) >= 22:
                                price_1mo_ago = float(price_col.iloc[-22])
                                price_12mo_ago = float(price_col.iloc[0])
                                mom = (price_1mo_ago / price_12mo_ago - 1) * 100
                except Exception: pass
```

(`start_price` 변수는 더 이상 쓰이지 않으므로 제거한다. `mom`은 함수 상단에서 이미 `mom = 0`으로 초기화되어 있으므로, 시계열이 22개 미만이면 `mom`이 0으로 남아 이후 `mom if mom != 0 else (info.get('52WeekChange', 0) * 100)` 폴백이 기존과 동일하게 작동한다.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_data_loader.py::test_get_stock_fundamentals_us_momentum_excludes_last_month tests/test_data_loader.py::test_get_stock_fundamentals_us_momentum_falls_back_when_series_too_short -v`
Expected: 둘 다 PASS

- [ ] **Step 5: 전체 회귀 테스트**

Run: `python -m pytest -q`
Expected: 기존 테스트 전부 PASS (특히 `test_get_stock_fundamentals_us`는 batch 데이터가 1행뿐이라 `len(price_col) >= 22`가 False가 되어 기존과 동일하게 `52WeekChange` 폴백을 사용하므로 영향 없음)

- [ ] **Step 6: 커밋**

```bash
git add modules/data_loader.py tests/test_data_loader.py
git commit -m "feat: switch US momentum factor to 12-1 definition"
```

---

### Task 2: KR 12-1 모멘텀 + 스크리너 안내 문구 수정

**Files:**
- Modify: `modules/data_loader.py` (`get_stock_fundamentals` 내부 pykrx 분기)
- Modify: `app.py` (스크리너 페이지 안내 문구, 약 1103번째 줄)
- Test: `tests/test_data_loader.py`

**Interfaces:**
- Consumes: 없음
- Produces: KR `Momentum` 값의 의미가 "최근 6개월 총수익률"에서 "12-1 모멘텀"으로 변경됨(Task 1과 동일한 정의로 통일).

`modules/data_loader.py`에서 다음 블록을 찾는다:

```python
                    df_cap = krx_stock.get_market_cap_by_ticker(date_str, market="ALL")
                    six_months_ago = (target_date - timedelta(days=180)).strftime("%Y%m%d")
                    df_momentum = krx_stock.get_market_price_change_by_ticker(six_months_ago, date_str)
```

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_data_loader.py`에 추가:

```python
@patch('yfinance.download')
@patch('yfinance.Ticker')
def test_get_stock_fundamentals_kr_momentum_uses_12_1_window(mock_ticker, mock_download, clean_data_loader):
    loader = clean_data_loader
    target_date = datetime.now()

    df_kospi = pd.DataFrame({
        'PER': [10.0], 'PBR': [1.0], 'EPS': [1000.0], 'BPS': [10000.0], '종가': [70000.0]
    }, index=['005930'])
    df_kosdaq = pd.DataFrame(columns=df_kospi.columns)
    df_cap = pd.DataFrame({'시가총액': [400000000000000]}, index=['005930'])
    df_momentum = pd.DataFrame({'등락률': [7.5]}, index=['005930'])

    with patch('pykrx.stock.get_market_fundamental_by_ticker') as mock_fund, \
         patch('pykrx.stock.get_market_cap_by_ticker') as mock_cap, \
         patch('pykrx.stock.get_market_price_change_by_ticker') as mock_mom, \
         patch('pykrx.stock.get_market_ticker_name') as mock_name:
        mock_fund.side_effect = lambda date_str, market: df_kospi if market == "KOSPI" else df_kosdaq
        mock_cap.return_value = df_cap
        mock_mom.return_value = df_momentum
        mock_name.return_value = "Samsung Electronics"

        res = loader.get_stock_fundamentals(tickers=["005930.KS"], market_name="kr")

        assert not res.empty
        assert res.iloc[0]['Momentum'] == 7.5

        expected_start = (target_date - timedelta(days=395)).strftime("%Y%m%d")
        expected_end = (target_date - timedelta(days=30)).strftime("%Y%m%d")
        mock_mom.assert_called_once_with(expected_start, expected_end)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_data_loader.py::test_get_stock_fundamentals_kr_momentum_uses_12_1_window -v`
Expected: FAIL — 현재 코드는 `get_market_price_change_by_ticker(six_months_ago, date_str)`를 `(오늘-180일, 오늘)` 인자로 호출하므로 `expected_start`/`expected_end`와 불일치.

- [ ] **Step 3: 최소 구현**

블록을 다음으로 교체한다:

```python
                    df_cap = krx_stock.get_market_cap_by_ticker(date_str, market="ALL")
                    momentum_start = (target_date - timedelta(days=395)).strftime("%Y%m%d")
                    momentum_end = (target_date - timedelta(days=30)).strftime("%Y%m%d")
                    df_momentum = krx_stock.get_market_price_change_by_ticker(momentum_start, momentum_end)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_data_loader.py::test_get_stock_fundamentals_kr_momentum_uses_12_1_window -v`
Expected: PASS

- [ ] **Step 5: 스크리너 안내 문구 수정**

`app.py`에서 다음 텍스트(스크리너 페이지의 "📊 퀀트 점수 산출 로직 상세 가이드" expander 내부)를 찾는다:

```python
            - **계산 방식**: 분석 대상 전체 종목의 최근 수익률(미국 1년, 한국 6개월)을 비교하여 **백분위 순위(Percentile)**를 매깁니다.
```

다음으로 교체한다:

```python
            - **계산 방식**: 분석 대상 전체 종목의 12-1 모멘텀(최근 12개월 수익률에서 최근 1개월 제외, 미국/한국 공통)을 비교하여 **백분위 순위(Percentile)**를 매깁니다.
```

- [ ] **Step 6: 전체 회귀 테스트**

Run: `python -m pytest -q`
Expected: 기존 테스트 전부 PASS

- [ ] **Step 7: 커밋**

```bash
git add modules/data_loader.py app.py tests/test_data_loader.py
git commit -m "feat: switch KR momentum factor to 12-1 definition, update UI copy"
```

---

### Task 3: 레짐 자동/수동 우선순위 결정 함수

**Files:**
- Modify: `modules/models.py` (module-level 함수 추가, `class QuantScreener:` 선언 직전)
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: 없음
- Produces: `resolve_regime_choice(auto_regime: str | None, use_manual_override: bool, manual_choice: str) -> str` — Task 4가 이 함수를 `app.py`에서 import해서 사용한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_models.py` 상단 import에 `resolve_regime_choice`를 추가하고:

```python
from modules.models import AnalysisModel, QuantScreener, resolve_regime_choice
```

테스트 추가:

```python
def test_resolve_regime_choice_uses_auto_by_default():
    result = resolve_regime_choice("Risk-off (위험 관리)", False, "Transition (국면 전환)")
    assert result == "Risk-off (위험 관리)"


def test_resolve_regime_choice_manual_override_wins():
    result = resolve_regime_choice("Risk-off (위험 관리)", True, "Risk-on (안정 성장)")
    assert result == "Risk-on (안정 성장)"


def test_resolve_regime_choice_falls_back_to_manual_when_auto_missing():
    result = resolve_regime_choice(None, False, "Transition (국면 전환)")
    assert result == "Transition (국면 전환)"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_models.py::test_resolve_regime_choice_uses_auto_by_default -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_regime_choice'`

- [ ] **Step 3: 최소 구현**

`modules/models.py`의 import 블록과 `class AnalysisModel:` 선언 사이(파일 최상단, 11~13번째 줄 부근)에 추가한다. 이 위치를 쓰는 이유는 Task 6에서 추가하는 `_apply_weight_cap` 함수(파일 하단 `class QuantScreener:` 바로 위에 위치)와 삽입 지점을 멀리 떨어뜨려, 두 항목을 별도 워크트리에서 병렬로 작업해도 `modules/models.py` 머지 시 충돌이 나지 않도록 하기 위함이다:

```python
from modules.logger import logger


def resolve_regime_choice(auto_regime, use_manual_override, manual_choice):
    """수동 오버라이드가 켜져 있거나 자동 계산에 실패했으면 수동 선택값을, 아니면 자동 계산값을 사용한다."""
    if use_manual_override or not auto_regime:
        return manual_choice
    return auto_regime


class AnalysisModel:
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_models.py::test_resolve_regime_choice_uses_auto_by_default tests/test_models.py::test_resolve_regime_choice_manual_override_wins tests/test_models.py::test_resolve_regime_choice_falls_back_to_manual_when_auto_missing -v`
Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add modules/models.py tests/test_models.py
git commit -m "feat: add resolve_regime_choice helper for auto/manual regime priority"
```

---

### Task 4: 스크리너 페이지에 레짐 자동 연동 배선

**Files:**
- Modify: `app.py` (스크리너 페이지, import 및 사이드바 UI)

**Interfaces:**
- Consumes: Task 3의 `resolve_regime_choice(auto_regime, use_manual_override, manual_choice) -> str`; 기존 전역 `engine`(`AnalysisModel` 인스턴스, `app.py:24`), `loader`(`DataLoader` 인스턴스, `app.py:23`)
- Produces: 없음 (UI 배선의 최종 소비처)

- [ ] **Step 1: import 수정**

`app.py` 8번째 줄:

```python
from modules.models import AnalysisModel, QuantScreener
```

을 다음으로 교체한다:

```python
from modules.models import AnalysisModel, QuantScreener, resolve_regime_choice
```

- [ ] **Step 2: 스크리너 페이지 사이드바 로직 교체**

`app.py`에서 다음 블록(스크리너 페이지 진입부)을 찾는다:

```python
    st.sidebar.header("⚙️ 스크리닝 설정")
    market_type = st.sidebar.radio("대상 시장", ["US (S&P500)", "KR (KOSPI 200)"])
    
    # 레짐 수동 선택 또는 자동 연동 (여기선 간단히 선택지로 제공)
    regime_choice = st.sidebar.selectbox("현재 시장 레짐 (가중치 반영)", 
                                        ["Risk-on (안정 성장)", "Risk-off (위험 관리)", "Transition (국면 전환)"])
    
    market_name_key = "us"
    if market_type == "US (S&P500)":
        with st.spinner('S&P 500 종목 리스트를 가져오는 중...'):
            target_tickers = loader.get_sp500_tickers()
            market_name_key = "us"
    elif market_type == "KR (KOSPI 200)":
        with st.spinner('KOSPI 200 종목 리스트를 가져오는 중...'):
            target_tickers = loader.get_kospi200_tickers()
            market_name_key = "kr"
```

다음으로 교체한다:

```python
    st.sidebar.header("⚙️ 스크리닝 설정")
    market_type = st.sidebar.radio("대상 시장", ["US (S&P500)", "KR (KOSPI 200)"])

    market_name_key = "us"
    if market_type == "US (S&P500)":
        with st.spinner('S&P 500 종목 리스트를 가져오는 중...'):
            target_tickers = loader.get_sp500_tickers()
            market_name_key = "us"
    elif market_type == "KR (KOSPI 200)":
        with st.spinner('KOSPI 200 종목 리스트를 가져오는 중...'):
            target_tickers = loader.get_kospi200_tickers()
            market_name_key = "kr"

    # 레짐 자동 계산 (리밸런싱 페이지와 동일한 방식, 실패 시 수동 선택으로 폴백)
    ref_index = "^GSPC" if market_name_key == "us" else "^KS11"
    ref_data = loader.get_market_history(ref_index, period="6mo")
    auto_regime = None
    if ref_data is not None and not ref_data.empty:
        ref_attr = engine.calculate_attractiveness(ref_data['Close'], None)
        auto_regime = ref_attr['regime'] if ref_attr else None

    use_manual_regime = st.sidebar.checkbox("🔧 레짐 수동 지정", value=False)
    if not auto_regime:
        st.sidebar.warning("레짐 자동 계산 실패 — 수동으로 선택해주세요.")
    manual_regime_choice = st.sidebar.selectbox(
        "현재 시장 레짐 (가중치 반영)",
        ["Risk-on (안정 성장)", "Risk-off (위험 관리)", "Transition (국면 전환)"],
        disabled=(bool(auto_regime) and not use_manual_regime),
    )
    regime_choice = resolve_regime_choice(auto_regime, use_manual_regime, manual_regime_choice)
    if auto_regime and not use_manual_regime:
        st.sidebar.info(f"자동 계산된 레짐: **{regime_choice}**")
```

- [ ] **Step 3: 수동 스모크 테스트**

이 프로젝트는 `app.py`(Streamlit UI)에 대한 자동 테스트 하네스가 없으므로(기존 관례상 UI 로직은 `app.py`에 인라인으로 두고, 단위 테스트는 `modules/`로 한정), 다음을 로컬에서 직접 확인한다:

1. `pkill -f "streamlit run app.py"` 후 `streamlit run app.py`로 재시작(모듈 변경 사항 반영을 위해 필수 재시작).
2. "🔍 종목 스크리너" 메뉴 진입, 대상 시장을 "US (S&P500)"으로 선택 → 사이드바에 "자동 계산된 레짐: **...**" 정보 박스가 나타나고, selectbox는 비활성화(disabled) 상태인지 확인.
3. "🔧 레짐 수동 지정" 체크박스를 켬 → selectbox가 활성화되고, 다른 레짐을 선택하면 화면 하단 "현재 레짐:" 표시와 스크리닝 결과가 선택한 값 기준으로 바뀌는지 확인.
4. 체크박스를 다시 끔 → 자동 계산된 레짐으로 되돌아가는지 확인.
5. 대상 시장을 "KR (KOSPI 200)"으로 변경 → 기준 지수가 `^KS11`로 바뀌어 레짐이 재계산되는지 확인(사이드바 정보 박스의 값이 US일 때와 달라질 수 있음, 값이 아예 안 뜨거나 에러가 나지 않는지가 핵심).

문제가 없으면 다음 단계로 진행한다. 문제가 있으면(예: `KeyError`, 무한 스피너) 원인을 파악해 수정 후 다시 확인한다.

- [ ] **Step 4: 전체 회귀 테스트**

Run: `python -m pytest -q`
Expected: 전부 PASS (이번 태스크는 `app.py`만 수정하므로 `modules/` 유닛 테스트에는 영향 없음)

- [ ] **Step 5: 커밋**

```bash
git add app.py
git commit -m "feat: auto-calculate screener regime with manual override option"
```

---

### Task 5: 리스크 패리티 — 변동성 하한(Floor) 설정 및 적용

**Files:**
- Modify: `modules/config.py` (`PortfolioConfig`)
- Modify: `config.yaml` (`portfolio` 섹션)
- Modify: `modules/models.py` (`QuantScreener.calculate_stock_weights`)
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: 없음
- Produces: `settings.portfolio.min_volatility_floor`(신규 설정값, Task 6에서도 `settings.portfolio.max_stock_weight_multiple`과 함께 참조됨), `_FakeLoader` 테스트 헬퍼(Task 6에서 재사용)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_models.py`에 테스트 헬퍼와 테스트를 추가한다 (파일 하단, 기존 sector-neutral 테스트들 뒤):

```python
class _FakeLoader:
    def __init__(self, histories):
        self._histories = histories

    def get_market_history(self, ticker, period="1y"):
        return self._histories.get(ticker)


def _flat_price_history(periods=25, price=100.0):
    dates = pd.date_range(start="2023-01-01", periods=periods)
    return pd.DataFrame({'Close': [price] * periods}, index=dates)


def _volatile_price_history(periods=25):
    dates = pd.date_range(start="2023-01-01", periods=periods)
    prices = [100.0]
    for i in range(1, periods):
        prices.append(prices[-1] * (1.05 if i % 2 == 0 else 0.95))
    return pd.DataFrame({'Close': prices}, index=dates)


def test_calculate_stock_weights_applies_volatility_floor():
    screener = QuantScreener()
    top_df = pd.DataFrame({
        'Ticker': ['FLAT', 'NORMAL'],
        'FinalScore': [80.0, 80.0],
        'Price': [100.0, 100.0],
    })
    loader = _FakeLoader({
        'FLAT': _flat_price_history(),
        'NORMAL': _volatile_price_history(),
    })

    result = screener.calculate_stock_weights(top_df, total_target_weight_pct=100.0, loader=loader)

    floor_pct = screener.analysis_model.port_config.min_volatility_floor * 100
    flat_vol = result.loc[result['Ticker'] == 'FLAT', 'Volatility'].iloc[0]
    normal_vol = result.loc[result['Ticker'] == 'NORMAL', 'Volatility'].iloc[0]
    assert flat_vol == pytest.approx(floor_pct)
    assert normal_vol > floor_pct
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_models.py::test_calculate_stock_weights_applies_volatility_floor -v`
Expected: FAIL — `AttributeError: 'PortfolioConfig' object has no attribute 'min_volatility_floor'`

- [ ] **Step 3: 최소 구현 — 설정값 추가**

`modules/config.py`의 `PortfolioConfig`를 다음으로 교체한다:

```python
class PortfolioConfig(BaseModel):
    show_portfolio: bool = True
    default_capital: int = 10000000
    max_equity_weight_at_high_risk: float = 20.0
    danger_thresholds: List[float] = [50.0, 70.0, 85.0]
    risk_penalties: List[float] = [1.0, 0.8, 0.5, 0.2]
    min_volatility_floor: float = 0.005
    max_stock_weight_multiple: float = 3.0
```

`config.yaml`의 `portfolio:` 섹션(51~56번째 줄 부근)을 다음으로 교체한다:

```yaml
portfolio:
  show_portfolio: false
  default_capital: 10000000
  max_equity_weight_at_high_risk: 20.0
  danger_thresholds: [50, 70, 85]
  risk_penalties: [1.0, 0.8, 0.5, 0.2] # Corresponds to thresholds
  min_volatility_floor: 0.005
  max_stock_weight_multiple: 3.0
```

- [ ] **Step 4: 최소 구현 — 변동성 하한 적용**

`modules/models.py`의 `calculate_stock_weights` 안에서 다음 줄을 찾는다:

```python
                    # 2. 변동성 계산 (최근 20일 표준편차 기반)
                    returns = hist['Close'].pct_change().dropna()
                    volatility = returns.tail(20).std()
```

다음으로 교체한다:

```python
                    # 2. 변동성 계산 (최근 20일 표준편차 기반, 0에 가까운 값은 하한 적용)
                    returns = hist['Close'].pct_change().dropna()
                    volatility = max(returns.tail(20).std(), self.analysis_model.port_config.min_volatility_floor)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `python -m pytest tests/test_models.py::test_calculate_stock_weights_applies_volatility_floor -v`
Expected: PASS

- [ ] **Step 6: 전체 회귀 테스트**

Run: `python -m pytest -q`
Expected: 전부 PASS

- [ ] **Step 7: 커밋**

```bash
git add modules/config.py config.yaml modules/models.py tests/test_models.py
git commit -m "feat: add volatility floor to risk-parity position sizing"
```

---

### Task 6: 리스크 패리티 — 종목별 최대 비중 상한(Cap) 및 재분배

**Files:**
- Modify: `modules/models.py` (module-level 함수 추가 + `calculate_stock_weights` 배선)
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: Task 5의 `settings.portfolio.max_stock_weight_multiple`, `_FakeLoader`/`_flat_price_history`/`_volatile_price_history` 테스트 헬퍼
- Produces: `_apply_weight_cap(rec_weights: pd.Series, total_target_weight_pct: float, max_multiple: float) -> pd.Series`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_models.py`에 추가:

```python
def test_calculate_stock_weights_caps_extreme_weight_and_redistributes():
    screener = QuantScreener()
    tickers = ['FLAT'] + [f'NORMAL{i}' for i in range(9)]
    top_df = pd.DataFrame({
        'Ticker': tickers,
        'FinalScore': [80.0] * 10,
        'Price': [100.0] * 10,
    })
    histories = {'FLAT': _flat_price_history()}
    histories.update({f'NORMAL{i}': _volatile_price_history() for i in range(9)})
    loader = _FakeLoader(histories)

    result = screener.calculate_stock_weights(top_df, total_target_weight_pct=100.0, loader=loader)

    n = len(tickers)
    cap = (100.0 / n) * screener.analysis_model.port_config.max_stock_weight_multiple
    flat_weight = result.loc[result['Ticker'] == 'FLAT', 'RecWeight'].iloc[0]

    assert flat_weight <= cap + 1e-9
    assert result['RecWeight'].sum() == pytest.approx(100.0)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_models.py::test_calculate_stock_weights_caps_extreme_weight_and_redistributes -v`
Expected: FAIL — FLAT의 `RecWeight`가 상한(`cap`, N=10·multiple=3.0이면 30.0)을 초과함 (변동성이 바닥에 가까운 FLAT이 역변동성 가중치로 인해 압도적 비중을 차지하므로).

- [ ] **Step 3: 최소 구현**

`modules/models.py`에서 `class QuantScreener:` 선언(현재 461번째 줄 부근) 바로 위에 추가한다. Task 3의 `resolve_regime_choice`는 파일 최상단(`class AnalysisModel:` 위)에 위치하므로 이 삽입 지점과 겹치지 않는다:

```python
def _apply_weight_cap(rec_weights, total_target_weight_pct, max_multiple):
    """상한을 초과하는 비중을 상한만큼 자르고, 초과분을 상한 미만 종목에 비례 재분배한다."""
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
```

`calculate_stock_weights` 안에서 다음 블록을 찾는다:

```python
        # 5. 비중 정규화 및 수량 산출
        total_factor = res_df['RiskAdjFactor'].sum()
        if total_factor > 0:
            res_df['RecWeight'] = (res_df['RiskAdjFactor'] / total_factor) * total_target_weight_pct
        else:
            res_df['RecWeight'] = total_target_weight_pct / len(res_df)
```

다음으로 교체한다:

```python
        # 5. 비중 정규화 및 수량 산출
        total_factor = res_df['RiskAdjFactor'].sum()
        if total_factor > 0:
            res_df['RecWeight'] = (res_df['RiskAdjFactor'] / total_factor) * total_target_weight_pct
        else:
            res_df['RecWeight'] = total_target_weight_pct / len(res_df)

        res_df['RecWeight'] = _apply_weight_cap(
            res_df['RecWeight'], total_target_weight_pct, self.analysis_model.port_config.max_stock_weight_multiple
        )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_models.py::test_calculate_stock_weights_caps_extreme_weight_and_redistributes -v`
Expected: PASS

- [ ] **Step 5: 회귀 테스트 추가 — 상한에 걸리지 않는 정상 케이스**

```python
def test_calculate_stock_weights_normal_case_unaffected_by_cap():
    screener = QuantScreener()
    tickers = [f'NORMAL{i}' for i in range(5)]
    top_df = pd.DataFrame({
        'Ticker': tickers,
        'FinalScore': [80.0] * 5,
        'Price': [100.0] * 5,
    })
    loader = _FakeLoader({t: _volatile_price_history() for t in tickers})

    result = screener.calculate_stock_weights(top_df, total_target_weight_pct=100.0, loader=loader)

    # 모든 종목의 변동성이 동일하므로 상한에 걸리지 않고 균등 비중(20%)이 나와야 함
    for t in tickers:
        w = result.loc[result['Ticker'] == t, 'RecWeight'].iloc[0]
        assert w == pytest.approx(20.0, abs=0.5)
```

Run: `python -m pytest tests/test_models.py::test_calculate_stock_weights_normal_case_unaffected_by_cap -v`
Expected: PASS

- [ ] **Step 6: 전체 회귀 테스트**

Run: `python -m pytest -q`
Expected: 전부 PASS

- [ ] **Step 7: 커밋**

```bash
git add modules/models.py tests/test_models.py
git commit -m "feat: cap per-stock risk-parity weight and redistribute excess"
```

---

### Task 7: 문서 업데이트 (README.md, docs/quant_screener.md)

**Files:**
- Modify: `README.md`
- Modify: `docs/quant_screener.md`

**Interfaces:**
- Consumes: Task 1~6에서 완료된 모든 변경 사항
- Produces: 없음 (최종 문서화 태스크)

- [ ] **Step 1: README.md — Phase 8 로드맵 업데이트**

`README.md`에서 다음 블록을 찾는다:

```markdown
- [x] **Phase 8: 퀀트 스크리너 방법론 검증 (진행 중)**:
    - Look-ahead Bias 정직한 재표기: "현재 상위 종목의 최근 1년 성과"가 진짜 point-in-time 백테스트가 아님을 명시.
    - 섹터 중립화 랭킹 도입(US): 팩터 백분위를 전체 유니버스가 아닌 섹터 내에서 산출하도록 개선.
    - 남은 과제: 모멘텀 팩터 정교화, 레짐 자동 연동, 리스크 패리티 개선, 팩터 가중치 통계적 검증 ([상세](docs/quant_screener.md#11-향후-개선-방향)).
```

다음으로 교체한다:

```markdown
- [x] **Phase 8: 퀀트 스크리너 방법론 검증**:
    - Look-ahead Bias 정직한 재표기: "현재 상위 종목의 최근 1년 성과"가 진짜 point-in-time 백테스트가 아님을 명시.
    - 섹터 중립화 랭킹 도입(US): 팩터 백분위를 전체 유니버스가 아닌 섹터 내에서 산출하도록 개선.
    - 12-1 모멘텀으로 US/KR 정의 통일: 최근 1개월 단기 반전 효과를 제외한 표준 모멘텀 팩터 적용.
    - 레짐 자동 연동: 스크리너 화면의 시장 레짐을 실시간 계산값으로 자동 적용(체크박스로 수동 오버라이드 가능).
    - 리스크 패리티 Floor/Cap: 변동성 하한과 종목별 최대 비중 상한을 추가해 역변동성 가중치의 극단값을 방지.
    - 남은 과제: 팩터 가중치 통계적 검증 (point-in-time 백테스트 복원 이후 진행, [상세](docs/quant_screener.md#11-향후-개선-방향)).
```

- [ ] **Step 2: README.md — 스크리너 기능 목록 업데이트**

다음 블록을 찾는다:

```markdown
*   **섹터 중립화 랭킹 (US)**: 전체 유니버스가 아닌 섹터 내 상대 순위로 밸류/퀄리티/성장성/모멘텀 백분위를 계산하여, 저PER·고ROE 구조를 가진 특정 섹터(금융/에너지 등)로 스크리닝 결과가 쏠리는 구조적 편향을 완화. KR은 실제 업종 분류 데이터가 없어 별도 적용하지 않음(향후 과제).
*   **하이브리드 배치 수집**: US 시장 데이터 수집 시 배치(Batch) 다운로드와 병렬 처리를 결합하여 기존 대비 3배 이상의 수집 속도 개선.
```

다음으로 교체한다:

```markdown
*   **섹터 중립화 랭킹 (US)**: 전체 유니버스가 아닌 섹터 내 상대 순위로 밸류/퀄리티/성장성/모멘텀 백분위를 계산하여, 저PER·고ROE 구조를 가진 특정 섹터(금융/에너지 등)로 스크리닝 결과가 쏠리는 구조적 편향을 완화. KR은 실제 업종 분류 데이터가 없어 별도 적용하지 않음(향후 과제).
*   **12-1 모멘텀**: 최근 1개월의 단기 반전 효과를 제외한 12개월 수익률로 US/KR 모멘텀 정의를 통일.
*   **레짐 자동 연동**: 기준 지수(S&P500/KOSPI)의 실시간 시장 매력도 분석 결과로 스크리너 레짐을 자동 적용하며, 필요 시 수동 지정 가능.
*   **리스크 패리티 가드레일**: 포지션 사이징의 역변동성 가중치에 변동성 하한과 종목별 최대 비중 상한을 적용해 극단적 비중 쏠림 방지.
*   **하이브리드 배치 수집**: US 시장 데이터 수집 시 배치(Batch) 다운로드와 병렬 처리를 결합하여 기존 대비 3배 이상의 수집 속도 개선.
```

- [ ] **Step 3: docs/quant_screener.md — 모멘텀 설명 업데이트**

다음 줄을 찾는다:

```markdown
*   **모멘텀 (Momentum)**: 주가 상승 강도가 높을수록 고득점.
```

다음으로 교체한다:

```markdown
*   **모멘텀 (Momentum)**: 12-1 모멘텀(최근 12개월 수익률에서 최근 1개월 제외) 기준, 값이 높을수록 고득점. 최근 1개월의 단기 반전(reversal) 효과를 배제하기 위해 US/KR 공통으로 이 정의를 사용한다.
```

- [ ] **Step 4: docs/quant_screener.md — 활용 방법 섹션 업데이트**

다음 줄을 찾는다:

```markdown
4.  **모멘텀 활용**: 최근 6개월(KR) 또는 1년(US) 수익률을 기반으로 한 추세 점수를 확인하여 진입 시점 결정.
```

다음으로 교체한다:

```markdown
4.  **모멘텀 활용**: 12-1 모멘텀(최근 12개월 수익률에서 최근 1개월 제외, US/KR 공통) 기반 추세 점수를 확인하여 진입 시점 결정.
```

- [ ] **Step 5: docs/quant_screener.md — 레짐 가중치 섹션에 자동 연동 설명 추가**

"## 2. 랭킹 산출 로직"의 "### ② 시장 레짐별 동적 가중치 (Dynamic Weighting)" 표 바로 다음 줄(`## 3. 데이터 수집 아키텍처` 시작 직전)에 아래 내용을 추가한다:

```markdown

시장 레짐은 기준 지수(US: S&P500, KR: KOSPI)의 실시간 시장 매력도 분석 결과(`AnalysisModel.calculate_attractiveness`)로 자동 계산되어 기본 적용된다. 화면의 "🔧 레짐 수동 지정" 체크박스를 켜면 사용자가 직접 다른 레짐을 강제로 선택해 what-if 분석을 할 수 있으며, 자동 계산이 실패한 경우(데이터 조회 실패 등)에는 수동 선택으로 자동 전환된다.
```

- [ ] **Step 6: docs/quant_screener.md — 포지션 사이징 섹션에 floor/cap 설명 추가**

"## 8. 포지션 사이징 자동화 (Phase 4)"의 "### ② 종목 단위 배분 (Stock Level)" 문단 바로 뒤에 아래 내용을 추가한다:

```markdown

**리스크 패리티 가드레일**: 종목별 비중은 역변동성 가중치(변동성이 낮을수록 비중 확대)를 기본으로 하되, 두 가지 안전장치를 둔다. ① 20일 변동성이 `min_volatility_floor`(기본 0.5%) 미만으로 떨어지면 이 값으로 하한을 적용해, 데이터가 얇아 우연히 변동성이 0에 가깝게 나온 종목이 비정상적으로 큰 비중을 차지하는 것을 방지한다. ② 정규화된 비중이 동일비중의 `max_stock_weight_multiple`배(기본 3배)를 넘으면 상한을 적용하고, 초과분을 상한에 걸리지 않은 종목들에 비례 재분배한다. 두 값 모두 `config.yaml`의 `portfolio` 섹션에서 조정 가능하다. 여러 종목 간 상관관계까지 고려하는 공분산 기반 리스크 패리티 최적화는 범위 밖이다(11절 참고).
```

- [ ] **Step 7: docs/quant_screener.md — 향후 개선 방향에서 완료 항목 제거**

"## 11. 향후 개선 방향" 섹션에서 다음 세 줄을 삭제한다:

```markdown
*   **모멘텀 팩터 정교화**: 12-1개월 모멘텀 등 표준적인 정의로 개선하고 KR/US 간 산출 기준 일관성 확보.
*   **레짐 자동 연동**: 현재 수동 선택 방식인 시장 레짐을 실시간 시장 매력도 점수와 자동 연동.
*   **리스크 패리티 개선**: 종목별 포지션 사이징을 공분산 기반으로 정교화하고, 변동성이 0에 가까울 때 `1/(vol+1e-6)`이 비정상적으로 커지는 문제 보완.
```

(이 세 항목은 이번 작업으로 완료되었으므로 향후 과제 목록에서 제거한다. 단, "완전한 공분산 기반 리스크 패리티 최적화"는 이번 범위에서 명시적으로 제외되었으므로 아래처럼 남겨둔다.)

삭제 후 남은 목록 바로 뒤(`자동 리밸런싱 연동` 줄 앞)에 아래 항목을 추가한다:

```markdown
*   **공분산 기반 리스크 패리티**: 현재는 변동성 하한/상한 가드레일만 적용된 상태이며, 종목 간 상관관계를 반영하는 진짜 리스크 패리티 최적화는 별도 과제로 남아있다.
```

- [ ] **Step 8: 전체 회귀 테스트**

Run: `python -m pytest -q`
Expected: 전부 PASS (문서만 변경했으므로 영향 없음)

- [ ] **Step 9: 커밋**

```bash
git add README.md docs/quant_screener.md
git commit -m "docs: document 12-1 momentum, regime auto-link, risk-parity floor/cap"
```
