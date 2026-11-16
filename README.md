# GT7 Türkçe Koç

Gran Turismo 7 için Türkçe, sesli sürüş koçu. PS5'in ev ağına gönderdiği canlı sürüş verisini
okur. Sürerken virajlardan önce kısa tavsiye verir, fren noktasından önce sesli uyarı çalar, tur
sonunda en çok nerede zaman kaybettiğini ve ne yapman gerektiğini söyler. Ücretsizdir, hesap
gerektirmez.

## Kurulum
1. [Releases sayfasından](https://github.com/jsph52/gt7-koc/releases) `GT7-Koc.exe` dosyasını indir.
2. EXE'yi kendine ait bir klasöre koy (turların ve ayarların bu klasöre kaydedilir) ve çift tıkla.
   - Windows uyarı verirse: **Ek bilgi → Yine de çalıştır**.
   - Güvenlik duvarı sorarsa: **İzin ver**.
3. PS5 ve bilgisayar aynı ev ağında olmalı. Koç PS5'i kendisi bulur.

## Kullanım
- **Serbest antrenman:** GT7'de piste çık; koç antrenmanı kendiliğinden başlatır, pisti ve arabayı tanır.
- **Time Trial:** ana ekrandaki bu haftanın Time Trial'larından birini seç; hazırlık ekranı hedef
  süreyi (altın, gümüş, bronz, dünya rekoru) ve oyunda nereye gideceğini gösterir.
- **Duraklatınca:** oyunu duraklattığında, turlarında en çok nerede zaman kaybettiğini gösteren
  inceleme ekranı açılır.
- **Ayarlar:** koçun ne kadar konuşacağı, fren uyarısı, ses ve ses düzeyi, Discord.
- **Discord ile PS5 kulaklığı:** Ayarlar › Discord'daki adımları bir kez uygula; koçun sesini PS5
  kulaklığından duyarsın.
- **Telefon / tablet:** aynı Wi-Fi'daki telefon ya da iPad'den de açılır (adres Ayarlar › Bağlantı'da yazar).

## Sorun giderme
- PS5 bulunamıyorsa: Ayarlar › Bağlantı › "PS5'i ağda bul" ya da PS5'in IP adresini elle yaz
  (PS5'te Ayarlar › Ağ › Bağlantı Durumu).
- Veri kesik kesik geliyorsa PS5'i kabloyla ya da 5 GHz Wi-Fi ile bağla.
- Telemetri kullanan başka bir program aynı bilgisayarda açıkken koç çalışamaz.
- Bir sorun olursa EXE'nin yanındaki `koc_gunluk.txt` dosyasına bakılabilir.

Bu program Sony Interactive Entertainment ya da Polyphony Digital ile bağlantılı değildir.
"Gran Turismo" ilgili sahiplerinin markasıdır.

## Kaynaklar ve lisanslar
- Telemetri çözümü ve ölçümler: [gt7-datalogger](https://github.com/jbhoorasingh/gt7-datalogger) (MIT, `koc/alinan/`).
- Pist çizgileri: [gt7-datalogger-track-data](https://github.com/jbhoorasingh/gt7-datalogger-track-data) (CC0 / MIT),
  [gt-telemetry](https://github.com/zetetos/gt-telemetry) (MIT), [GT7Tracks](https://github.com/vthinsel/GT7Tracks) (MIT);
  lisansları `koc/pistler/` içinde.
- Araba ve pist bilgileri: [gt7info](https://github.com/ddm999/gt7info) (MIT-0).
- Haftalık Time Trial verisi: [gt7-timetrials](https://gt7-timetrials.github.io/) sitesinin yayınladığı rapor.
- Yazı tipi: Barlow Condensed (SIL Open Font License), `koc/yazitipi/`.
