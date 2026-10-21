"""Load HistData.com XAUUSD M1 ASCII exports and convert to a clean UTC OHLC frame.

HistData documents its ASCII timestamps as EST without daylight saving, but the XAUUSD files
actually follow New York wall-clock time (EST/EDT): the 08:30 ET US data releases (e.g. NFP)
appear at 08:30 file time in both winter and summer, and the 17:00-18:00 ET daily break sits at
17:00 file time all year. Timestamps are therefore localized to America/New_York and converted to
UTC. Prices are bid.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

HISTDATA_TZ = "America/New_York"
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
    local = pd.DatetimeIndex(pd.to_datetime(df["ts"], format="%Y%m%d %H%M%S"), name="time")
    # gold is closed on Sunday morning when clocks change, so DST gaps/overlaps should not occur;
    # anything ambiguous is dropped rather than guessed
    utc = local.tz_localize(HISTDATA_TZ, ambiguous="NaT", nonexistent="NaT").tz_convert("UTC").as_unit("ns")
    out = df[["open", "high", "low", "close"]].astype("float64")
    out.index = utc
    return out[~out.index.isna()]


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
