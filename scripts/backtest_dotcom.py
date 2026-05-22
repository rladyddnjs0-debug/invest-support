import pandas as pd
import yfinance as yf
import numpy as np
from modules.lppl_engine import LPPLEngine
from datetime import datetime
import matplotlib.pyplot as plt

def run_dotcom_backtest():
    ticker = "^IXIC"
    print(f"Downloading historical data for {ticker} (1995-2002)...")
    # Fetching extra data for MA200 calculation
    data = yf.download(ticker, start="1994-01-01", end="2002-12-31")['Close']
    if isinstance(data, pd.DataFrame):
        data = data.iloc[:, 0]
        
    engine = LPPLEngine(num_iterations=50) # Use 50 for speed in backtest
    
    results = []
    # Test every 10 trading days from 1998 to mid-2001
    test_dates = data.loc['1998-01-01':'2001-06-01'].index[::10]
    
    print(f"Starting rolling analysis across {len(test_dates)} points...")
    
    for date in test_dates:
        # Use data up to the test date
        current_data = data.loc[:date]
        if len(current_data) < 500: continue
        
        # Run analysis
        score, details = engine.calculate_risk_indicator(current_data)
        
        results.append({
            'Date': date,
            'Price': data.loc[date],
            'RiskScore': score,
            'Regime': details.get('regime', 0),
            'Fit': details.get('fit', 0),
            'PeakTc': details.get('peak_tc', 0)
        })
        
        if score > 50:
            tc_date = current_data.index[0] + pd.Timedelta(days=int(details['peak_tc']))
            print(f"[{date.date()}] Risk: {score:.1f} | Price: {data.loc[date]:.1f} | Predicted Tc: {tc_date.date()}")

    df_res = pd.DataFrame(results)
    df_res.to_csv("dotcom_backtest_results.csv", index=False)
    
    # Simple Plotting
    fig, ax1 = plt.subplots(figsize=(12, 6))
    ax1.plot(df_res['Date'], df_res['Price'], color='black', label='NASDAQ Price')
    ax1.set_ylabel('Price')
    
    ax2 = ax1.twinx()
    ax2.fill_between(df_res['Date'], 0, df_res['RiskScore'], color='red', alpha=0.3, label='LPPL Risk Score')
    ax2.set_ylabel('Risk Score (0-100)')
    ax2.set_ylim(0, 100)
    
    plt.title("Dot-com Bubble LPPL Backtest (1998-2001)")
    plt.savefig("dotcom_backtest.png")
    print("Backtest complete. Results saved to 'dotcom_backtest_results.csv' and 'dotcom_backtest.png'")

if __name__ == "__main__":
    run_dotcom_backtest()
