# Panduan GoldScalperCent (MT5, akun cent, XAUUSD)

Panduan ini buat pasang dan jalanin EA `mql5/GoldScalperCent.mq5` di akun **cent** MT5 dengan modal $50 (5.000 USC).

> **Penting:** ini software trading otomatis, bukan jaminan profit. Hasil backtest di repo ini pakai data historis
> 2022–2025 dan biaya yang diasumsikan. Pasar ke depan bisa beda. Jalanin dulu di **demo minimal 2 minggu**.

---

## 1. Cara kerja EA (singkat)

<!--STRATEGY_SUMMARY-->

### Aturan anti-MC (selalu aktif)

| Aturan | Default | Artinya |
|---|---|---|
| Risk per trade | 2% equity | Lot dihitung otomatis dari jarak SL. Kena SL = rugi ±2%. |
| Risk saat drawdown | 1% | Kalau equity turun 10% dari puncak, risk jadi 1% sampai cetak puncak baru. |
| Skip kalau lot minimum kegedean | 3% | Kalau 0.01 lot aja udah risk >3%, trade nggak diambil. |
| Stop harian | -5% | Rugi 5% dalam sehari → stop sampai besok (UTC). |
| Loss beruntun | 3x | Kalah 3x berturut-turut di hari yang sama → stop sampai besok. |
| Max trade per hari | 8 | |
| **Hard stop** | -30% dari saldo awal | Equity nyentuh $35 (3.500 USC) → semua posisi ditutup dan EA **berhenti total** sampai lu review. |
| Tutup sebelum rollover | 21:00 UTC (04:00 WIB) | Nggak bawa posisi lewat jam spread melebar, nggak nginep weekend. |
| Filter news | ±30 menit | Nggak entry di sekitar news merah USD (NFP, CPI, FOMC). Pakai kalender bawaan MT5, cuma aktif di live/demo. |
| Filter spread | 15% dari SL | Kalau spread lagi lebar, entry di-skip. |

Nggak ada martingale, grid, averaging, atau posisi tanpa SL.

---

## 2. Persiapan akun

1. Buka akun **cent** di MT5 (lihat rekomendasi broker di `docs/BROKER.md`). Simbol gold di akun cent biasanya pakai akhiran `c`, contoh **`XAUUSDc`**.
2. Deposit $50 → di MT5 kelihatan **5000** (satuannya sen/USC).
3. Cek spesifikasi simbol: klik kanan `XAUUSDc` di Market Watch → **Specification**. Catat:
   - *Contract size*, *Minimal volume* (harus 0.01), *Volume step* (0.01)
   - *Stops level* (sebaiknya 0 atau kecil)
   - *Filling* (EA otomatis menyesuaikan)

## 3. Pasang EA

1. Di MT5: **File → Open Data Folder** → buka folder `MQL5/Experts/`.
2. Copy file `GoldScalperCent.mq5` ke situ.
3. Buka **MetaEditor** (F4 dari MT5), buka file itu, tekan **F7 (Compile)**. Harus "0 errors".
   Kalau ada error, copy pesan errornya ke gua, nanti gua benerin.
4. Balik ke MT5, refresh Navigator → **Expert Advisors → GoldScalperCent**.
5. Buka chart **XAUUSDc**, timeframe bebas (EA baca timeframe sendiri), drag EA ke chart.
6. Tab **Common**: centang *Allow Algo Trading*. Tombol **Algo Trading** di toolbar harus hijau.

### Setting yang WAJIB dicek: zona waktu server

Semua jam di EA pakai UTC, jadi EA perlu tahu jam server broker:

| Broker | `InpServerTZ` | `InpFixedOffsetHours` |
|---|---|---|
| Exness (server GMT+0) | `Fixed offset` | `0` |
| HFM, RoboForex, FBS, kebanyakan broker lain (GMT+2/+3) | `GMT+2 / GMT+3 with US DST` | (diabaikan) |
| Nggak yakin | `Auto` (live) | isi sesuai broker buat Strategy Tester |

Cek di panel kiri atas chart: baris `UTC hh:mm` harus sama dengan jam UTC sekarang (= WIB − 7 jam).

## 4. Backtest di MT5 (Strategy Tester)

1. **View → Strategy Tester** (Ctrl+R).
2. Expert: GoldScalperCent, Symbol: XAUUSDc, Modeling: **Every tick based on real ticks**.
3. Deposit: 5000 (USC) kalau akunnya cent. Leverage sesuai akun.
4. Periode: mulai dari 2025-01-01 sampai sekarang.
5. Set `InpServerTZ` = `Fixed offset` dan `InpFixedOffsetHours` sesuai broker (di tester mode Auto nggak bisa baca jam GMT).
6. Bandingin hasilnya sama hasil backtest Python di `docs/HASIL_BACKTEST.md`. Beda dikit itu normal (spread & data broker beda), tapi arah dan ukuran drawdown harusnya mirip.

## 5. Demo dulu, baru live

- Jalanin di **akun demo cent** minimal 2 minggu (atau ±40 trade).
- Lolos kalau: nggak ada error eksekusi di tab *Experts/Journal*, lot sesuai (risk ±2%), drawdown masih masuk akal.
- Baru pindah ke live $50 dengan setting yang sama.
- EA harus nyala terus Senin–Jumat → pakai **VPS** (banyak broker kasih gratis kalau saldo/volume tertentu) atau PC yang nggak dimatiin.

## 6. Kalau EA "HALTED"

Artinya equity udah turun 30% dari saldo awal. EA nutup semua posisi dan berhenti. Jangan langsung dinyalain lagi:

1. Cek log (tab *Experts*) dan file CSV di `File → Open Data Folder → ../Common/Files/GoldScalperCent_<login>.csv`.
2. Diskusiin dulu sama gua: apa pasar lagi beda banget, apa ada masalah eksekusi/spread.
3. Kalau mau lanjut: set `InpResetHalt = true`, OK, terus balikin ke `false`. Kalau mau saldo awal baru buat hard stop, isi `InpStartBalance`.

## 7. Input penting

<!--STRATEGY_INPUTS_TABLE-->

| Input | Default | Keterangan |
|---|---|---|
| `InpRiskPct` | 2.0 | Risk per trade (%). Minimal 1%, maksimal yang gua sarankan 3%. |
| `InpReducedRiskPct` | 1.0 | Risk waktu drawdown. |
| `InpDDReducePct` | 10 | Batas drawdown buat turunin risk. |
| `InpDailyLossPct` | 5 | Stop harian. |
| `InpMaxConsecLosses` | 3 | Stop setelah kalah beruntun. |
| `InpHardStopPct` | 30 | Hard stop dari saldo awal. |
| `InpMaxSpreadPctOfSL` | 15 | Filter spread. |
| `InpUseNewsFilter` | true | Filter news merah USD. |
| `InpMagic` | 20261021 | Ganti kalau pasang lebih dari satu EA. |
