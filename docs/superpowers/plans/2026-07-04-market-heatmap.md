# 마켓 히트맵 (Finviz 스타일) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** S&P 500 전 종목을 섹터별로 묶어 시가총액(박스 크기)과 당일 등락률(박스 색상)을 한눈에 보여주는 신규 사이드바 메뉴 `🗺️ 마켓 히트맵`을 추가한다.

**Architecture:** 기존 `종목 스크리너`가 이미 쓰는 `DataLoader.get_stock_fundamentals()`(Sector/MarketCap/Name, 7일 파일 캐시)를 재사용하고, 당일 등락률만을 위한 신규 경량 함수 `DataLoader.get_daily_changes()`(yfinance 배치 1회 호출)를 추가해 `st.cache_data(ttl=1800)`로 감싼다. 두 데이터를 merge해 `plotly.express.treemap`으로 렌더링한다.

**Tech Stack:** Python, Streamlit, yfinance, pandas, plotly.express (기존 스택 그대로, 신규 의존성 없음)

## Global Constraints

- 범위는 US(S&P 500)만. KR(KOSPI200)은 포함하지 않는다.
- 색상 지표는 당일 등락률(%)만. 기간 토글은 포함하지 않는다.
- 타일 클릭 인터랙션은 없음 (순수 시각화).
- 당일 등락률은 `@st.cache_data(ttl=1800)`(30분)로 캐시한다.
- `get_daily_changes`는 배치 1회 호출만 수행하며 재시도/백오프 로직을 두지 않는다 (스펙의 비목표 항목).
- 참조 스펙: `docs/superpowers/specs/2026-07-04-market-heatmap-design.md`

---

### Task 1: `DataLoader.get_daily_changes()` 배치 당일 등락률 함수

**Files:**
- Modify: `modules/data_loader.py` (새 메서드를 `get_market_history` 메서드 뒤, `get_sector_data` 앞에 추가 — 파일 내 300번째 줄 부근)
- Test: `tests/test_data_loader.py`

**Interfaces:**
- Consumes: 없음 (표준 라이브러리 `yfinance`, `pandas`, 기존 `self.logger` 대신 모듈 레벨 `logger` — `modules/data_loader.py` 상단에 이미 `from modules.logger import logger`로 import되어 있음)
- Produces: `DataLoader.get_daily_changes(self, tickers: list[str]) -> dict[str, float]` — 티커별 당일 등락률(%). 데이터가 없는 티커는 결과 dict에 아예 포함되지 않는다 (KeyError 없이 조용히 제외). 배치 다운로드 자체가 예외를 던지면 빈 dict `{}`를 반환한다. 이후 Task 2에서 이 함수를 그대로 호출한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_data_loader.py` 파일 맨 끝에 아래 3개 테스트를 추가한다 (파일 상단에 이미 `from unittest.mock import patch, MagicMock`, `import pandas as pd`, `import pytest`가 import되어 있으므로 추가 import 불필요):

```python
@patch('yfinance.download')
def test_get_daily_changes(mock_download, clean_data_loader):
    loader = clean_data_loader

    mock_df = pd.DataFrame({
        ('AAPL', 'Close'): [150.0, 153.0],
        ('MSFT', 'Close'): [300.0, 297.0],
    }, index=pd.date_range(start="2023-01-01", periods=2))
    mock_df.columns = pd.MultiIndex.from_tuples([('AAPL', 'Close'), ('MSFT', 'Close')])
    mock_download.return_value = mock_df

    changes = loader.get_daily_changes(["AAPL", "MSFT"])

    assert changes["AAPL"] == pytest.approx((153.0 / 150.0 - 1) * 100)
    assert changes["MSFT"] == pytest.approx((297.0 / 300.0 - 1) * 100)


@patch('yfinance.download')
def test_get_daily_changes_missing_ticker(mock_download, clean_data_loader):
    loader = clean_data_loader

    # MSFT를 요청했지만 다운로드 결과에는 AAPL만 존재하는 상황
    mock_df = pd.DataFrame({
        ('AAPL', 'Close'): [150.0, 153.0],
    }, index=pd.date_range(start="2023-01-01", periods=2))
    mock_df.columns = pd.MultiIndex.from_tuples([('AAPL', 'Close')])
    mock_download.return_value = mock_df

    changes = loader.get_daily_changes(["AAPL", "MSFT"])

    assert "AAPL" in changes
    assert "MSFT" not in changes


