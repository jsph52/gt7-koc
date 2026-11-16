# GT7 Türkçe Koç

**Gran Turismo 7 için Türkçe, sesli yapay zekâ sürüş koçu.**

GT7 Türkçe Koç, PS5'in ev ağına gönderdiği canlı telemetri verisini okur ve sürüşünü viraj viraj
analiz eder. Sürerken kulağına kısa ve net tavsiyeler verir, fren noktasına sesli geri sayım yapar,
tur sonunda en çok nerede zaman kaybettiğini ve bunu nasıl düzelteceğini söyler. Seni seanslar
arasında hatırlar ve gelişimini takip eder.

Ücretsizdir, hesap ya da abonelik gerektirmez. Tek bir EXE dosyasıyla çalışır.

---

## Özellikler

### Sürerken konuşan koç
- **Viraj öncesi tavsiye:** Zaman kaybettiğin virajlara yaklaşırken tek cümlelik, uygulanabilir
  tavsiye: *"Viraj 7: frene biraz daha geç bas."*
- **Çıkışta geri bildirim:** Tavsiyeyi uyguladıysan haber verir, aynı hata sürüyorsa hatırlatır.
- **Doğru anda konuşur:** Cümleyi yalnızca sakin bir ana sığıyorsa söyler; frende ve virajın
  ortasında araya girmez.
- **Ayarlanabilir hassasiyet:** Başlangıçtan uzmana beş seviye; koçun hangi farklarda konuşacağını sen
  belirlersin.

### Fren noktası uyarısı
- Her virajın fren noktasına **üç sesli geri sayım**: üçüncü seste frene basarsın.
- Viraja yaklaşma hızına göre fren noktası kendiliğinden kayar.
- Tepki süren ölçülür ve sürdükçe kendiliğinden ayarlanır.

### Tur sonu analizi
- Her viraj, **o virajdaki kendi en iyi geçişinle** karşılaştırılır; hatalı ve eksik turlar elenir.
- Zaman kaybının nedeni ölçülür: erken / geç fren, iz freni, viraj içi hız, gaza geç basma, çıkış hızı,
  çizgi, teker kilitlenmesi ve patinaj.
- Her viraj dört aşamada incelenir: giriş, dönüş, geçiş ve çıkış.
- **İdeal tur:** Bütün virajların en iyi geçişleri birleşince ulaşabileceğin süre.

### Time Trial
- Bu haftanın Time Trial etkinlikleri ana ekranda: dünya rekoru, altın süre ve senin en iyi turun.
- Hedefini seç (dünya rekoru, altın, gümüş, bronz); koç sana hedefe kalan farkı söyler.
- **Rekor turu:** Liderlik tablosundaki bir replay'i izleyerek kaydedebilirsin; koç seni o tura göre
  çalıştırır.

### İnceleme ve raporlar
- **Duraklatınca inceleme:** Oyunu duraklattığında, zamanı hangi teknikte kaybettiğin, sıradaki
  odak noktan ve viraj viraj tablo ekrana gelir.
- **İki turu karşılaştırma:** Hız, gaz ve fren çizgileri üst üste.
- **Seans raporu:** Her antrenmandan sonra tek sayfalık özet; geçmiş antrenmanların listesi.

### Yarış mühendisi
- Yakıt durumu ve pit stratejisi: kaç tur yeter, en geç hangi turda pite girmelisin.
- Lastik sıcaklığı, motor uyarıları, sıra değişimi, son tur anonsu.
- Araç ayarı önerileri: kilitlenme, patinaj, önden / arkadan kayma, vites oranları, yerden yükseklik.

### Kullanım kolaylığı
- **Otomatik:** PS5'i ağda kendisi bulur, pisti ve arabayı kendisi tanır, piste çıkınca antrenmanı başlatır.
- **122 pist düzeni** ve GT7'deki arabaların adları hazır.
- **Discord ile PS5 kulaklığı:** Koçun sesini ve fren uyarılarını doğrudan PS5 kulaklığından duy.
- **Telefon ve tablet:** Ekran aynı Wi-Fi'daki telefon ya da iPad'den de açılır.
- Doğal Türkçe ses, isteğe bağlı telsiz efekti.

---

## Kurulum

1. [Releases](https://github.com/jsph52/gt7-koc/releases) sayfasından `GT7-Koc.exe` dosyasını indir.
2. EXE'yi istediğin yere koy ve çift tıkla. Turların, ayarların ve raporların **Belgeler › GT7 Koc** klasörüne kaydedilir; yeni sürümü indirince eskisinin yerine koyman yeterli.
   - Windows uyarı verirse: **Ek bilgi › Yine de çalıştır**.
   - Güvenlik duvarı sorarsa: **İzin ver**.
3. PS5 ile bilgisayarın aynı ev ağında olduğundan emin ol.
4. GT7'de piste çık. Koç gerisini halleder.

**Gereksinimler:** Windows 10 / 11, PS5 ve Gran Turismo 7, aynı ev ağı. Koçun sesi için internet bağlantısı.

## Sorun giderme

| Sorun | Çözüm |
|---|---|
| PS5 bulunamıyor | Ayarlar › Bağlantı › **PS5'i ağda bul**, ya da PS5'in IP adresini elle yaz (PS5'te Ayarlar › Ağ › Bağlantı Durumu). |
| Veri kesik kesik geliyor | PS5'i kabloyla ya da 5 GHz Wi-Fi ile bağla. |
| Koç veri almıyor | Telemetri kullanan başka bir program aynı bilgisayarda açıksa kapat. |
| Başka bir sorun | **Belgeler › GT7 Koc** klasöründeki `koc_gunluk.txt` dosyasına bak. |

---

## Kaynaklar ve lisanslar

- Telemetri çözümü ve ölçümler: [gt7-datalogger](https://github.com/jbhoorasingh/gt7-datalogger) (MIT, `koc/alinan/`).
- Pist çizgileri: [gt7-datalogger-track-data](https://github.com/jbhoorasingh/gt7-datalogger-track-data) (CC0 / MIT),
  [gt-telemetry](https://github.com/zetetos/gt-telemetry) (MIT), [GT7Tracks](https://github.com/vthinsel/GT7Tracks) (MIT);
  lisansları `koc/pistler/` içinde.
- Araba ve pist bilgileri: [gt7info](https://github.com/ddm999/gt7info) (MIT-0).
- Haftalık Time Trial verisi: [gt7-timetrials](https://gt7-timetrials.github.io/) sitesinin yayınladığı rapor.
- Yazı tipi: Barlow Condensed (SIL Open Font License), `koc/yazitipi/`.

Bu proje Sony Interactive Entertainment ya da Polyphony Digital ile bağlantılı değildir.
"Gran Turismo" ve "GT7" ilgili sahiplerinin markalarıdır.
