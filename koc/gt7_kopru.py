# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - gt7-datalogger köprüsü
alinan/ klasöründeki hazır kodu (MIT, bkz. alinan/KAYNAK.md) koçun tur verisiyle kullanır.
"""
import math
from bisect import bisect_left, bisect_right
import os
import sys

from gt7_yol import DATA_DIR

sys.path.insert(0, os.path.join(DATA_DIR, "alinan"))

from app.processing.alignment import ReferencePath, align_to_reference
from app.processing.analysis import _heading_rate, _interp, project_corners
from app.processing.corner_metrics import (LapTrace, brake_point_delta, gear_high, measure,
                                           min_speed_delta, windows)
from app.processing.events import detect_events
from app.processing.strategy import LapFuel, project_strategy
from app.telemetry.packet import parse_packet  # noqa: F401 (gt7_koc kullanır)
from gt7_ipucu import duzluk_kesmeleri, kesme_cumlesi, viraj_ipuclari

WHEEL_NAMES = {"fl": "ön sol", "fr": "ön sağ", "rl": "arka sol", "rr": "arka sağ"}
ALIGN_MAX_SHIFT = 0.1  # hizalanan mesafe turun bu oranından fazla kayamaz
EVENT_CORNER_M = 150   # olay bir virajdan bundan uzaksa viraja bağlanmaz


def to_samples(lap):
    s = {k: v for k, v in lap.items() if isinstance(v, list)}
    s["pos_x"], s["pos_z"] = lap["x"], lap["z"]
    return s


def place_corners(corners, samples):
    """Koçun virajlarını (x, z) verilen turun üzerine giriş/tepe/çıkış olarak yerleştirir."""
    authored = [{"n": c["no"], "apex": {"x": c["x"], "z": c["z"]}} for c in corners]
    return windows(project_corners(samples, authored))


def section_bounds(wins, end):
    """Her virajın bölümü: önceki ve sonraki virajla arasındaki orta noktalar."""
    out = []
    for i, w in enumerate(wins):
        a = 0.0 if i == 0 else (wins[i - 1].apex + w.apex) / 2
        b = end if i == len(wins) - 1 else (w.apex + wins[i + 1].apex) / 2
        out.append((a, b))
    return out


def section_time(s, a, b):
    return _interp(s["dist"], s["t"], b) - _interp(s["dist"], s["t"], a)


# ---- Viraj bölümleri: çıkıştaki düzlük o virajın sayılır ----
# Bölüm sınırı iki virajın tam ortası olsaydı, Viraj 3'ten yavaş çıkınca düzlüğün ikinci yarısında
# kaybedilen süre Viraj 4'ün hanesine yazılırdı. Bu yüzden sınır sonraki virajın fren noktasından biraz
# önce: düzlük, kendisine yavaş çıkılan virajın.
DUZLUK_PAY_M = 30.0     # sonraki virajın (bu tur ve referanstaki) en erken fren noktasından bu kadar önce
DUZLUK_MIN_M = 20.0     # orta noktayla sınır arası bundan kısaysa ayrıca "düzlük kaybı" yazılmaz


def bolum_sinirlari(wins, end, olcumler=()):
    """Her virajın bölümü [(başlangıç, bitiş)]: önceki virajın bölümü bittiği yerden, sonraki
    virajın en erken fren noktası − DUZLUK_PAY_M'ye kadar. Sonraki viraj frensizse (ya da ölçüm
    yoksa) eskisi gibi iki virajın ortası. olcumler: measure() sonuçları (ör. bu tur + referans)."""
    orta = section_bounds(wins, end)
    kes = []
    for i, (_, b) in enumerate(orta):
        if i + 1 < len(wins):
            nx = wins[i + 1]
            frenler = [m[nx.n].brake_on for m in olcumler
                       if m and m.get(nx.n) is not None and m[nx.n].brake_on is not None]
            if frenler:
                b = max(b, min(min(frenler) - DUZLUK_PAY_M, nx.apex - DUZLUK_MIN_M))
        kes.append(b)
    return [(0.0 if i == 0 else kes[i - 1], b) for i, b in enumerate(kes)]


# ---- Kaza / pistten çıkma: o virajda ne düzeltme ne övgü ----
TASMA_PAKET = 6          # 1+ teker gevşek zeminde bu kadar paket (~0,1 sn) = taşma (gt7_tur_kurallari ile aynı)
KAZA_HIZ_ORAN = 0.6      # en düşük hız referansın bu oranının altına indiyse: döndün ya da neredeyse durdun
KAZA_S = 1.0             # bölümde en az bu kadar ...
KAZA_ORAN = 0.15         # ... ve referans bölüm süresinin bu oranından fazla kayıp = anormal
# Spin: arabanın kendi ekseni etrafında dönme hızı (0x2C açısal hız, dikey eksen) bu kadar rad/sn'yi
# SPIN_PAKET paket (~0,1 sn) üst üste geçti, 25 km/s üstünde. Normal virajda (saç tokası, 60 km/s) ~1 rad/sn.
# Sesli söylenmez: sadece o virajda tavsiye verilmez. Gerçek oyunda denenmedi.
SPIN_YAW = 2.5
SPIN_PAKET = 6
SPIN_HIZ = 25


def kaza_mi(s, ref, a, b, rs=None, delta=None):
    """Bu bölümde teknik yorumu anlamsız kılan bir şey oldu mu? Sebep metni ya da None.
    s: bu turun (hizalanmış) örnekleri ("loose" = gevşek zemindeki teker sayısı, varsa)."""
    d = s.get("dist") or []
    i0, i1 = bisect_left(d, a), bisect_right(d, b)
    run = 0
    for v in (s.get("loose") or [])[i0:i1]:
        run = run + 1 if v is not None and v >= 1 else 0
        if run >= TASMA_PAKET:
            return "pistten çıktın (teker çime / kuma taştı)"
    run = 0
    for y, v in zip((s.get("yaw") or [])[i0:i1], (s.get("speed") or [])[i0:i1]):
        run = run + 1 if y is not None and v is not None and abs(y) >= SPIN_YAW and v >= SPIN_HIZ else 0
        if run >= SPIN_PAKET:
            return "araba döndü (spin)"
    hizlar = [v for v in (s.get("speed") or [])[i0:i1] if v is not None]
    if hizlar and rs is not None and rs.min_speed and rs.min_speed > 30 \
            and min(hizlar) < KAZA_HIZ_ORAN * rs.min_speed:
        return "araba döndü ya da neredeyse durdu"
    if delta is not None and delta > max(KAZA_S, KAZA_ORAN * section_time(ref, a, b)):
        return "normalden çok fazla zaman kaybettin (kaza / büyük hata)"
    return None


FAZ_ADLARI = ("Giriş", "Dönüş", "Geçiş", "Çıkış")
FAZ_DE = {"Giriş": "girişte", "Dönüş": "dönüşte", "Geçiş": "frenden gaza geçişte", "Çıkış": "çıkışta"}


def faz_sureleri(mine, ref, rs, w, a, b):
    """Virajın 4 aşamasında referansa göre kaybedilen süre (sn, + = kayıp). Aşama sınırları
    referans geçişten: dönüşe başlama, en yavaş nokta, tam gaz (yoksa gaz, yoksa çıkış).
    Toplamı bölümün farkına eşittir; Çıkış, virajdan sonraki düzlüğü de içerir."""
    def al(attr, yedek):
        v = getattr(rs, attr, None) if rs is not None else None
        return yedek if v is None else v
    p3 = al("throttle_full", None)
    if p3 is None:
        p3 = al("throttle_on", w.exit)
    nokta = [a]
    for p in (al("turn_in", w.entry), al("min_speed_dist", w.apex), p3):
        nokta.append(min(max(p, nokta[-1]), b))
    nokta.append(b)
    return [section_time(mine, x, y) - section_time(ref, x, y) for x, y in zip(nokta, nokta[1:])]


def aligned_laps(laps, path):
    """Turları aynı mesafe eksenine oturtur; oturmayan tur kendi mesafesiyle kalır."""
    out = []
    for L in laps:
        s = to_samples(L)
        a = align_to_reference(s, path)
        # Başlangıç çizgisinde eksen turun sonuna atlarsa hizalama geçersizdir
        mid = len(s["dist"]) // 2
        if a and abs(a["dist"][mid] - s["dist"][mid]) > ALIGN_MAX_SHIFT * s["dist"][-1]:
            a = None
        out.append(a or s)
    return out


LINE_MIN_M = 2.0        # bundan küçük çizgi farkı söylenmez (ölçüm gürültüsü)
EXIT_MIN_KMH = 4        # bundan küçük çıkış hızı farkı söylenmez
COAST_MIN_M = 15        # frenle gaz arasında en iyi geçişten bu kadar fazla boşta kalmak söylenir
TRAIL_MIN_M = 10        # iz freni: en iyi geçişte fren dönüşe bu kadar taşınmış ve bu kadar kısa kalmışsa söylenir
SIRA = {1: "birinci", 2: "ikinci", 3: "üçüncü", 4: "dördüncü", 5: "beşinci",
        6: "altıncı", 7: "yedinci", 8: "sekizinci", 9: "dokuzuncu"}


def de(n):
    """Sayıya doğru bulunma eki: de(6) -> "6'da", de(3) -> "3'te", de(11) -> "11'de"."""
    son = {1: "de", 2: "de", 3: "te", 4: "te", 5: "te", 6: "da", 7: "de", 8: "de", 9: "da"}
    onlar = {1: "da", 2: "de", 3: "da", 4: "ta", 5: "de", 6: "ta", 7: "te", 8: "de", 9: "da"}
    if n % 10:
        e = son[n % 10]
    elif n % 100:
        e = onlar[(n // 10) % 10]
    else:
        e = "de"
    return f"{n}'{e}"


def den(n):
    """Sayıya ayrılma eki: den(3) -> "3'ten", den(6) -> "6'dan" (bulunma ekine -n)."""
    return de(n) + "n"


def ye(n):
    """Sayıya yönelme eki: ye(3) -> "3'e", ye(6) -> "6'ya", ye(2) -> "2'ye", ye(10) -> "10'a"."""
    son = {1: "e", 2: "ye", 3: "e", 4: "e", 5: "e", 6: "ya", 7: "ye", 8: "e", 9: "a"}
    onlar = {1: "a", 2: "ye", 3: "a", 4: "a", 5: "ye", 6: "a", 7: "e", 8: "e", 9: "a"}
    if n % 10:
        e = son[n % 10]
    elif n % 100:
        e = onlar[(n // 10) % 10]
    else:
        e = "e"
    return f"{n}'{e}"


def buyuk_harf(s):
    """Cümlenin ilk harfini büyütür (Türkçe i -> İ)."""
    if not s:
        return s
    return {"i": "İ", "ı": "I"}.get(s[0], s[0].upper()) + s[1:]


def heading_at(s, d, step=6.0):
    """Turun d mesafesindeki gidiş yönü (birim vektör, x-z düzleminde)."""
    x1, z1 = _interp(s["dist"], s["pos_x"], d - step), _interp(s["dist"], s["pos_z"], d - step)
    x2, z2 = _interp(s["dist"], s["pos_x"], d + step), _interp(s["dist"], s["pos_z"], d + step)
    n = math.hypot(x2 - x1, z2 - z1) or 1.0
    return (x2 - x1) / n, (z2 - z1) / n


def side_offset(ref, d, x, z):
    """(x, z) noktası, referans turun d noktasına göre kaç metre sağda (+) / solda (-).
    GT7'de atan2(dz, dx) açısı artarken araç sağa döner (Tokyo saat yönü turlarıyla doğrulandı),
    bu yüzden sağ taraf yön vektörünün (-hz, hx) yönüdür."""
    hx, hz = heading_at(ref, d)
    rx, rz = _interp(ref["dist"], ref["pos_x"], d), _interp(ref["dist"], ref["pos_z"], d)
    return (x - rx) * (-hz) + (z - rz) * hx


def turn_side(ref, w):
    """Virajın yönü: "sag" ya da "sol"."""
    hx1, hz1 = heading_at(ref, w.entry)
    hx2, hz2 = heading_at(ref, w.exit)
    turn = math.atan2(hz2, hx2) - math.atan2(hz1, hx1)
    turn = (turn + math.pi) % (2 * math.pi) - math.pi
    return "sag" if turn > 0 else "sol"


def line_diff(mine, ref, w, rm):
    """Son turun çizgisi, virajın en iyi geçişine göre: [(nokta, metre, yan)].
    metre > 0 sağda demek. Noktalar: dönüşe giriş, tepe noktası, çıkış."""
    points = [("girişte", rm.turn_in if rm and rm.turn_in is not None else w.entry),
              ("tepe noktasında", rm.min_speed_dist if rm and rm.min_speed_dist is not None else w.apex),
              ("çıkışta", w.exit)]
    out = []
    for name, d in points:
        x, z = _interp(mine["dist"], mine["pos_x"], d), _interp(mine["dist"], mine["pos_z"], d)
        out.append((name, side_offset(ref, d, x, z)))
    return out


def line_issue(diffs, side):
    """En büyük çizgi farkı için ekran ve ses cümlesi; fark küçükse None."""
    name, m = max(diffs, key=lambda p: abs(p[1]))
    if abs(m) < LINE_MIN_M:
        return None
    yer = "sağda" if m > 0 else "solda"
    karsi = "sola" if m > 0 else "sağa"
    ic = (m > 0) == (side == "sag")      # farkın olduğu taraf virajın iç tarafı mı?
    taraf = "içeride" if ic else "dışarıda"
    ekran = f"{name} en iyi geçişinden {abs(m):.1f} m daha {yer}ydın ({taraf})"
    if name == "tepe noktasında" and ic:
        ses = f"tepe noktasında fazla içeri girdin, biraz {karsi} açıl"
    elif name == "tepe noktasında":
        ses = f"tepe noktasında {yer} kaldın, {karsi} doğru içe yaklaş"
    else:
        ses = f"{name} {yer} kaldın, en iyi hattın biraz daha {karsi}"
    nokta = {"girişte": "giris", "tepe noktasında": "tepe", "çıkışta": "cikis"}[name]
    return {"kod": "cizgi", "ekran": ekran, "ses": ses, "nokta": nokta, "yan": "sağ" if m > 0 else "sol"}


def coast_m(m):
    """Fren bitişi ile gaza basma arasındaki boşta kalma mesafesi (m). Bilinmiyorsa None."""
    if not m or m.brake_off is None or m.throttle_on is None:
        return None
    return max(0.0, m.throttle_on - m.brake_off)


def yanal_g(samples, pencere=15):
    """Her örnek için yanal ivme (G): hız × yön değişimi (konumdan; gt7-datalogger yöntemi).
    Konum sıçramalarındaki uçlar ~0,25 sn'lik ortanca süzgeçle temizlenir."""
    rate = _heading_rate(samples)
    ham = [abs(v / 3.6 * r) / 9.80665 for v, r in zip(samples["speed"], rate)]
    h = pencere // 2
    return [sorted(ham[max(0, i - h):i + h + 1])[len(ham[max(0, i - h):i + h + 1]) // 2]
            for i in range(len(ham))]


def tepe_g(samples, gs, w):
    """Virajın giriş-çıkış arasındaki yanal G'nin üst değeri (%90'lık dilim; tek uçlar sayılmaz)."""
    d = samples["dist"]
    vals = sorted(g for x, g in zip(d, gs) if w.entry <= x <= w.exit)
    return vals[int(0.9 * (len(vals) - 1))] if vals else None


G_AZ_ORAN = 0.92        # en iyi geçişin yanal G'sinin bundan azı = arabanın tutuşunu tam kullanmadın


def _fark(a, b):
    return None if a is None or b is None else a - b


def fazlar(me, rs, exit_diff, g_me=None, g_rs=None, sureler=None):
    """Virajın 4 aşaması (giriş, dönüş, geçiş, çıkış): bu tur ve en iyi geçiş değerleri.
    Her aşamada 'kotu' True ise o aşamada en iyi geçişten belirgin geride kalındı."""
    def g(m, a):
        return getattr(m, a, None) if m else None
    bd = brake_point_delta(me, rs)                    # + = daha geç fren
    sd = min_speed_delta(me, rs)                      # + = daha hızlı
    tr_me, tr_rs = g(me, "trail_m"), g(rs, "trail_m")
    co_me, co_rs = coast_m(me), coast_m(rs)
    gz = _fark(g(me, "throttle_on"), g(rs, "throttle_on"))  # + = gaza daha geç
    out = [
        {"ad": "Giriş", "ne": "fren noktası ve gücü",
         "fren_m": bd, "fren_guc": g(me, "brake_peak"), "fren_guc_en_iyi": g(rs, "brake_peak"),
         "kotu": bd is not None and abs(bd) > 15},
        {"ad": "Dönüş", "ne": "iz freni, tepe hızı ve yanal G",
         "iz_m": tr_me, "iz_m_en_iyi": tr_rs, "tepe_kmh": g(me, "min_speed"),
         "tepe_fark": sd, "g": g_me, "g_en_iyi": g_rs,
         "kotu": (sd is not None and sd < -3) or (tr_rs is not None and tr_me is not None
                                                   and tr_rs >= TRAIL_MIN_M and tr_rs - tr_me > TRAIL_MIN_M)},
        {"ad": "Geçiş", "ne": "frenden gaza boşta kalma",
         "bosta_m": co_me, "bosta_m_en_iyi": co_rs,
         "kotu": co_me is not None and co_rs is not None and co_me - co_rs > COAST_MIN_M},
        {"ad": "Çıkış", "ne": "gaz ve çıkış hızı",
         "gaz_m": gz, "cikis_fark": exit_diff,
         "kotu": (gz is not None and gz > 15) or (exit_diff is not None and exit_diff < -EXIT_MIN_KMH)},
    ]
    # Her aşamada kaç saniye kaybedildi: 0,1 sn'den fazla kayıp da "kötü" sayılır
    for f, sn in zip(out, sureler or []):
        f["kayip"] = round(sn, 3)
        f["kotu"] = f["kotu"] or sn >= FAZ_KOTU_S
    return out


FAZ_KOTU_S = 0.10


def faz_ozeti(r):
    """Tur notları için: zamanın çoğunun gittiği aşama ve düzlük payı ("zamanın çoğu çıkışta gitti,
    0.12 sn'si sonraki düzlükte"). Söylenecek bir şey yoksa ""."""
    if r.get("kaza") or r["delta"] <= 0.1:
        return ""
    parca = []
    fz = [f for f in r.get("fazlar", []) if f.get("kayip") is not None]
    if fz:
        en = max(fz, key=lambda f: f["kayip"])
        if en["kayip"] >= 0.05 and en["kayip"] >= 0.5 * r["delta"]:
            parca.append(f"zamanın çoğu {FAZ_DE[en['ad']]} gitti ({en['kayip']:.2f} sn)")
    dz = r.get("duzluk_s") or 0.0
    if dz >= 0.05:
        neden = (" (düzlükte gaz kestin)" if any(not k["once"] for k in r.get("kesmeler", [])) else
                 " (yavaş çıkışın bedeli)" if (r.get("exit_diff") or 0) < -EXIT_MIN_KMH else "")
        parca.append(f"{dz:.2f} sn'si virajdan sonraki düzlükte{neden}")
    return "; ".join(parca)


def compare(lap, pool, corners):
    """Her virajı, temiz turlar arasında o virajdaki EN İYİ performansınla karşılaştırır."""
    base = to_samples(min(pool, key=lambda L: L["lap_ms"]))
    wins = place_corners(corners, base)
    path = ReferencePath(base)
    mine = aligned_laps([lap], path)[0]
    others = aligned_laps(pool, path)
    my_m = measure(LapTrace(mine), wins)
    their_m = [measure(LapTrace(s), wins) for s in others]
    en_iyi = min(range(len(pool)), key=lambda i: pool[i]["lap_ms"])
    end = base["dist"][-1]
    orta = section_bounds(wins, end)
    bounds = bolum_sinirlari(wins, end, [my_m, their_m[en_iyi]])
    try:
        g_mine = yanal_g(mine)
    except Exception:
        g_mine = None
    g_cache = {}
    res = []
    secilen = {}          # viraj no -> en iyi geçişin olduğu tur (pool sırası)
    for w, (a, b), (_, ob) in zip(wins, bounds, orta):
        k = min(range(len(others)), key=lambda i: section_time(others[i], a, b))
        secilen[w.n] = k
        delta = section_time(mine, a, b) - section_time(others[k], a, b)
        me, rs = my_m.get(w.n), their_m[k].get(w.n)
        ref = others[k]
        # Virajdan sonraki düzlükte (eskiden sonraki virajın sayılan kısmı) kaybedilen süre
        duzluk_s = (section_time(mine, ob, b) - section_time(ref, ob, b)) if b - ob >= DUZLUK_MIN_M else 0.0
        kaza = kaza_mi(mine, ref, a, b, rs, delta)
        try:
            sureler = faz_sureleri(mine, ref, rs, w, a, b)
        except Exception:
            sureler = None
        side = turn_side(ref, w)
        diffs = line_diff(mine, ref, w, rs)
        exit_diff = _interp(mine["dist"], mine["speed"], w.exit) - _interp(ref["dist"], ref["speed"], w.exit)
        issues = []   # öncelik sırasıyla: fren, iz freni, çizgi, en düşük hız, boşta kalma, gaz, çıkış, vites
        diff = brake_point_delta(me, rs)
        if diff is not None and diff < -15:
            issues.append({"kod": "fren_erken", "ekran": f"frene {-diff:.0f} m erken bastın",
                           "ses": "frene erken bastın, biraz daha geç bas"})
        elif diff is not None and diff > 15:
            issues.append({"kod": "fren_gec", "ekran": f"frene {diff:.0f} m geç bastın, viraja fazla hızlı girdin",
                           "ses": "frene geç kaldın, biraz daha erken bas"})
        if me and rs and me.trail_m is not None and rs.trail_m is not None \
                and rs.trail_m >= TRAIL_MIN_M and rs.trail_m - me.trail_m > TRAIL_MIN_M:
            issues.append({"kod": "iz_freni",
                           "ekran": f"freni dönüşe girmeden bıraktın (iz freni {me.trail_m:.0f} m, "
                                    f"en iyi geçişinde {rs.trail_m:.0f} m)",
                           "ses": "freni dönüşe doğru yavaş yavaş bırak"})
        li = line_issue(diffs, side)
        if li:
            issues.append(li)
        sdiff = min_speed_delta(me, rs)
        if sdiff is not None and sdiff < -3:
            issues.append({"kod": "orta_yavas",
                           "ekran": f"virajın en yavaş noktasında {-sdiff:.0f} km/s daha yavaştın",
                           "ses": "virajın ortasında fazla yavaşladın, hızı daha çok taşı"})
        if me and rs and me.throttle_on is not None and rs.throttle_on is not None \
                and me.throttle_on - rs.throttle_on > 15:
            issues.append({"kod": "gaz_gec", "ekran": f"çıkışta gaza {me.throttle_on - rs.throttle_on:.0f} m geç bastın",
                           "ses": "çıkışta gaza daha erken bas"})
        gaz_gec = any(i["kod"] == "gaz_gec" for i in issues)
        co_me, co_rs = coast_m(me), coast_m(rs)
        if not gaz_gec and co_me is not None and co_rs is not None and co_me - co_rs > COAST_MIN_M:
            issues.append({"kod": "bosta",
                           "ekran": f"frenle gaz arasında {co_me:.0f} m boşta kaldın "
                                    f"(en iyi geçişinde {co_rs:.0f} m)",
                           "ses": "frenden çıkınca hemen gaza geç, boşta kalma"})
        if exit_diff < -EXIT_MIN_KMH:
            issues.append({"kod": "cikis_yavas", "ekran": f"virajdan {-exit_diff:.0f} km/s daha yavaş çıktın",
                           "ses": "çıkış hızın düşük, gazı daha erken ve düzgün aç"})
        if me and rs and me.min_speed_gear is not None and rs.min_speed_gear \
                and me.min_speed_gear != rs.min_speed_gear and rs.min_speed_gear != 15 \
                and me.min_speed_gear != 15:
            g = rs.min_speed_gear
            issues.append({"kod": "vites", "ekran": f"en iyi geçişinde burayı {g}. viteste geçtin, "
                                                   f"şimdi {me.min_speed_gear}. vitestesin",
                           "ses": f"{SIRA.get(g, str(g))} vitese " + ("düş" if g < me.min_speed_gear else "çık")})
        g_me = g_rs = None
        if g_mine is not None:
            try:
                if k not in g_cache:
                    g_cache[k] = yanal_g(ref)
                g_me, g_rs = tepe_g(mine, g_mine, w), tepe_g(ref, g_cache[k], w)
            except Exception:
                pass
        reasons = [i["ekran"] for i in issues if i["kod"] != "vites"] if delta > 0.05 else []
        if delta > 0.05 and g_me and g_rs and g_rs > 0.5 and g_me < G_AZ_ORAN * g_rs:
            reasons.append(f"arabanın tutuşunu tam kullanmadın (yanal {g_me:.2f} G, "
                           f"en iyi geçişinde {g_rs:.2f} G)")
        if kaza:
            # Kaza / pistten çıkma: teknik değil kaza; bu virajda ne düzeltme ne övgü (sesli koç da susar)
            issues, reasons, diff = [], [f"{kaza}: bu viraj için tavsiye yok"], None
        res.append({"no": w.n, "delta": delta, "issues": issues,
                    "ref_s": round(section_time(ref, a, b), 3),
                    "reasons": reasons, "kaza": kaza,
                    "gear_reason": next((i["ekran"] for i in issues if i["kod"] == "vites"), None)
                    if delta > 0.05 and not kaza else None,
                    "line": diffs, "side": side, "exit_diff": exit_diff, "fren_m": diff,
                    "duzluk_s": round(duzluk_s, 3),
                    "bolum": (a / end, b / end) if end else None,
                    "fazlar": fazlar(me, rs, exit_diff, g_me, g_rs, sureler),
                    "gear_high": bool(gear_high(me)) and not kaza})
    # Ek ipuçları (sadece ekranda): gaz pompalama, fren basıncı, fazla direksiyon, düzlükte gaz kesme
    try:
        ek = viraj_ipuclari(mine, lambda n: others[secilen[n]], wins, my_m,
                            lambda n: their_m[secilen[n]].get(n))
        kesmeler = duzluk_kesmeleri(mine, others[en_iyi], wins,
                                    lambda n: their_m[en_iyi].get(n), bounds)
    except Exception:
        ek, kesmeler = {}, []
    for r in res:
        if r["kaza"]:          # kazadan sonra gaz kesmek / fren normal: ipucu yok
            r["kesmeler"], r["ipuclari"] = [], []
            continue
        r["kesmeler"] = [k for k in kesmeler if k["no"] == r["no"]]
        yeni = ek.get(r["no"], []) + ([{"kod": "duzluk", "ekran": kesme_cumlesi(max(r["kesmeler"],
                                                                                    key=lambda k: k["sn"])),
                                         "ses": "düzlükte tam gaz kal"}] if r["kesmeler"] else [])
        r["ipuclari"] = [i["ekran"] for i in yeni]
        # Sesli koç için en düşük öncelik: mevcut sorunlardan sonra, vitesten önce
        sesli = [i for i in yeni if i.get("ses")]
        vi = next((k for k, i in enumerate(r["issues"]) if i["kod"] == "vites"), len(r["issues"]))
        r["issues"][vi:vi] = sesli
        if r["delta"] > 0.05:
            r["reasons"] += [i["ekran"] for i in yeni if i["kod"] != "duzluk"]
    return res


def fren_kaymasi_uygula(cmp_res, kayma):
    """Rekor turunda fren noktası öne alındıysa (güvenlik payı / kendi fren gücü, gt7_fren_sesi): "erken /
    geç fren" o kaymış noktaya göre yeniden yazılır. Fren uyarısıyla frenleyene "erken bastın" denmez."""
    for r in cmp_res or []:
        k = (kayma or {}).get(r["no"])
        if not k or r.get("kaza") or r.get("fren_m") is None:
            continue
        diff = r["fren_m"] + k
        eski = [i for i in r["issues"] if i["kod"] in ("fren_erken", "fren_gec")]
        ekranlar = {i["ekran"] for i in eski}
        r["issues"] = [i for i in r["issues"] if i not in eski]
        r["reasons"] = [x for x in r["reasons"] if x not in ekranlar]
        yeni = None
        if diff < -15:
            yeni = {"kod": "fren_erken", "ekran": f"frene {-diff:.0f} m erken bastın (fren noktana göre)",
                    "ses": "frene erken bastın, biraz daha geç bas"}
        elif diff > 15:
            yeni = {"kod": "fren_gec", "ekran": f"frene {diff:.0f} m geç bastın (fren noktana göre)",
                    "ses": "frene geç kaldın, biraz daha erken bas"}
        if yeni:
            r["issues"].insert(0, yeni)
            if r["delta"] > 0.05:
                r["reasons"].insert(0, yeni["ekran"])
        r["fren_m"] = diff


def kilit_ekle(cmp_res, olaylar):
    """Teker kilitlenmesi virajın sorunu olur: en öne "kilit" eklenir
    (fren grubunda), "frenin başında sert bas" ipucu çıkarılır (kilitlenmeyle çelişir). Koç virajdan önce
    "frene biraz daha yumuşak bas" der, tur sonu sesi de bunu söyleyebilir. olaylar: wheel_events."""
    kilit = {}
    for e in olaylar or []:
        if e["tip"] == "kilit" and e["viraj"] and e["viraj"] not in kilit:
            kilit[e["viraj"]] = e["teker"]
    for r in cmp_res or []:
        teker = kilit.get(r["no"])
        if not teker or r.get("kaza"):
            continue
        r["kilit"] = teker
        sert = [i for i in r["issues"] if i["kod"] == "fren_bas"]
        ekranlar = {i["ekran"] for i in sert}
        r["issues"] = [i for i in r["issues"] if i not in sert]
        r["reasons"] = [x for x in r["reasons"] if x not in ekranlar]
        i = {"kod": "kilit", "teker": teker,
             "ekran": f"{teker} kilitlendi (frene biraz daha yumuşak bas, sonra yavaş yavaş bırak)",
             "ses": "frene biraz daha yumuşak bas"}
        r["issues"].insert(0, i)
        if r["delta"] > 0.05:
            r["reasons"].insert(0, i["ekran"])


def ideal_ms(pool, corners):
    """Teorik ideal tur: en iyi tur − her virajda o virajın en iyi geçişine göre kaybı.
    (Bölüm sürelerinin toplamı kullanılmaz: kaydın başı/sonu oyunun tur saatinden birkaç yüz ms farklı
    olabildiği için ideal, hiç gelişme yokken bile en iyiden hızlı çıkabiliyordu.)"""
    best = min(pool, key=lambda L: L["lap_ms"])
    return int(round(best["lap_ms"] - 1000 * sum(viraj_kazanclari(pool, corners).values())))


def viraj_kazanclari(pool, corners):
    """En iyi turun her virajda, o virajın en iyi geçişine göre kaybettiği süre (sn): {viraj no: sn}.
    Toplamı = en iyi tur − ideal tur (hedef süre analizi için)."""
    best = min(pool, key=lambda L: L["lap_ms"])
    base = to_samples(best)
    wins = place_corners(corners, base)
    others = aligned_laps(pool, ReferencePath(base))
    k = pool.index(best)
    out = {}
    sinir = bolum_sinirlari(wins, base["dist"][-1], [measure(LapTrace(others[k]), wins)])
    for w, (a, b) in zip(wins, sinir):
        out[w.n] = max(0.0, section_time(others[k], a, b) - min(section_time(s, a, b) for s in others))
    return out


def corner_bests(pool, corners):
    """Her virajda bölüm süresi en iyi olan geçişin değerleri (viraj uyarısı için)."""
    base = to_samples(min(pool, key=lambda L: L["lap_ms"]))
    wins = place_corners(corners, base)
    bounds = section_bounds(wins, base["dist"][-1])
    others = aligned_laps(pool, ReferencePath(base))
    ms = [measure(LapTrace(s), wins) for s in others]
    out = {}
    for w, (a, b) in zip(wins, bounds):
        k = min(range(len(others)), key=lambda i: section_time(others[i], a, b))
        m = ms[k].get(w.n)
        if not m or m.min_speed is None:
            continue
        out[w.n] = {
            "min": m.min_speed,
            "gear": m.min_speed_gear if m.min_speed_gear not in (None, 15) else None,
            "brake_m": (m.min_speed_dist - m.brake_on)
            if m.brake_on is not None and m.min_speed_dist is not None else None,
        }
    return out


def corner_table(lap, corners):
    """Haritadaki tablo için her virajın değerleri."""
    s = to_samples(lap)
    wins = place_corners(corners, s)
    ms = measure(LapTrace(s), wins)
    rows = {}
    for w in wins:
        m = ms[w.n]
        rows[w.n] = {
            "entry": _interp(s["dist"], s["speed"], w.entry),
            "min": m.min_speed,
            "exit": _interp(s["dist"], s["speed"], w.exit),
            "gear": m.min_speed_gear,
            "brake_m": (m.min_speed_dist - m.brake_on)
            if m.brake_on is not None and m.min_speed_dist is not None else None,
        }
    return rows


def wheel_group(wheels):
    """Teker listesini doğal Türkçeye çevirir: ["fl","fr"] -> "ön tekerler"."""
    w = set(wheels)
    if w == {"fl", "fr", "rl", "rr"}:
        return "dört teker"
    if w == {"fl", "fr"}:
        return "ön tekerler"
    if w == {"rl", "rr"}:
        return "arka tekerler"
    if len(w) == 1:
        return WHEEL_NAMES[next(iter(w))] + " teker"
    return ", ".join(WHEEL_NAMES[x] for x in wheels) + " tekerler"


def wheel_events(lap, corners, limit=3):
    """Turdaki kilitlenme ve patinajlar, en kötüden başlayarak:
    [{"tip": "kilit"/"patinaj", "viraj": no ya da None, "teker": "ön tekerler", "metin": ...}]"""
    s = to_samples(lap)
    total = s["dist"][-1]
    found = [e for e in detect_events(s) if e["type"] in ("lockup", "wheelspin")]
    found.sort(key=lambda e: abs(e["severity"] - 1), reverse=True)
    out, seen = [], set()
    for e in found:
        mid = (e["start_dist"] + e["end_dist"]) / 2
        near = min(corners, key=lambda c: abs(c["frac"] * total - mid), default=None)
        no = near["no"] if near and abs(near["frac"] * total - mid) <= EVENT_CORNER_M else None
        tip = "kilit" if e["type"] == "lockup" else "patinaj"
        if (tip, no) in seen:
            continue
        seen.add((tip, no))
        teker = wheel_group(e["wheels"])
        fiil = "kilitlendi" if tip == "kilit" else "patinaj yaptı"
        where = f"Viraj {de(no)}" if no else "Pistte"
        out.append({"tip": tip, "viraj": no, "teker": teker, "metin": f"{where} {teker} {fiil}."})
    return out[:limit]


def fuel_laps_left(fuel_laps, fuel_level, car):
    """Son turların tüketimine göre yakıtın kaç tur daha yeteceği (bilinmiyorsa None)."""
    p = project_strategy(fuel_level, 0, car, "", fuel_laps)
    if p is None or p.laps_to_empty is None:
        return None
    return p.laps_to_empty


def lap_fuel(number, lap_ms, used, car):
    return LapFuel(number=number, time_ms=lap_ms, fuel_consumed=used, car_id=car)