@patch('yfinance.download')
def test_get_daily_changes_download_failure(mock_download, clean_data_loader):
    loader = clean_data_loader
    mock_download.side_effect = Exception("Too Many Requests")

    changes = loader.get_daily_changes(["AAPL", "MSFT"])

    assert changes == {}
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `cd /Users/youngwonkim/develop/workspace/invest-support && source .venv/bin/activate && python3 -m pytest tests/test_data_loader.py -k test_get_daily_changes -v`
Expected: 3개 테스트 모두 `AttributeError: 'DataLoader' object has no attribute 'get_daily_changes'`로 FAIL

- [ ] **Step 3: `get_daily_changes` 최소 구현 작성**

`modules/data_loader.py`에서 `get_market_history` 메서드(현재 `get_historical_fundamentals` 다음, `get_sector_data` 이전)가 끝나는 지점, 즉 아래 코드 바로 뒤에:

```python
            # 재시도 후에도 실패 시, 기존 캐시가 있다면 만료됐더라도 반환 (완전 실패보다 낫음)
            if os.path.exists(file_path):
                logger.warning(f"Returning stale cache for {ticker_symbol} after download failure.")
                return pd.read_csv(file_path, index_col=0, parse_dates=True)
        return None
```

다음 메서드를 추가한다:

```python
    def get_daily_changes(self, tickers):
        """
        전 종목 당일 등락률(%)을 배치 1회 호출로 계산.
        시총/섹터 등 정적 정보는 포함하지 않으며, 데이터가 없는 티커는 결과에서 제외된다.
        """
        try:
            data = yf.download(tickers, period="2d", interval="1d", progress=False, group_by='ticker')
        except Exception as e:
            logger.error(f"Batch daily change download failed: {e}")
            return {}

        changes = {}
        for ticker in tickers:
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    if ticker not in data.columns.levels[0]:
                        continue
                    t_close = data[ticker]['Close'].dropna()
                else:
                    t_close = data['Close'].dropna()
                if len(t_close) >= 2:
                    changes[ticker] = float((t_close.iloc[-1] / t_close.iloc[-2] - 1) * 100)
            except Exception:
                continue
        return changes
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /Users/youngwonkim/develop/workspace/invest-support && source .venv/bin/activate && python3 -m pytest tests/test_data_loader.py -k test_get_daily_changes -v`
Expected: 3개 테스트 모두 PASS

- [ ] **Step 5: 전체 테스트 스위트 회귀 확인**

Run: `cd /Users/youngwonkim/develop/workspace/invest-support && source .venv/bin/activate && python3 -m pytest -q`
Expected: 기존 15개 + 신규 3개 = 18 passed, 0 failed

- [ ] **Step 6: Commit**

```bash
cd /Users/youngwonkim/develop/workspace/invest-support
git add modules/data_loader.py tests/test_data_loader.py
git commit -m "feat: add DataLoader.get_daily_changes for market heatmap coloring"
```

---

### Task 2: 마켓 히트맵 메뉴 UI

**Files:**
- Modify: `app.py`
  - 캐시 래퍼 함수 추가: 74번째 줄 `get_cached_historical_per` 함수 뒤
  - 사이드바 버튼 추가: 294~298번째 줄 `🔍 종목 스크리너` 버튼 블록 뒤, `💎 펀더멘털 가치평가` 버튼 블록 앞
  - 메뉴 페이지 블록 추가: 1373번째 줄(`종목 스크리너` 메뉴 블록의 마지막 줄, `st.error("데이터를 불러오지 못했습니다...")`) 뒤, `elif menu == "💎 펀더멘털 가치평가":` 앞

**Interfaces:**
- Consumes: `DataLoader.get_daily_changes(tickers: list[str]) -> dict[str, float]` (Task 1에서 정의), 기존 `loader.get_sp500_tickers()`, `loader.get_stock_fundamentals(tickers, market_name="us")`, 기존 전역 `loader`/`px`/`st` 객체
- Produces: 새 메뉴 값 `"🗺️ 마켓 히트맵"` (다른 메뉴와 동일하게 `st.session_state.menu`에 저장되는 문자열). 이후 다른 태스크가 이 메뉴 문자열을 참조할 일은 없음 (최종 태스크).

- [ ] **Step 1: 캐시 래퍼 함수 추가**

`app.py`의 아래 블록:

```python
@st.cache_data(ttl=3600*24) # 24시간 캐시
def get_cached_historical_per(ticker, force_download=False):
    """역사적 PER 계산 결과를 캐싱하여 API 호출 최소화"""
    return engine.calculate_historical_per_bands(ticker, force_download=force_download)

# --- 상세 분석 팝업 함수 ---
```

를 다음으로 교체한다 (기존 두 줄은 그대로 두고 바로 아래에 추가):

