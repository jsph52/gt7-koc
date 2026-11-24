"""Koçun sesi: herkeste aynı Türkçe ses (Microsoft "Ahmet").

Ses tarayıcıda değil burada üretilir, böylece Chrome, Edge, Firefox ya da telefon
fark etmez, herkes aynı sesi duyar.
Kaynak: edge-tts paketi (açık kaynak, ücretsiz; Microsoft'un Edge'deki "sesli oku"
servisini kullanır, internet ister, anahtar gerekmez). İnternet yoksa ya da servis
cevap vermezse None döner; arayüz o cümleyi okumaz (tarayıcının kendi sesine
geçilmez: iki farklı ses karışık duyulmasın).
"""
import asyncio
import os
import threading
import time
from collections import OrderedDict

SES = "tr-TR-AhmetNeural"
HIZ = "+5%"
# Ayarlar'dan seçilebilir: ses ve konuşma hızı
SESLER = {"ahmet": "tr-TR-AhmetNeural", "emel": "tr-TR-EmelNeural"}
HIZLAR = {"yavas": "-5%", "normal": "+5%", "hizli": "+15%", "cok_hizli": "+25%"}
ZAMAN_ASIMI = 6.0        # sn: bir deneme bundan uzun sürerse bırakılır
DENEME = 2               # her cümle için deneme sayısı (internetteki kısa takılmalar için)
ART_ARDA = 3             # bu kadar cümle üst üste alınamazsa servis gitmiş sayılır...
BEKLEME = 20.0           # ...ve bu kadar sn denenmez (o arada cümleler okunmaz)
# Tek bir hatada servisi bırakmamak için: kısa internet takılmaları cümleleri susturmasın.
EN_UZUN = 400            # karakter
ONBELLEK = 300           # cümle

_onbellek = OrderedDict()
_kilit = threading.Lock()
_son_hata = 0.0
_hata_sayisi = 0         # üst üste alınamayan cümle sayısı
hata = None              # son hata (ekranda / testte göstermek için)


def _proxy():
    # Sadece geliştirme ortamı için: bilgisayarda vekil sunucu tanımlıysa onu kullan
    return os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None


async def _uret(metin, ses=SES, hiz=HIZ):
    import edge_tts
    c = edge_tts.Communicate(metin, ses, rate=hiz, proxy=_proxy())
    parcalar = bytearray()
    async for p in c.stream():
        if p.get("type") == "audio":
            parcalar += p["data"]
    return bytes(parcalar)


def sentez(metin, ses="ahmet", hiz="normal"):
    """Metni MP3 olarak döndürür; olmazsa None. ses: "ahmet"/"emel", hiz: HIZLAR anahtarı."""
    global _son_hata, _hata_sayisi, hata
    metin = " ".join(str(metin or "").split())[:EN_UZUN]
    if not metin:
        return None
    ses_adi, oran = SESLER.get(ses, SES), HIZLAR.get(hiz, HIZ)
    anahtar = (metin, ses_adi, oran)
    with _kilit:
        if anahtar in _onbellek:
            _onbellek.move_to_end(anahtar)
            return _onbellek[anahtar]
        if _hata_sayisi >= ART_ARDA and time.time() - _son_hata < BEKLEME:
            return None
    veri = None
    for _ in range(DENEME):
        try:
            veri = asyncio.run(asyncio.wait_for(_uret(metin, ses_adi, oran), ZAMAN_ASIMI))
            if not veri:
                raise RuntimeError("boş ses geldi")
            break
        except ImportError as e:   # paket yok: tekrar denemenin anlamı yok
            veri = None
            hata = f"{type(e).__name__}: {e}"[:200]
            break
        except Exception as e:     # internet takıldı, servis cevap vermedi...
            veri = None
            hata = f"{type(e).__name__}: {e}"[:200]
    if not veri:
        with _kilit:
            _son_hata = time.time()
            _hata_sayisi += 1
        print("Ses alınamadı:", hata, "| cümle:", metin[:60])
        return None
    with _kilit:
        hata = None
        _hata_sayisi = 0
        _onbellek[anahtar] = veri
        while len(_onbellek) > ONBELLEK:
            _onbellek.popitem(last=False)
    return veri


if __name__ == "__main__":   # deneme: python koc/gt7_ses.py "Merhaba"
    import sys
    v = sentez(" ".join(sys.argv[1:]) or "Telsiz denemesi, mühendis hatta.")
    if v:
        with open("ses_deneme.mp3", "wb") as f:
            f.write(v)
        print("ses_deneme.mp3 yazıldı,", len(v), "bayt")
    else:
        print("Ses üretilemedi:", hata)
