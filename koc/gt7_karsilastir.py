# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - İki turu üst üste koyma
Seçilen iki turun hız, gaz, fren ve vites çizgileri aynı mesafe ekseninde; ikinci turun birinciye göre
zaman farkı (sn) her noktada. B turu A'nın çizgisine hizalanır (gt7-datalogger hizalaması), böylece
iki tur farklı çizgi ya da farklı uzunlukta olsa da aynı yerler üst üste gelir.
Bu seansın turları bellekte küçültülmüş tutulur (3 m'de bir nokta, en fazla 30 tur).
"""
from array import array

from gt7_kopru import _interp, ReferencePath, aligned_laps, place_corners, to_samples

ALANLAR = ("t", "dist", "x", "z", "speed", "throttle", "brake", "gear")
SAKLA_ADIM_M = 3.0      # bellekte tutulan turda nokta aralığı
GRAFIK_ADIM_M = 5.0     # grafikte nokta aralığı
EN_COK_TUR = 30


def iz_kucult(lap):
    """Turun grafik için gereken alanları, 3 m'de bir nokta (bellekte az yer tutsun)."""
    d = lap["dist"]
    sec, son = [], None
    for i, v in enumerate(d):
        if son is None or v - son >= SAKLA_ADIM_M or i == len(d) - 1:
            sec.append(i)
            son = v
    out = {k: array("f", [float(lap[k][i] or 0) for i in sec])
           for k in ALANLAR if lap.get(k) and len(lap[k]) == len(d)}
    out["lap_ms"] = lap.get("lap_ms")
    return out


def iz_sakla(state, no, lap):
    izler = state.setdefault("izler", {})
    izler[no] = iz_kucult(lap)
    for eski in sorted(izler)[:-EN_COK_TUR]:
        izler.pop(eski, None)


def _liste(iz):
    return {k: (list(v) if isinstance(v, array) else v) for k, v in iz.items()}


def karsilastir(a, b, corners=None, adim=GRAFIK_ADIM_M):
    """a: x ekseni olan tur, b: karşılaştırılan tur (ikisi de tur sözlüğü ya da iz).
    Döner: grafik verisi (mesafe, iki turun hız/gaz/fren/vites, B'nin A'ya göre farkı, virajlar)."""
    A, B = _liste(a), _liste(b)
    sa = to_samples(A)
    sb = aligned_laps([B], ReferencePath(sa))[0]
    uzunluk = sa["dist"][-1]
    d = [i * adim for i in range(int(uzunluk / adim) + 1)]

    def ornek(s, alan, hane=1):
        if not s.get(alan):
            return None
        return [round(_interp(s["dist"], s[alan], x), hane) for x in d]

    ta, tb = ornek(sa, "t", 3), ornek(sb, "t", 3)
    out = {"d": [round(x) for x in d], "uzunluk": round(uzunluk),
           "a": {"hiz": ornek(sa, "speed"), "gaz": ornek(sa, "throttle", 0), "fren": ornek(sa, "brake", 0),
                 "vites": ornek(sa, "gear", 0)},
           "b": {"hiz": ornek(sb, "speed"), "gaz": ornek(sb, "throttle", 0), "fren": ornek(sb, "brake", 0),
                 "vites": ornek(sb, "gear", 0)},
           "fark": [round(y - x, 3) for x, y in zip(ta, tb)],
           "a_ms": A.get("lap_ms"), "b_ms": B.get("lap_ms"), "virajlar": []}
    if corners:
        try:
            for w in place_corners(corners, sa):
                out["virajlar"].append({"no": w.n, "d": round(w.apex)})
        except Exception:
            pass
    return out
