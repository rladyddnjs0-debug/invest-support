import yfinance as yf
import json

def update():
    assets = [
        {"Ticker": "360750.KS", "Eval": 14330630, "Return": 7.31, "Curr": "KRW", "Notes": "포트폴리오 핵심(Core) 자산"},
        {"Ticker": "409120.KS", "Eval": 5449950, "Return": 11.32, "Curr": "KRW", "Notes": "환헤지형 지수 투자"},
        {"Ticker": "GOOGL", "Eval": 4491486, "Return": 37.71, "Curr": "USD", "Notes": "최고 수익률 기록 중"},
        {"Ticker": "VRT", "Eval": 3484708, "Return": 10.61, "Curr": "USD", "Notes": "전력 인프라/데이터센터 수혜"},
        {"Ticker": "NVDA", "Eval": 3406275, "Return": 13.84, "Curr": "USD", "Notes": "AI 반도체 대장주"},
        {"Ticker": "BRK-B", "Eval": 2086722, "Return": -4.67, "Curr": "USD", "Notes": "가치주 중심의 방어 자산"},
        {"Ticker": "PFE", "Eval": 1938495, "Return": 9.17, "Curr": "USD", "Notes": "헬스케어 배당/방어주"},
        {"Ticker": "ARM", "Eval": 1249246, "Return": 8.72, "Curr": "USD", "Notes": "AI IP 설계 저변 확대"},
        {"Ticker": "COHR", "Eval": 938522, "Return": 0.81, "Curr": "USD", "Notes": "광통신/레이저 솔루션"},
        {"Ticker": "457440.KQ", "Eval": 310, "Return": -75.25, "Curr": "KRW", "Notes": "소액 비중 (손실폭 확대)"}
    ]

    try:
        usd_krw = yf.download("USDKRW=X", period="1d")['Close'].iloc[-1].item()
    except:
        usd_krw = 1467.0

    new_portfolio = []
    
    for a in assets:
        ticker = a['Ticker']
        try:
            # Try to fetch current price to get a realistic Quantity
            price_df = yf.download(ticker, period="5d")
            if not price_df.empty:
                current_price = price_df['Close'].iloc[-1].item()
            else:
                raise Exception("Empty DF")
        except:
            # Fallback estimation if fetching fails
            # We use 10,000 KRW as a base for Korean stocks, $100 for US
            current_price = 10000.0 if a['Curr'] == "KRW" else 100.0
            print(f"Estimation used for {ticker}")
            
        rate = usd_krw if a['Curr'] == "USD" else 1.0
        qty = a['Eval'] / (current_price * rate)
        avg_p = current_price / (1 + a['Return']/100)
        
        new_portfolio.append({
            "Ticker": ticker,
            "Quantity": round(float(qty), 6),
            "AvgPrice": round(float(avg_p), 4),
            "Currency": a['Curr'],
            "Notes": a['Notes']
        })

    with open("data/portfolio.json", "w") as f:
        json.dump(new_portfolio, f, indent=4)
    print("Updated data/portfolio.json with 10 assets.")

if __name__ == "__main__":
    update()
