import numpy as np
import pandas as pd
from modules.models import AnalysisModel
from datetime import datetime, timedelta

def test_lppl_robust():
    model = AnalysisModel()
    
    # 1. Generate Synthetic Bubble Data
    # y = A + B(tc-t)^m * (1 + C cos(omega ln(tc-t) + phi))
    tc = 500
    m = 0.5
    omega = 10
    A = 10
    B = -1
    C = 0.5
    phi = 0
    
    t = np.arange(0, 400)
    dt = tc - t
    y_log = A + B * (dt**m) * (1 + C * np.cos(omega * np.log(dt) + phi))
    prices = np.exp(y_log)
    
    dates = [datetime(2020, 1, 1) + timedelta(days=int(i)) for i in t]
    data = pd.Series(prices, index=dates)
    
    print("Running LPPL on synthetic bubble data...")
    result = model.run_lppl_fit(data)
    
    if result:
        print("\n--- LPPL Analysis Result (Synthetic) ---")
        print(f"Predicted Tc Date: {result['tc_date']}")
        print(f"Confidence Score: {result['confidence_score']:.4f}")
        print(f"R-squared: {result['r_squared']:.4f}")
        
        # Verify tc is somewhat close to 500
        t_start = data.index[0]
        predicted_tc_days = (result['tc_date'] - t_start).days
        print(f"Actual Tc: 500, Predicted Tc: {predicted_tc_days}")
        
        assert 450 <= predicted_tc_days <= 600, "Tc prediction out of reasonable range"
        assert result['confidence_score'] > 0.1, "Confidence should be non-zero for synthetic bubble"
        print("\nTest Passed!")
    else:
        print("Fitting failed.")
        assert False, "Fitting should have succeeded on clean synthetic data"

if __name__ == "__main__":
    test_lppl_robust()
