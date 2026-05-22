import sys
import os
import argparse
from datetime import datetime, timedelta
import pandas as pd

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.data_loader import DataLoader
from modules.models import AnalysisModel

def run_historical_snapshot(event_name):
    loader = DataLoader()
    model = AnalysisModel()
    
    events = {
        "covid-19": "2020-03-20",
        "lehman-crisis": "2008-09-15",
        "rate-hike-2022": "2022-06-15"
    }
    
    if event_name not in events:
        print(f"Unknown event: {event_name}. Available: {list(events.keys())}")
        return

    target_date = datetime.strptime(events[event_name], "%Y-%m-%d")
    print(f"--- Running Snapshot Test: {event_name} ({target_date.date()}) ---")
    
    # Fetch historical data (using 2-year window up to target_date)
    start_date = (target_date - timedelta(days=730)).strftime("%Y-%m-%d")
    end_date = target_date.strftime("%Y-%m-%d")
    
    # Example: S&P 500
    try:
        data = loader.get_market_history("S&P500", period="max") 
        if data is not None:
            hist_data = data.loc[:target_date].tail(500)
            print(f"DEBUG: Data length: {len(data)}")
            print(f"DEBUG: Hist data length up to {target_date.date()}: {len(hist_data)}")
            
            # 1. Market Attractiveness
            res = model.calculate_attractiveness(hist_data['Close'], spread_df=None)
            if res is None:
                print("DEBUG: calculate_attractiveness returned None")
            print(f"\n[Market Attractiveness]")
            print(f"Score: {res['score']}")
            print(f"Regime: {res['regime']}")
            print(f"Action: {res['action']}")
            
            # 2. LPPL Risk
            print(f"\n[LPPL Risk Indicator]")
            lppl_res = model.run_lppl_fit(hist_data['Close'], num_iterations=50)
            if lppl_res:
                print(f"Danger Score: {lppl_res['danger_score']}")
                print(f"Is Bubble: {lppl_res['is_bubble']}")
            else:
                print("No LPPL pattern detected.")
                
    except Exception as e:
        print(f"Error during snapshot test: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Historical Snapshot Tester")
    parser.add_argument("--event", type=str, required=True, help="Event name (e.g., covid-19)")
    args = parser.parse_args()
    
    run_historical_snapshot(args.event)
