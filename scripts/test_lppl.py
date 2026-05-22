import pandas as pd
from modules.data_loader import DataLoader
from modules.models import AnalysisModel

def test_lppl():
    loader = DataLoader()
    model = AnalysisModel()
    
    # 1. 데이터 로드 (S&P500 최근 2년)
    data = loader.get_market_history("S&P500", period="2y")
    if data is None or data.empty:
        print("데이터 로드 실패")
        return
        
    prices = data['Close']
    
    # 2. LPPL 피팅 수행
    print("LPPL 피팅 시작...")
    result = model.run_lppl_fit(prices)
    
    if result:
        print("\n--- LPPL 분석 결과 ---")
        print(f"예상 임계점(Tc): {result['tc_date'].date()}")
        print(f"성장 지수(m): {result['params']['m']:.4f}")
        print(f"버블 징후 여부: {'⚠️ 위험' if result['is_bubble'] else '✅ 정상'}")
        
        # 3. 데이터 일치 여부 확인
        print("\n최근 5일 실제가 vs 예측가:")
        actual_last_5 = prices.tail(5)
        # result['fitted']는 numpy 배열이므로 인덱싱 주의
        predicted_last_5 = result['fitted'][len(prices)-5:len(prices)]
        
        comparison = pd.DataFrame({
            'Actual': actual_last_5.values,
            'Predicted': predicted_last_5
        }, index=actual_last_5.index)
        print(comparison)
    else:
        print("피팅에 실패했습니다.")

if __name__ == "__main__":
    test_lppl()
