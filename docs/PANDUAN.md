# Panduan GoldSwingCent (MT5, akun cent, XAUUSD)

Panduan pasang dan jalanin EA `mql5/GoldSwingCent.mq5` di akun **cent** MT5 dengan modal $50 (5.000 USC).

> **Penting:** ini software trading otomatis, bukan jaminan profit. Hasil backtest (`docs/HASIL_BACKTEST.md`) pakai
> data 2022–2025 dan biaya yang diasumsikan, dan pasar ke depan bisa beda. Jalanin dulu di **demo minimal 2–4 minggu**.

---

## 1. Cara kerja EA (singkat)

- **Arah dari H4:** close bar H4 terakhir di atas EMA(40) dan EMA-nya naik → cuma cari BUY. Kebalikannya → cuma SELL.
  Kalau nggak jelas, EA diam.
- **Entry di H1:** nunggu harga koreksi dulu. RSI(14) H1 turun di bawah 40, terus balik naik nembus 40 → BUY.
  Untuk SELL kebalikannya (nembus 60 ke bawah).
- **Stop loss:** 2 × ATR(14) H4. Lot dihitung otomatis supaya kalau kena SL ruginya 2% equity.
- **Trailing stop:** 3 × ATR. Mulai ngunci profit setelah harga jalan sekitar +1 ATR, nggak pernah mundur.
- **Tutup semua tiap Jumat 20:00 UTC** (Sabtu 03:00 WIB). Nggak bawa posisi lewat weekend.
- Nggak buka posisi baru jam 21:00–24:00 UTC (04:00–07:00 WIB, jam spread lebar) dan Jumat setelah 12:00 UTC.
- Satu posisi dalam satu waktu. Rata-rata ±4 trade per bulan, posisi biasanya ditahan 1–5 hari.

Jadi ini **swing**, bukan scalping. Scalping udah dites dan kalah sama spread (detail di `docs/HASIL_BACKTEST.md`).

### Aturan anti-MC (selalu aktif)

| Aturan | Default | Artinya |
|---|---|---|
| Risk per trade | 2% equity | Kena SL = rugi ±2%. |
| Risk saat drawdown | 1% | Equity turun 10% dari puncak → risk 1% sampai cetak puncak baru. |
| Skip kalau lot minimum kegedean | 3% | Kalau 0.01 lot aja udah risk >3%, trade nggak diambil. |
| Stop harian | −5% | Rugi 5% dalam sehari (UTC) → nggak buka posisi baru sampai besok. |
| Loss beruntun | 3x | Kalah 3x berturut-turut di hari yang sama → stop sampai besok. |
| **Hard stop** | −30% dari saldo awal | Equity nyentuh $35 (3.500 USC) → semua posisi ditutup dan EA **berhenti total** sampai lu review. |
| Margin | ≤ 50% free margin | Nggak pernah buka posisi yang makan lebih dari setengah free margin. |
| Filter spread | $1.00 / 10% SL | Spread lagi lebar → entry di-skip. |
| Filter news | ±15 menit | Nggak entry di sekitar news merah USD (kalender MT5, cuma aktif di live/demo). |

Nggak ada martingale, grid, averaging, atau posisi tanpa SL.

---

## 2. Persiapan akun

1. Buka akun **cent** di MT5 (lihat `docs/BROKER.md`). Simbol gold di akun cent biasanya **`XAUUSDc`**.
2. Leverage: **1:500 atau 1:1000** udah lebih dari cukup. Lot di EA ini kecil (±0.02–0.05 lot cent),
   jadi margin-nya cuma beberapa sen.
3. Deposit $50 → di MT5 kelihatan **5000** (USC).
4. Cek spesifikasi simbol: klik kanan `XAUUSDc` → **Specification**. Pastikan *Minimal volume* 0.01 dan *Volume step* 0.01.

## 3. Pasang EA

1. MT5: **File → Open Data Folder** → buka `MQL5/Experts/`, copy `GoldSwingCent.mq5` ke situ.
2. Buka **MetaEditor** (F4), buka file itu, tekan **F7 (Compile)**. Harus "0 errors".
   Kalau ada error, kirim pesan errornya ke gua, nanti gua benerin.
