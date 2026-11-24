# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Haftalık zamana karşı yarışlar (Time Trial) ve altın hedefi
Kaynak: gt7-timetrials sitesinin her gün güncellediği hazır rapor (report.json, GitHub'da).
Rapor: süren time trial'lar, pist, araba, bitiş, dünya rekoru, şu anki altın süre (rekor + %3)
ve sitenin tahmin ettiği son altın süre. Koç Sony'ye istek atmaz, sadece bu raporu okur.
- Rapor günde birkaç kez (en fazla 6 saatte bir) arka planda indirilir, kayıt klasörüne saklanır.
- İnternet yoksa ya da rapor değişmişse son saklanan rapor kullanılır; o da yoksa sekme boş kalır,
  koçun geri kalanı etkilenmez.
- Pist ve araba adları bizim pist listemiz ve araba adlarıyla eşleştirilir; sürdüğün pist + araba
  bir time trial'a uyuyorsa tur sonunda altına kalan süre yazılır.
"""
import difflib
import json
import os
import re
import threading
import time
import urllib.request
from datetime import datetime, timezone

from gt7_pistler import normalize
from gt7_veri import _oku, araba_adi
from gt7_yol import USER_DIR

KAYNAK = ("https://raw.githubusercontent.com/gt7-timetrials/"
          "gt7-timetrials.github.io/main/report.json")
SITE = "https://gt7-timetrials.github.io/"
DOSYA = os.path.join(USER_DIR, "tt_rapor.json")
YENILE_S = 6 * 3600      # rapor bundan eskiyse yeniden indirilir
# Madalya süreleri dünya rekoruna göre (GT7 time trial kuralı): altın rekor + %3 (rapor da böyle
# hesaplıyor), gümüş + %5 (gt7-timetrials belgesi), bronz + %10 (yaygın bilinen kural, sitede yok).
GUMUS_KAT = 1.05
BRONZ_KAT = 1.10
# Arayüzdeki hedef düğmeleri: etiket -> ekrandaki ad
HEDEF_ADLARI = {"rekor": "Dünya rekoru", "altin": "Altın", "gumus": "Gümüş", "bronz": "Bronz"}
ZAMAN_ASIMI = 15         # indirme en fazla bu kadar saniye bekler
HATA_BEKLE_S = 600       # indirme başarısızsa bu kadar sonra yeniden denenir

_kilit = threading.Lock()
_durum = {"rapor": None, "indirildi": None, "hata": None, "deneme": 0, "suruyor": False}


# Raporda bazı adlar özel harfle yazılıyor ("Mazda ɛ̃fini RX-7"): sadece karşılaştırmada sade harfe çevrilir,
# ekranda ad raporun yazdığı gibi kalır.
OZEL_HARF = str.maketrans({"ɛ": "e", "ə": "e", "ø": "o", "æ": "ae", "œ": "oe", "ß": "ss", "ł": "l",
                           "đ": "d", "ð": "d", "þ": "th", "ı": "i"})
BENZERLIK = 0.88   # birebir eşleşme yoksa en çok benzeyen araba adı en az bu kadar benzemeli


def _anahtar(ad):
    """Ad karşılaştırması için sade hâli: aksansız, küçük harf, sadece harf/rakam kelimeleri."""
    return " ".join(re.findall(r"[a-z0-9]+", normalize((ad or "").lower().translate(OZEL_HARF))))


def pist_bul(ad, catalog):
    """Raporun pist adını bizim pist listemizde bulur (yoksa None)."""
    k = _anahtar(ad)
    if not k:
        return None
    for t in catalog:
        if _anahtar(t["name"]) == k:
            return t
    # "Reverse" / "(Reverse)" ve "Layout" gibi farklar: kelime kümesi aynı mı?
    ks = set(k.split()) - {"layout"}
    for t in catalog:
        if set(_anahtar(t["name"]).split()) - {"layout"} == ks:
            return t
    return None


def araba_bul(ad):
    """Raporun araba adından araba kodu (yoksa None). Birebir eşleşme yoksa en çok benzeyen ad
    (yazım farkları: "ɛ̃fini" / "efini", noktalama), yeterince benzemiyorsa None."""
    k = _anahtar(ad)
    if not k:
        return None
    adlar = {kod: _anahtar(isim) for kod, isim in _oku("arabalar.json").items()}
    for kod, a in adlar.items():
        if a == k:
            return int(kod)
    en_iyi, oran = None, 0.0
    for kod, a in adlar.items():
        r = difflib.SequenceMatcher(None, k, a).ratio()
        if r > oran:
            en_iyi, oran = kod, r
    return int(en_iyi) if en_iyi is not None and oran >= BENZERLIK else None


def _sure(ms):
    if not ms:
        return None
    m, s = divmod(ms / 1000, 60)
    return f"{int(m)}:{s:06.3f}"


def _oku_dosya():
    try:
        with open(DOSYA, encoding="utf-8") as f:
            return json.load(f), os.path.getmtime(DOSYA)
    except (OSError, ValueError):
        return None, None


def _indir():
    try:
        req = urllib.request.Request(KAYNAK, headers={"User-Agent": "gt7-koc"})
        with urllib.request.urlopen(req, timeout=ZAMAN_ASIMI) as r:
            veri = json.loads(r.read().decode("utf-8"))
        if not isinstance(veri.get("events"), list):
            raise ValueError("raporda 'events' yok (biçim değişmiş olabilir)")
        try:
            with open(DOSYA, "w", encoding="utf-8") as f:
                json.dump(veri, f, ensure_ascii=False)
        except OSError:
            pass
        with _kilit:
            _durum.update(rapor=veri, indirildi=time.time(), hata=None)
    except Exception as e:  # internet yok, site kapalı, biçim değişti...
        with _kilit:
            _durum["hata"] = str(e) or e.__class__.__name__
    finally:
        with _kilit:
            _durum["suruyor"] = False


def guncelle(zorla=False):
    """Rapor eskiyse arka planda indirmeyi başlatır (ana döngüyü bekletmez)."""
    with _kilit:
        if _durum["rapor"] is None:
            rapor, zaman = _oku_dosya()
            if rapor:
                _durum.update(rapor=rapor, indirildi=zaman)
        eski = _durum["indirildi"] is None or time.time() - _durum["indirildi"] > YENILE_S
        bekle = time.time() - _durum["deneme"] < HATA_BEKLE_S
        if _durum["suruyor"] or not (zorla or (eski and not bekle)):
            return
        _durum.update(suruyor=True, deneme=time.time())
    threading.Thread(target=_indir, daemon=True).start()


def _kalan(bitis):
    try:
        son = datetime.fromisoformat(bitis)
    except (TypeError, ValueError):
        return None
    return (son - datetime.now(timezone.utc)).total_seconds() / 86400


def etkinlikler(catalog, en_iyi=None):
    """Süren time trial'lar (arayüz ve tur sonu için).
    en_iyi(pist_id) -> bu pistte her arabayla en iyi turun: (ms, araba kodu) ya da (None, None).
    (Sınıflı etkinlikte, örneğin Gr.3, her arabayla sürülebilir; liderlik tablosu tek.)"""
    with _kilit:
        rapor = _durum["rapor"]
    out = []
    for e in (rapor or {}).get("events", []):
        kalan = _kalan(e.get("ends"))
        if kalan is not None and kalan < 0:
            continue
        pist = pist_bul(e.get("track"), catalog)
        kod = araba_bul(e.get("car"))
        tahmin = (e.get("predicted") or {}).get("gold_ms")
        altin = e.get("gold_now_ms")
        senin, senin_kod = en_iyi(pist["id"]) if en_iyi and pist else (None, None)
        wr = e.get("wr_ms")
        gumus = round(wr * GUMUS_KAT) if wr else None
        bronz = round(wr * BRONZ_KAT) if wr else None
        out.append({
            "id": e.get("event_id"), "pist": e.get("track"), "pist_id": pist["id"] if pist else None,
            "araba": e.get("car"), "araba_kod": kod,
            "kalan_gun": round(kalan, 1) if kalan is not None else None,
            "rekor_ms": e.get("wr_ms"), "rekor": _sure(e.get("wr_ms")), "rekor_sahibi": e.get("wr_holder"),
            "altin_ms": altin, "altin": _sure(altin),
            "altin_tahmin_ms": tahmin, "altin_tahmin": _sure(tahmin),
            "gumus_ms": gumus, "gumus": _sure(gumus), "bronz_ms": bronz, "bronz": _sure(bronz),
            "katilimci": e.get("entrants"), "url": e.get("leaderboard_url"),
            "senin_ms": senin, "senin": _sure(senin), "senin_araba": araba_adi(senin_kod) if senin_kod else None,
            "bitis": e.get("ends"),
            "altina_fark": round((senin - altin) / 1000, 3) if senin and altin else None,
        })
    return out


def durum():
    with _kilit:
        return {"indirildi": time.strftime("%d.%m %H:%M", time.localtime(_durum["indirildi"]))
                if _durum["indirildi"] else None,
                "hata": _durum["hata"], "suruyor": _durum["suruyor"], "kaynak": SITE}


def hedef(catalog, pist_id, araba_kodu=None):
    """Sürdüğün pistte süren bir time trial varsa o etkinlik, yoksa None. Araba bakılmaz: sınıflı
    etkinliklerde (Gr.3 vb.) her araba serbest ve raporda sınıf bilgisi yok."""
    if not pist_id:
        return None
    for e in etkinlikler(catalog):
        if e["pist_id"] == pist_id and e["altin_ms"]:
            return e
    return None


def bul(catalog, etkinlik_id, en_iyi=None):
    """Kimliğe göre süren etkinlik (yoksa None). en_iyi: etkinlikler()'deki gibi."""
    for e in etkinlikler(catalog, en_iyi):
        if e["id"] == etkinlik_id:
            return e
    return None


def tur_satiri(e, lap_ms, en_iyi_ms):
    """Tur sonu notu ve (altın ilk kez geçildiyse) kısa ses: (satır, ses ya da None)."""
    fark = (lap_ms - e["altin_ms"]) / 1000
    satir = f"Time trial altın hedefi {e['altin']}: bu tur {fark:+.3f} sn"
    if e.get("altin_tahmin") and e["altin_tahmin_ms"] != e["altin_ms"]:
        satir += f" (bitişte tahmini altın {e['altin_tahmin']})"
    satir += "."
    onceden = en_iyi_ms is not None and en_iyi_ms <= e["altin_ms"]
    ses = "Altın süreyi geçtin!" if fark <= 0 and not onceden else None
    return satir, ses
