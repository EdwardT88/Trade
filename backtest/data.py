"""Load HistData.com XAUUSD M1 ASCII exports and convert to a clean UTC OHLC frame.

HistData ASCII timestamps are Eastern Standard Time *without* daylight saving,
i.e. a fixed UTC-5 offset. Prices are bid.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

HISTDATA_UTC_OFFSET = pd.Timedelta(hours=5)
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PARQUET = REPO_ROOT / "data" / "xauusd_m1.parquet"


def _read_histdata_csv(fh) -> pd.DataFrame:
    df = pd.read_csv(
        fh,
        sep=";",
        header=None,
        names=["ts", "open", "high", "low", "close", "volume"],
        dtype={"ts": str},
    )
    idx = pd.to_datetime(df["ts"], format="%Y%m%d %H%M%S") + HISTDATA_UTC_OFFSET
    out = df[["open", "high", "low", "close"]].astype("float64")
    out.index = pd.DatetimeIndex(idx, name="time").tz_localize("UTC").as_unit("ns")
    return out


def load_histdata(paths: list[Path]) -> pd.DataFrame:
    """Read HistData .zip or .csv files, merge, de-duplicate and sort."""
    frames = []
    for p in sorted(paths):
        p = Path(p)
        if p.suffix == ".zip":
            with zipfile.ZipFile(p) as z:
                name = next(n for n in z.namelist() if n.endswith(".csv"))
                with z.open(name) as fh:
                    frames.append(_read_histdata_csv(io.TextIOWrapper(fh)))
        else:
            frames.append(_read_histdata_csv(p))
    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="first")].sort_index()
    bad = (df["high"] < df[["open", "close"]].max(axis=1)) | (df["low"] > df[["open", "close"]].min(axis=1))
    df = df[~bad]
    return df


def load_m1(path: Path = DEFAULT_PARQUET, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df.index = df.index.as_unit("ns")
    if start is not None:
        df = df[df.index >= pd.Timestamp(start, tz="UTC")]
    if end is not None:
        df = df[df.index < pd.Timestamp(end, tz="UTC")]
    return df


def resample(m1: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample M1 to a higher timeframe. Bars are labelled by their open time (MT5 convention)."""
    agg = m1.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    )
    agg = agg.dropna()
    agg.index = agg.index.as_unit("ns")
    return agg


def to_arrays(df: pd.DataFrame) -> dict[str, np.ndarray]:
    return {
        "time": df.index.as_unit("ns").asi8,  # ns since epoch, UTC
        "open": df["open"].to_numpy(),
        "high": df["high"].to_numpy(),
        "low": df["low"].to_numpy(),
        "close": df["close"].to_numpy(),
    }
