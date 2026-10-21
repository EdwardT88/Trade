# Rekomendasi broker: akun cent MT5 buat XAUUSD (Oktober 2026)

Ringkasan riset web (resmi broker + sumber pihak ketiga). Beberapa angka **nggak bisa diverifikasi live** dari sini,
jadi yang ditandai (\*) wajib lu cek sendiri di MT5 sebelum deposit/jalanin EA.

## Pilihan gua

### 1. HFM — akun **Cent** (paling cocok)
- Ada di **MT5**, simbol gold **`XAUUSDc`**. 0.01 lot = 0.01 oz, jadi gerak $1 di gold = 1 sen (USC).
- Halaman resmi HFM: EA, scalping, dan hedging **diizinkan**.
- Stop-out 20%, margin call 50% (\*). Minimal deposit $0.
- Spread gold di Cent sekitar **$0.34–0.36** jam normal (bacaan live dari pengguna MT5 Agustus 2026; iklan resminya "from 0.32").
- Catatan teknis buat EA: filling **FOK only**, stops level 0, freeze level 8 point (\*). Jam server = WIB − 4 jam
  (GMT+2/+3), jadi di EA pakai `InpServerTZ = GMT+2 / GMT+3 with US DST`.
- Kekurangan: metode deposit lokal (bank/e-wallet) belum terkonfirmasi resmi (\*), entitas offshore (St. Vincent/Seychelles).

### 2. Exness — **Standard Cent** (paling gampang deposit)
- Ada di MT5 (\*), simbol **`XAUUSDc`**, tanpa komisi.
- Deposit lokal: VA BCA/Mandiri/BRI/BNI/CIMB, DANA, OVO, GoPay, QRIS (\*).
- Spread gold kemungkinan lebih tipis, sekitar $0.16–0.35 (\*, pihak ketiga).
- **Stop-out 0%**: broker nggak nutup posisi sampai equity hampir habis. Makanya EA ini punya **hard stop sendiri** (-30%).
- **Nggak ada akun demo untuk Standard Cent.** Tes di Strategy Tester atau demo Standard dulu.
- Jam server GMT+0, jadi di EA pakai `InpServerTZ = Fixed offset`, `InpFixedOffsetHours = 0`.

### 3. JustMarkets — Standard Cent (cek dulu MT5-nya)
- Scalping diizinkan resmi; deposit BCA/Mandiri/BNI resmi ada.
- Halaman mereka sendiri nggak konsisten soal Standard Cent di MT5, jadi cek dulu sebelum deposit.

## Yang gua nggak saranin
| Broker | Alasan |
|---|---|
| RoboForex ProCent | Kartu spesifikasi gold nunjukin min lot 0.10 (10x lebih kasar); banyak keluhan withdraw 2026 (\*) |
| FBS Cent | Cent cuma bisa lewat link IB; syaratnya boleh nolak order "scalping/black-box" |
| FXTM Micro | MT4 doang |
| XM, Octa, Tickmill, IC Markets, Pepperstone | Nggak ada akun cent |
| Broker lokal (MIFX, HSB, Finex, Dupoin) | Legal (Bappebti), tapi akunnya micro, bukan cent: 0.01 lot = 1 oz, $1 gerak = 2% akun $50. Nggak muat buat risk 2%. |

## Soal legalitas (jujur aja)
- Nggak ada satupun broker cent di atas yang punya izin **Bappebti/OJK/BI**. Yang melanggar hukum itu broker yang nawarin tanpa izin;
  nggak ketemu aturan yang menghukum trader individunya. Tapi konsekuensinya: **nggak ada perlindungan hukum lokal**,
  nggak ada dana kompensasi, dan domainnya sering diblokir.
- Pakai **aplikasi/domain resmi aja**, hati-hati situs mirror/phishing.
- Hindari deposit lewat IB/exchanger/P2P, karena dana bisa kena bekukan (PPATK).
- Profit tetap penghasilan, jadi lapor di SPT tahunan (\*).

## Wajib dicek di MT5 sebelum jalanin EA
Klik kanan `XAUUSDc` → **Specification**:
1. **Contract size & tick value**: pastikan $1 gerak gold di 0.01 lot = 1 USC.
2. **Volume min/step = 0.01/0.01.** Kalau minimal 0.10, sizing EA jadi kasar (EA otomatis skip trade yang risk-nya >3%).
3. **Stops level / freeze level** (EA otomatis menghormati).
4. **Filling mode** (EA otomatis menyesuaikan, termasuk FOK).
5. **Swap long/short** dan hari triple swap.
6. **Jam server**: cocokin `InpServerTZ` (lihat `docs/PANDUAN.md`).
7. **Margin call / stop-out** akun: lihat di properti akun.

## Sumber utama
- HFM: [Cent account](https://www.hfm.com/int/en/trading-accounts/cent-account) · [XAUUSD spec](https://www.hfm.com/int/en/trading-instruments/single-product?symbol=XAUUSD247) · [Advantages](https://www.hfm.com/int/en/about/advantages)
- Exness: [Standard Cent](https://get.exness.help/hc/en-us/articles/17537782786588-Standard-Cent-account) · [Margin call & stop out](https://get.exness.help/hc/en-us/articles/360014693340-Margin-call-and-stop-out-levels-by-account-type) · [Commodities](https://get.exness.help/hc/en-us/articles/17854173039388-Commodities)
- JustMarkets: [Standard accounts](https://justmarkets.com/trading/standard-accounts) · [Bank Indonesia lokal](https://justmarkets.com/company/news/22/local-indonesian-banks)
- RoboForex: [ProCent XAUUSD](https://roboforex.com/forex-trading/trading/specifications/card/pro-cent/XAUUSD/) · FBS: [Trading conditions PDF](https://cdn.fbs.com/docs/Trading_conditions_en.pdf)
- Bacaan live pengguna HFM Cent (pihak ketiga): [AURUM](https://github.com/amarnazhan27-gif/AURUM) · [Alphatom_MT5](https://github.com/cryptyroot-ux/Alphatom_MT5)