3. Balik ke MT5 → Navigator → **Expert Advisors → GoldSwingCent**.
4. Buka chart **XAUUSDc** (timeframe bebas, EA baca H4/H1/M1 sendiri), lalu drag EA ke chart.
5. Tab **Common**: centang *Allow Algo Trading*. Tombol **Algo Trading** di toolbar harus hijau.
6. Biarin chart kebuka. EA butuh MT5 nyala terus Senin–Jumat, jadi pakai **VPS** atau PC yang nggak dimatiin.

### WAJIB: zona waktu server

Semua jam di EA pakai UTC, jadi EA perlu tahu jam server broker:

| Broker | `InpServerTZ` | `InpFixedOffsetHours` |
|---|---|---|
| Exness (server GMT+0) | `Fixed offset` | `0` |
| HFM, kebanyakan broker lain (GMT+2/+3) | `GMT+2 / GMT+3 with US DST` | (diabaikan) |
| Nggak yakin | `Auto` | buat Strategy Tester isi sesuai broker |

Cek di panel kiri atas chart: `UTC hh:mm` harus sama dengan jam UTC sekarang (= jam WIB − 7).

## 4. Backtest di MT5 (Strategy Tester)

1. **View → Strategy Tester** (Ctrl+R). Expert: GoldSwingCent, Symbol: XAUUSDc.
2. Modeling: **Every tick based on real ticks** (atau "1 minute OHLC" biar lebih cepat).
3. Deposit **5000** (USC), leverage sesuai akun.
4. Periode: 2025-01-01 sampai sekarang.
5. Di tab Inputs: set `InpServerTZ = Fixed offset` dan `InpFixedOffsetHours` sesuai broker
   (Exness 0; HFM 2 buat musim dingin / 3 buat musim panas, ambil yang paling sering di periode tes).
   Di tester, mode Auto nggak bisa baca jam GMT.
6. Bandingin sama `docs/HASIL_BACKTEST.md`. Jumlah trade dan arah hasil harusnya mirip. Beda dikit itu normal
   (data/spread broker, bar H4 ngikut jam server).

## 5. Demo dulu, baru live

- Jalanin di **demo** (atau akun cent live dengan risk 1% dulu kalau broker nggak punya demo cent, misalnya Exness)
  selama 2–4 minggu.
- Lolos kalau: nggak ada error eksekusi di tab *Experts/Journal*, lot sesuai (risk ±2%), SL selalu kepasang, trailing jalan,
  dan posisi ketutup Jumat malam.
- Baru jalanin live $50 dengan setting yang sama.

## 6. Kalau EA "HALTED"

Artinya equity udah turun 30% dari saldo awal. EA nutup semua posisi dan berhenti. **Jangan langsung dinyalain lagi.**

1. Cek log (tab *Experts*) dan file CSV di `File → Open Data Folder → ../Common/Files/GoldSwingCent_<login>.csv`.
2. Diskusiin dulu: apa pasar lagi beda banget (misal gold lagi turun panjang), atau ada masalah eksekusi/spread.
3. Kalau mau lanjut: set `InpResetHalt = true`, klik OK, terus balikin ke `false`.
   Kalau mau pakai saldo awal baru buat hitungan hard stop, isi `InpStartBalance`.

## 7. Input penting

| Input | Default | Keterangan |
|---|---|---|
| `InpRiskPct` | 2.0 | Risk per trade (%). Minimal 1%, maksimal yang gua sarankan 3%. |
| `InpSides` | Long and short | `Long only` = cuma BUY (lebih bagus di 2024–2025, tapi itu taruhan gold terus naik). |
| `InpStopATR` / `InpTrailATR` | 2.0 / 3.0 | Jarak SL dan trailing (× ATR H4). Jangan diubah tanpa backtest ulang. |
| `InpTrendEMA` / `InpRsiLevel` | 40 / 40 | Parameter strategi hasil riset. |
| `InpFridayClose` | true | Tutup Jumat 20:00 UTC. |
| `InpReducedRiskPct` / `InpDDReducePct` | 1.0 / 10 | Risk turun waktu drawdown. |
| `InpDailyLossPct` / `InpMaxConsecLosses` | 5 / 3 | Rem harian. |
| `InpHardStopPct` | 30 | Hard stop dari saldo awal. |
| `InpServerTZ` / `InpFixedOffsetHours` | Auto / 0 | Zona waktu server (lihat tabel di atas). |
| `InpUseNewsFilter` | true | Filter news merah USD. |
| `InpMagic` | 20261021 | Ganti kalau pasang lebih dari satu EA di akun yang sama. |
