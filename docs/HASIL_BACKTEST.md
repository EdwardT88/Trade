# Hasil riset & backtest (XAUUSD, akun cent $50)

> ⚠️ **UPDATE PENTING (Oktober 2026): edge strategi ini TIDAK terbukti dalam jangka panjang.**
> Setelah dapet data tambahan, strategi yang sama (tanpa diubah) dites ulang:
>
> | Periode | Gold, rata-rata per trade |
> |---|---|
> | 2013–2015 (gold bear) | +0.05R (132 trade) |
> | 2016–2019 | +0.03R (181 trade) |
> | 2020–Mar 2022 | −0.09R (96 trade) |
> | 2022–2025 (data utama di bawah) | +0.31R (174 trade) |
> | **Mei–Sep 2026 (data terbaru)** | **−0.37R (18 trade), akun $50 → $44.9** |
>
> Di 11 pair FX hasilnya rata-rata minus juga. Kesimpulannya: profit 2022–2025 sebagian besar dari **bull market gold**, bukan
> keunggulan strategi. **Jangan anggap EA ini mesin profit.** Kalau mau tetap dipakai, perlakukan sebagai eksperimen:
> demo dulu, risk 1%, uang yang siap hilang. Script cek ulang: `scripts/cross_market_check.py`.

## TL;DR
- **Scalping gold (M1–M15) nggak punya edge setelah spread.** Lima gaya scalping dites dengan rapi, dan semuanya ±0R sebelum biaya.
  Setelah spread, semuanya minus, dan di 2025 semuanya rugi 13–22%.
- **Yang lolos: swing trend-pullback** (arah dari H4, entry di H1, tahan 1–5 hari, flat tiap Jumat).
  Positif di 2022–23, 2024, dan di **2025 yang disimpan sebagai ujian akhir** (+28% di akun $50, drawdown maks 9.9%).
- Jadi EA-nya **bukan scalper**. Trade-nya jarang (±4 per bulan), tapi tiap trade punya peluang menang yang masuk akal.
  "Dikit-dikit jadi bukit"-nya datang dari konsistensi, bukan dari banyaknya trade.

## Cara ngetes (biar hasilnya bisa dipercaya)
- Data: XAUUSD M1 2022–2025 (HistData), dikonversi ke UTC dan dicek pakai jam rilis NFP.
- Mesin backtest sendiri (`backtest/engine.py`) dengan aturan konservatif:
  - Entry di bar M1 berikutnya. Spread kena di entry (buy) atau exit (sell).
  - Kalau SL dan TP kena di bar yang sama, dianggap SL duluan.
  - Gap harga di-fill di harga open bar berikutnya.
  - Swap 5%/tahun dihitung tiap malam (×3 tiap Rabu).
- Mesinnya dites: entry acak tanpa biaya hasilnya ≈ 0R (nggak bias), plus 13 unit test.
- Biaya default: spread = max($0.25, 0.8 bps harga). Di harga $4.300 itu sekitar $0.34, mirip spread HFM Cent.
  Ada juga skenario stress: spread $0.40 / 1.2 bps, slippage $0.10, swap 8%.
- Protokol anti-overfitting:
  1. Strategi dikembangkan di 2022–2023.
  2. Divalidasi sekali di 2024.
  3. **Data 2025 disembunyikan** dari semua agen riset. Aturan lulus/gagal ditulis dan di-commit **sebelum** 2025 dibuka
     (`results/HOLDOUT_PLAN.md`).

## Hasil scalping (semua NGGAK layak)
| Gaya | Edge sebelum biaya | Setelah biaya (2024) | Akun $50 di 2025 |
|---|---|---|---|
| Trend pullback M5 | +0.03R | −0.04R | −15.0% |
| Opening range breakout | ≈0 | −0.16R di 2025 | −22.3% |
| Asian range (breakout/fade) | ≈0 | −0.05R (stress) | −16.5% |
| Mean reversion (Bollinger/RSI) | ≈0 | −0.12R | −12.7% |
| Momentum breakout M1/M5 | ≈0 | −0.01R | −13.9% |

Penyebabnya: di horizon menit, gerak gold hampir acak. Spread ~$0.35 dengan SL $3–5 itu sama dengan
7–12% dari risk di **setiap** trade. Pakai broker spread paling tipis pun hasilnya tetap minus.

## Strategi terpilih: `swing_pullback`
**Aturan:**
- **Trend (H4):** close bar H4 terakhir di atas EMA(40), dan EMA(40) lebih tinggi dari 6 bar sebelumnya → cuma cari BUY.
  Kebalikannya → cuma cari SELL.
