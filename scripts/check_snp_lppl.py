import pandas as pd
import yfinance as yf
from modules.models import AnalysisModel
from datetime import datetime

model = AnalysisModel()
ticker = "^GSPC"
print(f"Downloading {ticker}...")
data = yf.download(ticker, period="2y", interval="1d", progress=False)['Close']
if isinstance(data, pd.DataFrame):
    data = data.iloc[:, 0]

print(f"Latest Price: {data.iloc[-1]:.2f} (Date: {data.index[-1]})")

res = model.run_lppl_fit(data)
if res:
    print(f"Danger Score: {res['danger_score']}")
    print(f"Tc Date: {res['tc_date']}")
    print(f"R-squared: {res['r_squared']:.4f}")
else:
    print("No LPPL signal detected.")
