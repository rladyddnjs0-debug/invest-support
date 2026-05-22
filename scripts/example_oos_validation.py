import pandas as pd
import yfinance as yf
import numpy as np
from modules.lppl_engine import LPPLEngine

def walk_forward_validation(ticker="^GSPC", train_window=750, step=60, min_history=1000):
    """
    Out-of-Sample Walk-Forward Validation for LPPL.
    Trains on historical windows and checks predictive accuracy.
    """
    print(f"Downloading {ticker} data...")
    data = yf.download(ticker, period="10y")['Close']
    if isinstance(data, pd.DataFrame):
        data = data.iloc[:, 0]
        
    engine = LPPLEngine(num_iterations=50)
    
    hits = 0
    false_positives = 0
    total_signals = 0
    
    # We step through history
    for i in range(min_history, len(data) - 60, step):
        # 1. Train Window (In-Sample)
        train_data = data.iloc[i-train_window:i]
        test_data = data.iloc[i:i+60] # Next 60 days
        
        rolling_results = engine.run_rolling_analysis(train_data)
        score, msg = engine.calculate_bubble_score(rolling_results)
        
        # 2. If a signal is generated
        if score > 0.6: # High Risk
            total_signals += 1
            print(f"Signal detected at {train_data.index[-1].date()} (Score: {score:.2f})")
            
            # 3. Evaluate Out-of-Sample (OOS)
            # Did the market crash in the next 60 days? (e.g. > 10% drop from peak)
            max_price = test_data.max()
            min_after_max = test_data.loc[test_data.idxmax():].min()
            drawdown = (max_price - min_after_max) / max_price
            
            if drawdown > 0.10:
                hits += 1
                print(f"  -> HIT! Market dropped {drawdown*100:.1f}% in OOS.")
            else:
                false_positives += 1
                print(f"  -> FALSE POSITIVE. No significant drop.")
                
    print("\n--- Validation Summary ---")
    print(f"Total Signals: {total_signals}")
    print(f"Hits: {hits}")
    print(f"False Positives: {false_positives}")
    if total_signals > 0:
        print(f"Hit Rate: {hits/total_signals*100:.1f}%")

if __name__ == "__main__":
    walk_forward_validation()
