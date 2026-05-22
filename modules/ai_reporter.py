import os
import google.generativeai as genai
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

class AIReporter:
    def __init__(self):
        # Streamlit Secrets 우선 확인, 없으면 환경 변수 확인
        api_key = None
        if "GOOGLE_API_KEY" in st.secrets:
            api_key = st.secrets["GOOGLE_API_KEY"]
        else:
            api_key = os.getenv("GOOGLE_API_KEY")

        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
        else:
            self.model = None

    def generate_report(self, market_name, lppl_data, attr_data, macro_data=None):
        if not self.model:
            return "🤖 **AI 분석 기능 안내**\n\n현재 AI 분석 기능은 준비 중이거나 서비스 점검 중입니다. (API 키 설정이 필요합니다.)\n지수 및 퀀트 지표 분석 결과는 아래 차트에서 계속 확인하실 수 있습니다."

        # 1. LPPL 데이터 추출
        lppl_params = lppl_data.get('params', {}) if lppl_data else {}
        lppl_status = {
            "tc": lppl_data.get('tc_date', 'N/A') if lppl_data else 'N/A',
            "m": round(lppl_params.get('m', 0), 3),
            "B": round(lppl_params.get('B', 0), 3),
            "omega": round(lppl_params.get('omega', 0), 1),
            "error": round(1 - lppl_data.get('r_squared', 0), 4) if lppl_data else 'N/A',
            "is_bubble": lppl_data.get('is_bubble', False) if lppl_data else False,
            "danger_score": lppl_data.get('danger_score', 0) if lppl_data else 0
        }

        # 2. 매력도 데이터 추출
        details = attr_data.get('details', {})
        attr_status = {
            "score": attr_data.get('score', 0),
            "regime": attr_data.get('regime', 'N/A'),
            "ma_zscore": details.get('Z-이격도', 'N/A'),
            "rsi": details.get('스무딩RSI', 'N/A'),
            "macro_score": details.get('매크로점수', 'N/A'),
            "credit_score": details.get('신용점수', 'N/A')
        }

        # 3. 추가 매크로 데이터 가공
        macro_context = ""
        if macro_data:
            macro_context = f"""
[추가 글로벌 매크로 지표]
- 장단기 금리차(10Y-2Y/3M): {macro_data.get('spread', 'N/A')}%
- 달러 인덱스(DXY): {macro_data.get('dxy', 'N/A')}
- 변동성 지수(VIX): {macro_data.get('vix', 'N/A')}
- 기대 인플레이션(BEI Proxy): {macro_data.get('bei', 'N/A')}
- 금(Gold) 가격: ${macro_data.get('gold', 'N/1')}
- WTI 유가(Oil): ${macro_data.get('oil', 'N/A')}/bbl
"""

        # 4. 리스크 매니저 페르소나 기반 보강된 프롬프트
        prompt = f"""
너는 버블 탐지(LPPL)와 글로벌 매크로 지표를 결합하여 자산 배분을 결정하는 **헤지펀드 리스크 매니저**다.
아래 제공된 다각도의 시장 데이터를 종합하여 {market_name} 시장에 대한 '기관급 리스크 보고서'를 작성하라.

### [입력 데이터: {market_name}]
1. LPPL 버블 진단:
   - 예상 붕괴 시점(tc): {lppl_status['tc']}
   - 파라미터: m={lppl_status['m']}, B={lppl_status['B']}, omega={lppl_status['omega']}
   - 신뢰도(Error): {lppl_status['error']} / 위험점수: {lppl_status['danger_score']}

2. 시장 매력도(퀀트):
   - 종합 점수: {attr_status['score']}/100 (레짐: {attr_status['regime']})
   - 세부: 이격도 {attr_status['ma_zscore']}, RSI {attr_status['rsi']}, 매크로 {attr_status['macro_score']}, 신용 {attr_status['credit_score']}
{macro_context}

---

### [리스크 매니저의 분석 명령]
다음 5가지 관점에서 논리적이고 비판적으로 분석하라:

**1. 매크로 펀더멘털 및 신용 리스크 점검**
- 금리차 역전, 달러 강세, 그리고 특히 **신용 점수(Credit Score)**를 통해 기업들의 자금 조달 환경과 부도 위험을 진단하라.
- VIX 수준을 통해 시장의 공포와 유동성 환경을 정의하라.

**2. LPPL 기반 버블 신뢰도 평가**
- 수학적 파라미터가 버블의 전형적인 '초지수적 성장' 패턴을 보이는지 평가하고, tc까지 남은 기간의 리스크를 산출하라.

**3. 지표 간 상관관계 및 충돌 분석**
- 예: "달러는 강세인데 주식 시장 매력도 점수가 높은 모순적 상황" 등을 포착하여 그 이면의 위험을 설명하라.

**4. 최종 판단 (4대 리스크 국면 분류)**
- 다음 중 하나를 선택: [공격적 매수 / 정상 상승 / 버블 말기 / 리스크 회피]

**5. 행동 지침 (Action Plan)**
- 포지션 비중(%), 헤지 전략(금, 달러 등 활용), 단기/중기 대응 방안을 단호하게 제시하라.

---
**출력 주의사항:**
- 감정적인 서술을 배제하고 오직 **데이터 기반의 차갑고 전문적인 어조**를 유지하라.
- 리포트 제목: [{market_name}] 글로벌 매크로 및 버블 리스크 종합 보고서
"""
    def generate_portfolio_report(self, portfolio_df, rebal_df=None):
        if not self.model:
            return "⚠️ GOOGLE_API_KEY가 설정되지 않았습니다."

        pf_context = portfolio_df.to_string()
        rebal_context = ""
        if rebal_df is not None:
            rebal_context = f"\n\n### [시스템 추천 리밸런싱 지침]\n{rebal_df[['Ticker', 'DangerScore', '비중(%)', 'TargetWeight', 'TradeQty']].to_string()}"
        
        prompt = f"""
너는 세계 최고의 헤지펀드 **포트폴리오 전략가(Portfolio Strategist)**다.
다음은 사용자의 현재 포트폴리오 데이터와 시스템이 산출한 리밸런싱 가이드다:

{pf_context}
{rebal_context}

### [분석 요청 사항]
1. **자산 배분 효율성**: 현재 종목별 비중이 특정 섹터나 종목에 과도하게 쏠려있는지 진단하라.
2. **수익률 및 위험 균형**: 수익률이 높은 종목의 위험 점수(LPPL Danger Score)를 체크하여, 수익 실현이 필요한 시점인지 분석하라.
3. **리밸런싱 지침 해석**: 시스템이 제안한 매매 수량(TradeQty)의 타당성을 검토하고, 실행 우선순위를 정해라.
4. **위험 종목 대응**: 위험 점수 70점 이상의 종목이 있다면 즉각적인 매도 또는 헤지 방안을 제시하라.
5. **최종 코멘트**: 한 줄의 핵심 요약과 함께 '격언' 스타일의 조언을 남겨라.

---
**출력 주의사항:**
- 전문적인 금융 용어를 사용하되 가독성 있게 작성하라.
- 마크다운 형식을 활용하여 보고서 형태로 출력하라.
- 리포트 제목: [Portfolio Strategy] 인텔리전트 포트폴리오 및 리밸런싱 보고서
"""
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"❌ 포트폴리오 리포트 생성 중 오류 발생: {str(e)}"