```python
@st.cache_data(ttl=3600*24) # 24시간 캐시
def get_cached_historical_per(ticker, force_download=False):
    """역사적 PER 계산 결과를 캐싱하여 API 호출 최소화"""
    return engine.calculate_historical_per_bands(ticker, force_download=force_download)

@st.cache_data(ttl=1800) # 30분 캐시 (당일 등락률은 신선도가 중요하므로 짧게 유지)
def get_cached_daily_changes(tickers):
    """당일 등락률을 캐싱하여 히트맵 재렌더링 시 불필요한 API 호출 방지"""
    return loader.get_daily_changes(tickers)

# --- 상세 분석 팝업 함수 ---
```

- [ ] **Step 2: 사이드바 메뉴 버튼 추가**

`app.py`의 아래 블록:

```python
if st.sidebar.button("🔍 종목 스크리너", width="stretch",
                     type="primary" if st.session_state.menu == "🔍 종목 스크리너" else "secondary"):
    st.session_state.menu = "🔍 종목 스크리너"
    st.session_state.active_ticker = None # 메뉴 이동 시 팝업 닫기
    st.rerun()

if st.sidebar.button("💎 펀더멘털 가치평가", width="stretch",
```

를 다음으로 교체한다:

```python
if st.sidebar.button("🔍 종목 스크리너", width="stretch",
                     type="primary" if st.session_state.menu == "🔍 종목 스크리너" else "secondary"):
    st.session_state.menu = "🔍 종목 스크리너"
    st.session_state.active_ticker = None # 메뉴 이동 시 팝업 닫기
    st.rerun()

if st.sidebar.button("🗺️ 마켓 히트맵", width="stretch",
                     type="primary" if st.session_state.menu == "🗺️ 마켓 히트맵" else "secondary"):
    st.session_state.menu = "🗺️ 마켓 히트맵"
    st.session_state.active_ticker = None
    st.rerun()

if st.sidebar.button("💎 펀더멘털 가치평가", width="stretch",
```

- [ ] **Step 3: 메뉴 페이지 블록 추가**

`app.py`에서 `종목 스크리너` 메뉴 블록의 마지막 부분:

```python
                else:
                    st.error("백테스트를 위한 과거 데이터를 충분히 확보하지 못했습니다. (미국 주식은 티커가 너무 많아 시간이 소요될 수 있습니다)")
    else:
        st.error("데이터를 불러오지 못했습니다. 티커 설정을 확인해주세요.")

elif menu == "💎 펀더멘털 가치평가":
```

를 다음으로 교체한다 (기존 두 elif 사이에 새 블록 삽입):

```python
                else:
                    st.error("백테스트를 위한 과거 데이터를 충분히 확보하지 못했습니다. (미국 주식은 티커가 너무 많아 시간이 소요될 수 있습니다)")
    else:
        st.error("데이터를 불러오지 못했습니다. 티커 설정을 확인해주세요.")

elif menu == "🗺️ 마켓 히트맵":
    st.title("🗺️ 마켓 히트맵 (S&P 500)")
    st.markdown("섹터별 시가총액 비중과 당일 등락률을 한눈에 보여주는 실시간 히트맵입니다.")

    with st.spinner('종목 데이터를 불러오는 중...'):
        heatmap_tickers = loader.get_sp500_tickers()
        fund_df = loader.get_stock_fundamentals(heatmap_tickers, market_name="us")

    if fund_df.empty:
        st.error("종목 데이터를 가져올 수 없습니다.")
    else:
        with st.spinner('당일 등락률 계산 중...'):
            daily_changes = get_cached_daily_changes(tuple(fund_df['Ticker'].tolist()))

        heat_df = fund_df.copy()
        heat_df['DayChange'] = heat_df['Ticker'].map(daily_changes)

        missing_count = int(heat_df['DayChange'].isna().sum())
        if len(daily_changes) == 0:
            st.warning("당일 등락률 데이터를 가져오지 못했습니다. 박스 색상이 모두 중립(0%)으로 표시됩니다.")
        elif missing_count > 0:
            st.caption(f"⚠️ {missing_count}개 종목은 당일 등락률을 가져오지 못해 0%로 표시됩니다.")

        heat_df['DayChange'] = heat_df['DayChange'].fillna(0.0)
        heat_df['Sector'] = heat_df['Sector'].fillna('Unknown Sector').replace('', 'Unknown Sector')
        heat_df['MarketCap'] = pd.to_numeric(heat_df['MarketCap'], errors='coerce').fillna(0)
        heat_df = heat_df[heat_df['MarketCap'] > 0]
        heat_df['DisplayName'] = heat_df['Name'].astype(str) + " (" + heat_df['Ticker'].astype(str) + ")"

        if heat_df.empty:
            st.error("시가총액 데이터가 유효한 종목이 없어 히트맵을 그릴 수 없습니다.")
        else:
            max_abs_change = max(float(heat_df['DayChange'].abs().max()), 1e-6)
            fig_heatmap = px.treemap(
                heat_df,
                path=[px.Constant("S&P 500"), 'Sector', 'DisplayName'],
                values='MarketCap',
                color='DayChange',
                hover_data=[c for c in ['PER', 'ROE'] if c in heat_df.columns],
                color_continuous_scale='RdYlGn',
                range_color=[-max_abs_change, max_abs_change],
                color_continuous_midpoint=0,
                title="섹터/종목별 당일 등락률 (박스 크기: 시가총액)",
                template="plotly_dark"
            )
            fig_heatmap.update_layout(margin=dict(t=40, l=10, r=10, b=10), height=700)
            st.plotly_chart(fig_heatmap, width="stretch")

            st.caption(f"펀더멘털(시총/섹터) 캐시는 최대 {settings.data_loader.cache_expiry_days}일, 등락률은 최대 30분 주기로 갱신됩니다.")

elif menu == "💎 펀더멘털 가치평가":
```

