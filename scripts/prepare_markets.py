"""Build multi-market parquet files (true UTC) for research beyond XAUUSD.

Sources (public GitHub repos, cloned with git):
- ejtraderLabs/historical-data: FX majors M15 (and XAUUSD H1/H4) 2012-11 .. 2022-03. Prices are integers
  scaled by 10**digits; timestamps are broker server time = New York wall time + 7 h (GMT+2/+3),
  verified with NFP releases at 15:30 server time in winter and summer.
- getdata-finance/<sym>-1m-ohlcv-*-historical-data: 1-minute samples 2026-03-26 .. 2026-09-25, UTC.

Usage:
    git clone --depth 1 https://github.com/ejtraderLabs/historical-data.git /tmp/ej
    git clone --depth 1 https://github.com/getdata-finance/eurusd-1m-ohlcv-forex-historical-data.git /tmp/gd/eurusd
    ...
    python scripts/prepare_markets.py --ej /tmp/ej --gd /tmp/gd
Writes data/markets/<SYM>_<tf>.parquet with columns open/high/low/close and a UTC index.
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.data import resample  # noqa: E402

OUT = ROOT / "data" / "markets"
DIGITS = {"AUDJPY": 3, "EURJPY": 3, "GBPJPY": 3, "USDJPY": 3, "XAUUSD": 2}  # others: 5


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df[~df.index.isna()]
    df = df[~df.index.duplicated(keep="first")].sort_index()
    bad = (df["high"] < df[["open", "close"]].max(axis=1)) | (df["low"] > df[["open", "close"]].min(axis=1))
    return df[~bad]


def load_ej(path: Path, sym: str) -> pd.DataFrame:
    raw = pd.read_csv(path, parse_dates=["Date"])
    scale = 10 ** DIGITS.get(sym, 5)
    ny_wall = pd.DatetimeIndex(raw["Date"]) - pd.Timedelta(hours=7)
    utc = ny_wall.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT").tz_convert("UTC").as_unit("ns")
    df = raw[["open", "high", "low", "close"]].astype(float) / scale
    df.index = utc
    return _clean(df)


def load_gd(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    idx = pd.DatetimeIndex(pd.to_datetime(raw["datetime"], utc=True)).as_unit("ns")
    df = raw[["open", "high", "low", "close"]].astype(float)
    df.index = idx
    return _clean(df)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ej", type=Path, required=True)
    ap.add_argument("--gd", type=Path, required=True, help="folder holding the cloned getdata-finance repos")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for d in sorted(p for p in a.ej.iterdir() if p.is_dir() and not p.name.startswith(".")):
        sym = d.name
        for tf in ("m15", "h1"):
            f = d / f"{sym}{tf}.csv"
            if f.exists() and (tf == "m15" or sym == "XAUUSD"):
                df = load_ej(f, sym)
                df.to_parquet(OUT / f"{sym}_{tf}_2012_2022.parquet")
                print(f"{sym} {tf}: {len(df):,} bars {df.index[0]} -> {df.index[-1]}")
    for csv in sorted(a.gd.glob("*/*_1m.csv")):
        sym = csv.name.split("_")[0].upper()
        df = load_gd(csv)
        df.to_parquet(OUT / f"{sym}_m1_2026.parquet")
        resample(df, "15min").to_parquet(OUT / f"{sym}_m15_2026.parquet")
        print(f"{sym} 2026 m1: {len(df):,} bars {df.index[0]} -> {df.index[-1]}")


if __name__ == "__main__":
    main()
