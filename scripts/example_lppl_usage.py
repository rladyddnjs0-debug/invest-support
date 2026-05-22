import pandas as pd
import yfinance as yf
from modules.lppl_engine import LPPLEngine
import matplotlib.pyplot as plt

def main():
    # 1. Load Data
    ticker = "^GSPC" # S&P 500
    print(f"Downloading {ticker} data...")
    data = yf.download(ticker, period="5y")['Close']
    if isinstance(data, pd.DataFrame):
        data = data.iloc[:, 0]
        
    print(f"Latest Price: {data.iloc[-1]:.2f} (Date: {data.index[-1]})")

    # 2. Initialize Research-Grade LPPL Engine
    # num_iterations=100 for high precision (as requested)
    engine = LPPLEngine(num_iterations=100, window_sizes=[120, 250, 500])

    # 3. Run Rolling Analysis
    print("Running rolling LPPL analysis (multi-start, ensemble)...")
    rolling_results = engine.run_rolling_analysis(data)

    if not rolling_results:
        print("No valid LPPL signals found.")
        return

    # 4. Calculate Aggregate Bubble Score
    bubble_score = engine.calculate_bubble_score(rolling_results)

    print("\n--- LPPL Analysis Results ---")
    print(f"Overall Bubble Confidence Score: {bubble_score:.4f}")
    
    for res in rolling_results:
        win = res['window_size']
        best = res['best_fit']
        stab = res['stability']
        print(f"\n[Window Size: {win} days]")
        print(f"  - Predicted Tc: {stab['tc_mean']:.2f} (std: {stab['tc_std']:.2f})")
        print(f"  - Parameter m: {best['m']:.4f}")
        print(f"  - Parameter omega: {best['omega']:.4f}")
        print(f"  - Valid Fits in Ensemble: {stab['num_valid_fits']}/{engine.num_iterations}")
        print(f"  - Window Confidence: {stab['confidence']:.4f}")

    # 5. Visualization (if you have a display environment)
    # In a CLI environment, this might save to a file or require manual showing.
    print("\nGenerating visualization...")
    try:
        engine.plot_results(data, rolling_results, bubble_score)
        plt.savefig("lppl_analysis_result.png")
        print("Visualization saved as 'lppl_analysis_result.png'")
    except Exception as e:
        print(f"Could not generate plot: {e}")

if __name__ == "__main__":
    main()
