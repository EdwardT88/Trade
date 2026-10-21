"""Build data/xauusd_m1.parquet from HistData XAUUSD M1 yearly zips.

Usage:
    git clone --depth 1 https://github.com/Motasim-1/data-xauusd-2025-input.git /tmp/xau
    python scripts/prepare_data.py /tmp/xau/*.zip
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.data import DEFAULT_PARQUET, load_histdata  # noqa: E402


def main(argv: list[str]) -> None:
    if not argv:
        raise SystemExit(__doc__)
    df = load_histdata([Path(a) for a in argv])
    DEFAULT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(DEFAULT_PARQUET)
    print(f"wrote {len(df):,} bars {df.index[0]} -> {df.index[-1]} to {DEFAULT_PARQUET}")


if __name__ == "__main__":
    main(sys.argv[1:])
