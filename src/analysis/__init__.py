"""
Analysis layer — completely independent of the backtest engine.

All functions accept raw data (pd.Series / pd.DataFrame) and return plain dicts
or DataFrames.  They can be called from scripts, notebooks, or Streamlit without
importing anything from backtest/, strategy/, or data/.
"""