- **Entry (H1):** RSI(14) balik naik nembus 40 (buy) atau balik turun nembus 60 (sell). Masuk di awal bar H1 berikutnya.
- **Stop:** 2 × ATR(14) H4. Lot dihitung supaya kena SL = −2% equity.
- **Trailing:** 3 × ATR, mulai ngunci profit setelah harga jalan +1 ATR.
- **Tutup semua tiap Jumat 20:00 UTC** (Sabtu 03:00 WIB), jadi nggak ada risiko gap weekend.
- Nggak entry jam 21:00–24:00 UTC (rollover), dan nggak entry Jumat setelah 12:00 UTC.

| Periode | Trade | Win rate | Rata-rata | Profit factor | Akun $50 | DD maks | Bulan profit |
|---|---|---|---|---|---|---|---|
| 2022–2023 (dev) | 74 | 53% | +0.42R | 2.29 | $50 → $87 | 8.4% | 62% |
| 2024 (validasi) | 47 | 36% | +0.21R | 1.41 | $50 → $59 | 8.7% | 42% |
| **2025 (ujian akhir)** | **53** | **58%** | **+0.26R** | **1.92** | **$50 → $64** | **9.9%** | **67%** |

Grafik equity: `results/swing_pullback/equity.png`. Daftar trade: `results/swing_pullback/trades_*.csv`.

**Monte Carlo 6 bulan** (pakai distribusi trade 2025, 5.000 simulasi):
- Peluang nyentuh hard stop (−30%): **0%**
- Peluang profit: 86%
- Median saldo $56.8 (+14%). 5% terburuk $47.2, 5% terbaik $69.7.
- Drawdown maks (95% kasus) ≤ 11.8%

**Skenario stress** (spread lebih lebar + swap 8%): rata-rata tetap positif (+0.39 / +0.18 / +0.23R).

## Pilihan durasi trade (default EA: maks 3 hari)
Strategi yang sama, cuma batas lama posisinya yang beda (akun $50, spread + swap 5%):

| Batas lama posisi | 2022–23 | 2024 | 2025 | Rata-rata tahan | Paling lama |
|---|---|---|---|---|---|
| Sampai Jumat (versi ujian) | $87.0 | $59.1 | $63.9 | 42 jam | ~5 hari |
| **Maks 72 jam (default EA)** | **$87.3** | **$57.6** | **$64.4** | **38 jam** | **3 hari** |
| Maks 48 jam | $79.4 | $51.5 | $60.1 | 32 jam | 2 hari |
| Maks 36 jam | $68.1 | $51.4 | $60.3 | 27 jam | 1,5 hari |
| Maks 24 jam | $60.8 | $44.4 | $57.5 | 20 jam | 1 hari |
| Scalping M5, maks 2 jam | $34.9 (hard stop) | $37.0 | $54.5 | 2 jam | 2 jam |

Batas 72 jam dipilih **setelah** lihat semua data (bukan bagian dari ujian 2025), tapi efeknya kecil: cuma motong
trade terpanjang, profitnya hampir sama di ketiga periode. Pasang take-profit (1.5R/2R/3R) nggak bikin lebih baik.

## Yang harus lu tahu (jujur)
- **Buktinya "lumayan", bukan "pasti".** Gabungan 2022–2025: 174 trade, rata-rata +0.31R, t ≈ 3.1
  (sudah termasuk periode pengembangan). Di 2025 aja t ≈ 1.7.
- **Profit didominasi posisi BUY.** SELL rugi di 2024 (−0.52R) dan 2025 (−0.13R), dua tahun bull gold.
  Kalau gold masuk fase turun panjang, performa bisa jauh lebih jelek dari tabel di atas.
  Ada opsi `InpSides = Long only`, tapi itu taruhan tambahan bahwa gold terus naik.
- **Trade-nya jarang:** ±3–4 per bulan, dan ada bulan yang rugi. Pertumbuhan realistis kira-kira **+1–2% per bulan rata-rata**,
  bukan per hari.
- **Hasil live pasti beda dikit:** spread broker, slippage, bar H4 yang ngikut jam server (udah dites geser 2 jam, hasilnya mirip),
  filter news (nggak ada di backtest).

## Reproduksi
```bash
pip install -r requirements.txt
git clone --depth 1 https://github.com/Motasim-1/data-xauusd-2025-input.git /tmp/xau
python scripts/prepare_data.py /tmp/xau/*.zip
python scripts/report.py swing_pullback --out results/swing_pullback
python -m pytest -q tests
```
