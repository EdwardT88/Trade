# RiskGuardCent: penjaga akun buat trading manual

`mql5/RiskGuardCent.mq5` **nggak buka trade sendiri.** Lu tetap trading manual (dari PC, HP, atau panel EA ini),
dan EA ini jagain akun lu dari MC. Dia jalan di MT5 yang nyala terus (paling bagus di VPS).

> ⚠️ EA cuma bisa jaga selama MT5-nya nyala. Kalau PC/VPS mati, nggak ada yang ngawasin.
> Trade dari HP tetap kejaga **kalau** MT5 di VPS/PC-nya lagi jalan.

## Apa yang dijaga

| Aturan | Default | Yang terjadi kalau dilanggar |
|---|---|---|
| **SL wajib** | 30 detik | Posisi tanpa SL dikasih SL darurat di jarak risk maks (2%). Kalau nggak bisa, posisinya ditutup. |
| **Risk per posisi** | maks 2% | Lot kegedean → sebagian posisi ditutup sampai risk-nya 2%. Kalau nggak bisa, SL dirapetin. Kalau masih nggak bisa, posisi ditutup. |
| **Total risk terbuka** | maks 4% | Posisi baru yang bikin total risk lewat 4% langsung ditutup. |
| **Posisi bersamaan** | maks 2 | Posisi ke-3 langsung ditutup. |
| **Trade per hari** | maks 6 | Trade ke-7 langsung ditutup. |
| **Cooldown habis loss** | 15 menit | Posisi baru dalam 15 menit setelah loss langsung ditutup (anti balas dendam). |
| **Loss beruntun** | 3x | Kalah 3x berturut-turut → **dikunci sampai besok**. |
| **Rugi harian** | −5% | Rugi 5% (closed + floating) → semua posisi ditutup dan **dikunci sampai besok**. |
| **Hard stop** | −30% dari saldo awal | Semua ditutup, akun **HALTED** sampai lu reset manual. |

Waktu dikunci, setiap posisi baru yang lu buka bakal langsung ditutup EA.

## Panel (lot calculator 1 klik)

Panel muncul di kiri atas chart:

`[SL LINE] [BUY] [SELL] [CLOSE ALL] [risk %]`

1. Klik **SL LINE**. Muncul garis merah (SL) dan garis hijau putus-putus (TP = 2× jarak SL).
2. Geser garis merah ke level SL lu: **di bawah harga = BUY**, **di atas harga = SELL**. Garis TP ikut otomatis
   (atau geser sendiri).
3. Panel nunjukin lot, risk dalam USC dan %, jarak SL, dan TP.
4. Klik **BUY** atau **SELL**. Lot dihitung otomatis supaya kalau kena SL ruginya pas sesuai risk %.
5. Kotak **risk %** bisa diganti (misal 1.0 atau 1.5). Nggak bisa lebih dari risk maks (2%).
6. **CLOSE ALL** harus diklik dua kali dalam 5 detik (biar nggak kepencet).

Order dari panel dianggap trade manual, jadi tetap dijaga semua aturan di atas.

## Pasang

1. Copy `RiskGuardCent.mq5` ke `MQL5/Experts/`, compile (F7) di MetaEditor.
2. Pasang di **satu chart aja** (misal XAUUSDc). EA ngejaga semua simbol di akun (`InpGuardAllSymbols = true`).
   Jalanin cuma di **satu terminal** per akun: kalau udah di VPS, matiin EA ini di MT5 PC (dua guard bakal motong lot / geser SL dobel).
3. *Allow Algo Trading* harus nyala.
4. Kalau lu juga jalanin GoldSwingCent: biarin `InpManualOnly = true`. Posisi EA lain nggak diutak-atik satu-satu,
   tapi tetap dihitung di total risk, rugi harian, dan hard stop.

## Input penting

| Input | Default | Keterangan |
|---|---|---|
| `InpRiskPct` | 1.0 | Risk default tombol BUY/SELL (%). |
| `InpMaxRiskPerTradePct` | 2.0 | Risk maks per posisi. Lebih dari ini dipotong. |
| `InpMaxOpenRiskPct` | 4.0 | Total risk semua posisi terbuka. |
| `InpMaxPositions` | 2 | Posisi terbuka maksimal. |
| `InpNoSLAction` / `InpNoSLGraceSec` | SL darurat / 30 | Posisi tanpa SL: dikasih SL darurat atau ditutup. |
| `InpDailyLossPct` | 5.0 | Rugi harian sebelum dikunci. |
| `InpMaxTradesPerDay` | 6 | Trade baru per hari. |
| `InpMaxConsecLosses` | 3 | Loss beruntun sebelum dikunci. |
| `InpCooldownMin` | 15 | Menit jeda setelah loss (0 = mati). |
| `InpDayStartHourServer` | 0 | Jam server buat ganti hari. Exness (GMT+0): 0 = 07:00 WIB. |
| `InpHardStopPct` / `InpStartBalance` | 30 / 0 | Hard stop. Saldo awal **dalam USC** di akun cent (5000 = $50). |
| `InpResetHalt` | false | Buat buka HALT: set true sekali, OK, terus balikin false. |
| `InpFridayCloseAll` / `InpFridayCloseHourSrv` | false / 20 | Tutup semua posisi Jumat jam segini (jam server, opsional). Harus **sebelum** market tutup: Exness (GMT+0) tutup ±21:00 musim panas, 22:00 musim dingin. |

## Log

Setiap tindakan EA (SL darurat, potong lot, posisi ditolak, kunci harian) dicatat di tab *Experts* dan di file
`Common/Files/RiskGuard_<login>.log`. Panel juga nunjukin tindakan terakhir.
