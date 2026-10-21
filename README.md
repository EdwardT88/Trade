# Trade — XAUUSD EA untuk akun cent $50

MT5 Expert Advisor + riset backtest buat trading gold (XAUUSD) di akun **cent** dengan modal kecil.
Tujuannya dua: **nggak margin call** dan **akun tumbuh pelan-pelan**.

- **EA:** `mql5/GoldSwingCent.mq5`. Swing trend-pullback (arah H4, entry H1, SL 2×ATR, trailing 3×ATR, flat tiap Jumat)
  dengan aturan anti-MC yang ketat.
- **Panduan setup:** [`docs/PANDUAN.md`](docs/PANDUAN.md)
- **Hasil riset & backtest:** [`docs/HASIL_BACKTEST.md`](docs/HASIL_BACKTEST.md) (scalping vs swing, ujian 2025)
- **Rekomendasi broker:** [`docs/BROKER.md`](docs/BROKER.md)

## Struktur
```
backtest/      mesin backtest M1 (spread, swap, risk manager akun cent), indikator ala MT5, metrik, Monte Carlo
strategies/    semua strategi yang dites (5 scalping, 3 swing); swing_pullback = yang dipakai EA
scripts/       prepare_data.py, evaluate.py, report.py
results/       ringkasan, daftar trade, grafik equity, aturan & hasil holdout 2025
tests/         unit test mesin backtest
mql5/          EA MetaTrader 5
docs/          panduan, hasil, broker (Bahasa Indonesia)
```

## Jalanin riset ulang
```bash
pip install -r requirements.txt
git clone --depth 1 https://github.com/Motasim-1/data-xauusd-2025-input.git /tmp/xau
python scripts/prepare_data.py /tmp/xau/*.zip
python -m pytest -q tests
python scripts/report.py swing_pullback
```
