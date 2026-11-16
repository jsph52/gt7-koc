# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Viraj adları
Bilinen pistlerde (Suzuka, Spa, Monza, Bathurst, Le Mans, Laguna Seca…) koçun bulduğu virajlar
veri/viraj_adlari.json'daki adlı noktalarla konumdan eşleşir (70 m içinde, her ad bir virajda).
- Ses: "Viraj 13'te" yerine "Spoon'da" (ek, adın okunuşuna göre: Spoon'da, La Source'ta, Lesmo 2'de).
- Ekran: "Spoon'da (V13)" — haritadaki numarayla bağlantı kurulsun diye.
- Ses üretiminden önce yabancı adlar Türkçe okunuşla değiştirilir (gt7_ses: "Spoon" -> "spun").
Adı olmayan virajlar eskisi gibi "Viraj 5" kalır. Nordschleife'de eşleşmeden emin olunamadığı için ad yok.
"""
import json
import math
import os
import re

from gt7_yol import DATA_DIR

DOSYA = os.path.join(DATA_DIR, "veri", "viraj_adlari.json")
ESIK_M = 70            # adlı nokta ile virajın tepe noktası en fazla bu kadar uzak olabilir

INCE = "eiöü"
UNLU = "aeıioöuü"
SERT = "fstkçşhp"

_veri = None


def _yukle():
    global _veri
    if _veri is None:
        try:
            with open(DOSYA, encoding="utf-8") as f:
                _veri = json.load(f)
        except (OSError, ValueError):
            _veri = {"pistler": {}, "ortak": {}}
    return _veri


def pist_adlari(pist_id):
    v = _yukle()
    if not pist_id:
        return []
    return v["pistler"].get(pist_id) or v["pistler"].get(v.get("ortak", {}).get(pist_id), [])


def eslestir(pist_id, corners):
    """Koçun virajları (no, x, z) -> {viraj no: ad kaydı}. Her ad en yakın tek virajı alır."""
    adlar = pist_adlari(pist_id)
    if not adlar or not corners:
        return {}
    ciftler = sorted((math.hypot(c["x"] - a["xz"][0], c["z"] - a["xz"][1]), i, c["no"])
                     for i, a in enumerate(adlar) for c in corners if c.get("x") is not None)
    out, kullanilan = {}, set()
    for d, i, no in ciftler:
        if d > ESIK_M:
            break
        if no in out or i in kullanilan:
            continue
        out[no] = adlar[i]
        kullanilan.add(i)
    return out


def _kucuk(s):
    return s.replace("I", "ı").replace("İ", "i").lower()


def ekle(kayit, tur):
    """Ada hal eki: tur "de" (bulunma), "den" (ayrılma), "e" (yönelme). Okunuşa göre ünlü uyumu."""
    ok = _kucuk(kayit.get("okunus") or kayit["ad"])
    harf = [h for h in ok if h.isalpha()]
    unluler = [h for h in harf if h in UNLU]
    ince = bool(unluler) and unluler[-1] in INCE
    son = harf[-1] if harf else "a"
    e = "e" if ince else "a"
    if kayit.get("tur") == "tri":        # "Dunlop şikanı" -> "Dunlop şikanında"
        ek = {"de": "nd" + e, "den": "nd" + e + "n", "e": "n" + e}[tur]
    else:
        de = ("t" if son in SERT else "d") + e
        ek = {"de": de, "den": de + "n", "e": ("y" if son in UNLU else "") + e}[tur]
    return kayit["ad"] + ("" if kayit.get("tur") in ("tr", "tri") else "'") + ek


_EK_TURU = {"de": "de", "da": "de", "te": "de", "ta": "de",
            "den": "den", "dan": "den", "ten": "den", "tan": "den",
            "e": "e", "a": "e", "ye": "e", "ya": "e"}
_KALIP = re.compile(r"Viraj (\d+)((?:(?:, | ve )\d+)*)(?:'([a-zçğıöşü]+))?")


def adlandir(metin, adlar, ekran=False):
    """Metindeki "Viraj 5'te" gibi yerlerde virajın adı varsa adı koyar.
    ekran=True: adın yanına haritadaki numara "(V5)" eklenir."""
    if not metin or not adlar or "Viraj " not in metin:
        return metin
    from gt7_kopru import de, den, ye   # döngüsel içe aktarma olmasın

    def degistir(m):
        nolar = [int(m.group(1))] + [int(x) for x in re.findall(r"\d+", m.group(2) or "")]
        ayiraclar = re.findall(r", | ve ", m.group(2) or "")
        if not any(n in adlar for n in nolar):
            return m.group(0)
        ek = m.group(3)
        tur = _EK_TURU.get(ek) if ek else None
        if ek and not tur:
            return m.group(0)
        parca = []
        for k, n in enumerate(nolar):
            son = k == len(nolar) - 1
            kayit = adlar.get(n)
            if kayit:
                s = ekle(kayit, tur) if son and tur else kayit["ad"]
                if ekran:
                    s += f" (V{n})"
            else:
                s = "Viraj " + ({"de": de, "den": den, "e": ye}[tur](n) if son and tur else str(n))
            parca.append(s)
        out = parca[0]
        for a, p in zip(ayiraclar, parca[1:]):
            out += a + p
        return out

    return _KALIP.sub(degistir, metin)


def okunus_uygula(metin):
    """Ses üretmeden önce yabancı viraj adlarını Türkçe okunuşla değiştirir ("Spoon'da" -> "spun'da")."""
    if not metin:
        return metin
    ciftler = getattr(okunus_uygula, "_ciftler", None)
    if ciftler is None:
        tum = {}
        for liste in _yukle()["pistler"].values():
            for a in liste:
                if a.get("okunus"):
                    tum[a["ad"]] = a["okunus"]
        ciftler = sorted(tum.items(), key=lambda x: -len(x[0]))
        okunus_uygula._ciftler = ciftler
    for ad, ok in ciftler:
        if ad in metin:
            metin = re.sub(r"(?<![\w])" + re.escape(ad) + r"(?![\w])", ok, metin)
    return metin
