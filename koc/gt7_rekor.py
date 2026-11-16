# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Rekor turu (replay'den referans)
Fikir gt7-timetrials sitesinden: GT7 telemetriyi replay izlerken de gönderir. Lider tablosundan
rekor sahibinin replay'i indirilip izlenirse koç o turu kaydeder. Ayar "referans" = "rekor" iken
(varsayılan) koçun HER ŞEYİ bu tura
göredir: viraj karşılaştırması, sesli tavsiyeler, canlı fark, fren bipi noktaları. "kendi" iken eskisi gibi
sadece tur notlarında ek karşılaştırma olur.
Kayıt: pist dosyasında tr["rekor"][araba kodu] (araba başına en hızlı replay turu).
"""
import time

from gt7_kopru import compare
from gt7_paket import sure

ALANLAR = ("t", "dist", "x", "z", "speed", "throttle", "brake", "gear", "rpm", "wheel_angle")
EN_COK = 3            # tur notlarında rekora göre en çok kaybettiren bu kadar viraj


def rekor_turu(lap, lap_ms, car):
    """Kaydedilecek rekor turu: sadece karşılaştırmada gereken alanlar."""
    out = {k: list(lap[k]) for k in ALANLAR if lap.get(k)}
    out.update(lap_ms=lap_ms, car=car, saat=time.strftime("%d.%m.%Y %H:%M"))
    return out


def rekor_ekle(tr, rek):
    """Rekor turunu pist kaydına koyar; aynı arabada daha hızlısı varsa onu korur.
    Döner: (eklendi mi, önceki tur ya da None)."""
    kayit = tr.setdefault("rekor", {})
    eski = kayit.get(str(rek["car"]))
    if eski and eski["lap_ms"] <= rek["lap_ms"]:
        return False, eski
    kayit[str(rek["car"])] = rek
    return True, eski


def rekor_dili(metin):
    """Karşılaştırma cümlelerindeki "en iyi geçişin" ifadelerini rekor turuna çevirir."""
    for a, b in (("en iyi geçişinden", "rekor turundan"), ("en iyi geçişinde", "rekor turunda"),
                 ("en iyi geçişine", "rekor turuna"), ("en iyi geçişin", "rekor turun")):
        metin = metin.replace(a, b)
    return metin


def rekor_karsilastir(lap, rek, corners):
    """Bu turu rekor turuyla viraj viraj karşılaştırır.
    Döner: (ekran satırları, özet {"fark", "rekor", "virajlar": {no: fark}})."""
    lap_ms = lap["lap_ms"]
    res = compare(lap, [rek], corners)
    fark = (lap_ms - rek["lap_ms"]) / 1000
    satir = [f"Rekor turuna göre: {fark:+.3f} sn (rekor {sure(rek['lap_ms'])})."]
    kayip = sorted([r for r in res if r["delta"] > 0.05], key=lambda r: -r["delta"])[:EN_COK]
    for r in kayip:
        neden = "; ".join(rekor_dili(x) for x in r["reasons"]) or "fark küçük ayrıntılarda"
        satir.append(f"Rekora göre Viraj {r['no']}: {r['delta']:+.2f} sn -> {neden}")
    ozet = {"fark": round(fark, 3), "rekor": sure(rek["lap_ms"]),
            "virajlar": {str(r["no"]): round(r["delta"], 3) for r in res}}
    return satir, ozet
