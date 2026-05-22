from modules.data_loader import DataLoader

def test_loading():
    loader = DataLoader()
    
    print("--- 지수 데이터 테스트 ---")
    sp500 = loader.get_market_history("S&P500", period="1y")
    if sp500 is not None:
        print(f"S&P500 수집 성공: {len(sp500)} 행")
        print(sp500.tail(3))
        
    print("\n--- 장단기 금리차 테스트 ---")
    spread = loader.get_yield_spread(period="1y")
    if spread is not None:
        print(f"금리차 계산 성공: {len(spread)} 행")
        print(spread.tail(3))

if __name__ == "__main__":
    test_loading()