- [ ] **Step 4: 정적 검사**

Run: `cd /Users/youngwonkim/develop/workspace/invest-support && source .venv/bin/activate && python3 -m pyflakes app.py`
Expected: 새로 추가한 코드와 관련된 `undefined name` 오류가 없어야 함 (기존에 있던 무관한 f-string 경고는 무시)

- [ ] **Step 5: 전체 테스트 스위트 재확인**

Run: `cd /Users/youngwonkim/develop/workspace/invest-support && source .venv/bin/activate && python3 -m pytest -q`
Expected: 18 passed, 0 failed (Task 1에서 추가한 테스트 포함, app.py는 테스트 대상이 아니므로 카운트 불변)

- [ ] **Step 6: 로컬 서버로 실제 렌더링 확인**

Run:
```bash
cd /Users/youngwonkim/develop/workspace/invest-support
pkill -f "streamlit run app.py" 2>/dev/null; sleep 1
source .venv/bin/activate
nohup streamlit run app.py --server.headless true --server.port 8501 > /tmp/streamlit_heatmap.log 2>&1 &
for i in $(seq 1 30); do curl -sf http://localhost:8501/_stcore/health > /dev/null 2>&1 && break; sleep 1; done
```
그 다음 Playwright(또는 동일 세션에서 이미 쓰던 헤드리스 브라우저 방식)로:
1. `http://localhost:8501` 접속
2. 사이드바에서 "🗺️ 마켓 히트맵" 클릭
3. 트리맵이 렌더링될 때까지 대기 (S&P 500 펀더멘털 캐시가 이미 있다면 수 초 내, 없다면 최초 1회 배치 다운로드로 다소 소요)
4. 스크린샷 촬영 후 육안 확인: Sector별 박스가 보이고, 박스 안에 종목명이 보이고, 색상이 초록/빨강으로 섞여 있고(전부 회색/중립이면 등락률 계산 실패 의심), "펀더멘털... 캐시는 최대 7일, 등락률은 최대 30분..." 캡션이 보이는지 확인

Expected: 에러 메시지 없이 트리맵이 정상 렌더링됨

- [ ] **Step 7: Commit**

```bash
cd /Users/youngwonkim/develop/workspace/invest-support
git add app.py
git commit -m "feat: add Finviz-style market heatmap menu for S&P 500"
```

---

## Self-Review Notes

- **스펙 커버리지**: 스펙의 아키텍처/데이터 흐름(1~6단계), 신규 메뉴 UI, 에러 처리 4가지 케이스, 테스트 요구사항이 Task 1~2에 모두 반영됨. KR 지원/기간 토글/타일 클릭/재시도 로직은 스펙의 비목표 항목이라 포함하지 않음.
- **플레이스홀더 스캔**: "TODO"/"적절히 처리" 등 모호한 지시 없음, 모든 스텝에 실제 코드/명령어 포함.
- **타입/시그니처 일관성**: Task 1에서 정의한 `get_daily_changes(self, tickers) -> dict[str, float]`을 Task 2의 `get_cached_daily_changes(tickers)`와 `heat_df['DayChange'] = heat_df['Ticker'].map(daily_changes)`에서 동일한 이름/반환 타입으로 그대로 사용함.
