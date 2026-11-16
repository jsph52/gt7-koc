# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Hedef süre
Hedef, pist kaydında araba başına saklanır: tr["hedef"][araba kodu] = ms.
Analiz: en iyi turun hedefe ne kadar uzak; virajlardaki en iyi geçişlerini birleştirince (ideal tur)
hedefe ulaşılıyor mu, ulaşılıyorsa farkı hangi virajlar kapatır; ulaşılmıyorsa (rekor turu varsa)
rekor turuna göre en çok fark olan virajlar.
"""
import re

from gt7_kopru import compare, viraj_kazanclari
from gt7_paket import sure

EN_AZ_SN = 0.02       # bundan küçük viraj kazancı listelenmez
EN_COK = 4            # listelenen viraj sayısı


def sure_oku(metin):
    """"1:52.000", "1:52", "1.52.300", "52.4" -> ms; okunamazsa None."""
    t = str(metin or "").strip().replace(",", ".")
    adaylar = []
    m = re.fullmatch(r"(\d+):(\d{1,2})(?:\.(\d{1,3}))?", t)
    if m:
        adaylar.append(m.groups())
    m = re.fullmatch(r"(\d+)\.(\d{2})\.(\d{1,3})", t)
    if m:
        adaylar.append(m.groups())
    m = re.fullmatch(r"(\d{1,3})(?:\.(\d{1,3}))?", t)       # sadece saniye: "52.4"
    if m:
        adaylar.append(("0", m.group(1), m.group(2)))
    m = re.fullmatch(r"(\d+)\.(\d{2})", t)                  # "1.52" = 1 dk 52 sn
    if m:
        adaylar.append((m.group(1), m.group(2), None))
    for dk, sn, ks in adaylar:
        dk, sn = int(dk), int(sn)
        if dk and sn >= 60:
            continue
        ms = (dk * 60 + sn) * 1000 + int((ks or "0").ljust(3, "0")[:3])
        if 10_000 <= ms <= 3_600_000:
            return ms
    return None


def _viraj(adi, no):
    return adi(no) if adi else f"Viraj {no}"


def analiz(hedef_ms, pool, corners, rekor=None, adi=None):
    """Hedefe göre durum (arayüz ve tur notları için)."""
    out = {"hedef": sure(hedef_ms), "hedef_ms": hedef_ms, "virajlar": [], "satirlar": []}
    if not pool:
        out["durum"] = "tur_yok"
        out["satirlar"].append(f"Hedef {sure(hedef_ms)}. Analiz için önce temiz bir tur at.")
        return out
    best = min(pool, key=lambda L: L["lap_ms"])
    kalan = (best["lap_ms"] - hedef_ms) / 1000
    out.update(en_iyi=sure(best["lap_ms"]), kalan=round(kalan, 3))
    if kalan <= 0:
        out["durum"] = "ulasildi"
        out["satirlar"].append(f"Hedef {sure(hedef_ms)} geçildi: en iyi turun {sure(best['lap_ms'])} "
                               f"({kalan:+.3f} sn). Yeni bir hedef koyabilirsin.")
        return out
    out["satirlar"].append(f"Hedef {sure(hedef_ms)}: en iyi turun {sure(best['lap_ms'])}, {kalan:.3f} sn kaldı.")
    kaz = viraj_kazanclari(pool, corners) if len(pool) >= 2 and corners else {}
    toplam = sum(kaz.values())
    sirali = sorted(((no, v) for no, v in kaz.items() if v >= EN_AZ_SN), key=lambda x: -x[1])
    if kaz:
        out["ideal"] = sure(int(best["lap_ms"] - toplam * 1000))
    if kaz and toplam >= kalan:
        out["durum"] = "ideal_yeter"
        sec, birikim = [], 0.0
        for no, v in sirali:
            sec.append((no, v))
            birikim += v
            if birikim >= kalan or len(sec) >= EN_COK:
                break
        out["virajlar"] = [{"no": no, "ad": _viraj(adi, no), "sn": round(v, 3), "kaynak": "ideal"} for no, v in sec]
        out["satirlar"].append(f"İdeal turun {out['ideal']}: hedef ulaşılabilir. Virajlardaki en iyi geçişlerini "
                               "tek turda birleştirmen yeter.")
        out["satirlar"].append("Farkı kapatacak virajlar: " + ", ".join(
            f"{_viraj(adi, no)} {v:.2f} sn" for no, v in sec) + ".")
        return out
    out["durum"] = "ideal_yetmez" if kaz else "az_tur"
    if kaz:
        out["satirlar"].append(f"İdeal turun ({out['ideal']}) bile hedefin {kalan - toplam:.2f} sn gerisinde: "
                               "en iyi geçişlerini birleştirmek yetmez, yeni bir şey denemen gerek.")
        out["virajlar"] = [{"no": no, "ad": _viraj(adi, no), "sn": round(v, 3), "kaynak": "ideal"}
                           for no, v in sirali[:EN_COK]]
        if sirali:
            out["satirlar"].append("Kendi en iyi geçişlerinle kazanabileceğin: " + ", ".join(
                f"{_viraj(adi, no)} {v:.2f} sn" for no, v in sirali[:EN_COK]) + ".")
    else:
        out["satirlar"].append("Viraj viraj öneri için en az 2 temiz tur gerekli.")
    if rekor and corners:
        try:
            res = compare(best, [rekor], corners)
        except Exception:
            res = []
        fark = sorted((r for r in res if r["delta"] >= 0.05), key=lambda r: -r["delta"])[:EN_COK]
        if fark:
            out["rekor_virajlar"] = [{"no": r["no"], "ad": _viraj(adi, r["no"]), "sn": round(r["delta"], 3),
                                      "kaynak": "rekor"} for r in fark]
            out["satirlar"].append("Rekor turuna göre en çok fark (yeni şeyler burada denenir): " + ", ".join(
                f"{_viraj(adi, r['no'])} {r['delta']:.2f} sn" for r in fark) + ".")
    elif not rekor:
        out["satirlar"].append("Time Trial sekmesinden bir rekor turu kaydedersen, hangi virajda daha hızlı "
                               "gidilebildiğini de gösteririm.")
    return out


def ses(hedef_ms, lap_ms, onceki_en_iyi, problem):
    """Tur sonu sesine kısa ek: hedef ilk kez geçildiyse ya da yeni en iyi turdaysa kalan fark."""
    if problem or not hedef_ms:
        return None
    if lap_ms <= hedef_ms and (onceki_en_iyi is None or onceki_en_iyi > hedef_ms):
        return "Hedefi geçtin!"
    if onceki_en_iyi is not None and lap_ms < onceki_en_iyi and lap_ms > hedef_ms:
        return f"Hedefe {(lap_ms - hedef_ms) / 1000:.2f} saniye kaldı."
    return None
