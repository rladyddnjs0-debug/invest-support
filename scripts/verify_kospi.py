import pandas as pd
import yfinance as yf
from modules.data_loader import DataLoader
from datetime import datetime

def verify_kospi_data():
    loader = DataLoader()
    
    print("--- Checking KOSPI (Yahoo Finance: ^KS11) ---")
    kospi_yf = loader.get_market_history("KOSPI", period="1y")
    if kospi_yf is not None and not kospi_yf.empty:
        print(f"Latest KOSPI Price: {kospi_yf['Close'].iloc[-1]:.2f}")
        print(f"Latest Date: {kospi_yf.index[-1]}")
        print(f"Data Points: {len(kospi_yf)}")
    else:
        print("FAILED to load KOSPI from Yahoo Finance.")

    print("\n--- Checking KOSDAQ (Yahoo Finance: ^KQ11) ---")
    kosdaq_yf = loader.get_market_history("KOSDAQ", period="1y")
    if kosdaq_yf is not None and not kosdaq_yf.empty:
        print(f"Latest KOSDAQ Price: {kosdaq_yf['Close'].iloc[-1]:.2f}")
        print(f"Latest Date: {kosdaq_yf.index[-1]}")
    else:
        print("FAILED to load KOSDAQ from Yahoo Finance.")

    print("\n--- Checking KOSPI 200 Fundamentals (pykrx) ---")
    try:
        # Get first few tickers to test
        tickers = ["005930.KS", "000660.KS"]
        df_fundamentals = loader.get_stock_fundamentals(tickers=tickers, market_name="kr")
        if not df_fundamentals.empty:
            print("Successfully loaded fundamentals via pykrx:")
            print(df_fundamentals[['Ticker', 'Name', 'PER', 'PBR']].to_string())
        else:
            print("FAILED to load fundamentals via pykrx.")
    except Exception as e:
        print(f"EXCEPTION during pykrx fundamental check: {e}")

if __name__ == "__main__":
    verify_kospi_data()
