# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Ek viraj ipuçları
Ekranda ayrıntılı; sesli koç bunları sadece virajda daha önemli bir sorun yoksa,
çok kısa söyler ("gazı tek seferde aç", "frenin başında sert bas", "düzlükte tam gaz kal",
"girişte yavaş ol, direksiyonu az çevir").
Fikirler gt7-timetrials sitesinin tur karşılaştırma belgesinden (docs/telemetry.md,
"Per corner" ve "Extra lifts and braking"); kod bu proje için yazıldı.

- Gaz pompalama: çıkışta tam gaza gelmeden gazı birkaç kez açıp kapatmak.
- Fren basıncı: frenin başında tam frende (%90 üstü) en iyi geçişten belirgin kısa kalmak.
- Fazla direksiyon: bu virajda, turun geri kalanına göre belirgin fazla teker açısı
  (önden kayma ya da daha dar çizgi). Kol / direksiyon farkı olmasın diye sürücünün
  kendi tur içi oranıyla karşılaştırılır. Teker açısı sadece C biçiminde gelir.
- Direksiyon zamanlaması: direksiyonun en çok çevrildiği
  ana en iyi geçişten belirgin geç ulaşmak (dönüşe geç başlama, gaza geçiş de gecikir). C biçimi.
- Düzlükte gaz kesme / fren: virajların fren-tam gaz bölgesi dışında, en iyi geçişte
  tam gazla geçilen yerde gaz kesmek ya da frene dokunmak (en az 0,03 sn kaybettiren).
"""
import os
import sys

from gt7_yol import DATA_DIR

if os.path.join(DATA_DIR, "alinan") not in sys.path:
    sys.path.insert(0, os.path.join(DATA_DIR, "alinan"))

from app.processing.analysis import _interp  # noqa: E402

SAW_DROP = 15          # gaz bu kadar puan düşerse "kapattı" sayılır
SAW_MIN = 2            # en az bu kadar kapatıp açma = pompalama (en iyi geçişte en fazla 1)
FULL_BRAKE = 90        # tam fren eşiği (%)
FULL_BRAKE_DIFF_M = 15  # tam frende bu kadar metre kısa kalmak söylenir
STEER_MIN_RAD = 0.05   # en iyi geçişte bundan az teker açısı olan viraj oran hesabına girmez
STEER_RATIO = 1.3      # tur içi oranın bu katı = fazla direksiyon
STEER_LATE_M = 15      # direksiyonun en çok çevrildiği an en iyi geçişten bu kadar metre geçse söylenir
LIFT_MIN_M = 10        # düzlükte en az bu kadar metre gaz kesme / fren
LIFT_MIN_S = 0.03      # ve en az bu kadar zaman kaybı
LIFT_GAP = 20          # gaz, en iyi geçişten bu kadar puan düşük ve...
LIFT_THR = 90          # ...bundan az olmalı
STEP_M = 2.0           # düzlük taraması adımı (m)
MERGE_M = 10           # aralarında bundan az mesafe olan iki kesme birleşir


def _deger(s, key, d):
    v = s.get(key)
    if not v:
        return None
    return _interp(s["dist"], v, d)


def _aralik(s, key, a, b):
    """s turunun a-b metre arasındaki key değerleri (None olanlar atlanır)."""
    d, v = s["dist"], s.get(key) or []
    return [(x, y) for x, y in zip(d, v) if a <= x <= b and y is not None]


def pompalama(s, a, b):
    """a-b arasında tam gaza (95) gelmeden gazın kaç kez belirgin kapatıldığı."""
    sayi, tepe = 0, None
    for _, g in _aralik(s, "throttle", a, b):
        if g >= 95:
            break
        if tepe is None or g > tepe:
            tepe = g
        elif tepe - g >= SAW_DROP:
            sayi += 1
            tepe = g
    return sayi


def tam_fren_m(s, a, b):
    """a-b arasında fren %90 üstündeyken gidilen metre."""
    pts = _aralik(s, "brake", a, b)
    return sum(pts[i][0] - pts[i - 1][0] for i in range(1, len(pts))
               if pts[i][1] >= FULL_BRAKE and pts[i - 1][1] >= FULL_BRAKE)


def en_cok_aci(s, a, b):
    vals = [abs(v) for _, v in _aralik(s, "wheel_angle", a, b)]
    return max(vals) if vals else None


def en_cok_aci_yeri(s, a, b):
    """a-b arasında teker açısının en büyük olduğu mesafe (m) ya da None."""
    pts = [(x, abs(v)) for x, v in _aralik(s, "wheel_angle", a, b)]
    return max(pts, key=lambda p: p[1])[0] if pts else None


def ortanca(v):
    v = sorted(v)
    return v[len(v) // 2] if v else None


def viraj_ipuclari(mine, ref_of, wins, me_m, rs_of):
    """Her viraj için ek ipuçları: {viraj_no: [{"kod", "ekran", "ses" (sesli söylenebilirse)}]}.
    ref_of(no): o virajın en iyi geçişinin turu; rs_of(no): onun ölçümleri."""
    out = {w.n: [] for w in wins}
    acilar = {}
    for w in wins:
        ref, me, rs = ref_of(w.n), me_m.get(w.n), rs_of(w.n)
        # Gaz pompalama: en yavaş noktadan çıkışa
        a = (rs.min_speed_dist if rs and rs.min_speed_dist is not None else w.apex)
        b = w.exit + 30
        n_me, n_rs = pompalama(mine, a, b), pompalama(ref, a, b)
        if n_me >= SAW_MIN and n_rs <= 1:
            out[w.n].append({"kod": "pompa", "ekran": f"çıkışta gazı {n_me} kez açıp kapadın; gazı tek "
                                                      "seferde, yavaş yavaş aç (araba dengede kalır)",
                             "ses": "gazı tek seferde aç"})
        # Fren basıncı: frenin başından virajın en yavaş noktasına
        bas = [m.brake_on for m in (me, rs) if m and m.brake_on is not None]
        if bas:
            a, b = min(bas) - 5, (rs.min_speed_dist if rs and rs.min_speed_dist is not None else w.apex)
            f_me, f_rs = tam_fren_m(mine, a, b), tam_fren_m(ref, a, b)
            if f_rs >= FULL_BRAKE_DIFF_M and f_rs - f_me >= FULL_BRAKE_DIFF_M:
                out[w.n].append({"kod": "fren_bas",
                                 "ekran": (f"tam frende (%90 üstü) {f_me:.0f} m kaldın" if f_me >= 1 else
                                           "frene hiç tam (%90 üstü) basmadın")
                                          + f", en iyi geçişinde {f_rs:.0f} m: frenin başında sert bas, "
                                            "sonra yavaş yavaş bırak",
                                 "ses": "frenin başında sert bas"})
        # Direksiyon: oranlar sonra tur içi ortancayla karşılaştırılır
        a_me, a_rs = en_cok_aci(mine, w.entry, w.exit), en_cok_aci(ref, w.entry, w.exit)
        if a_me is not None and a_rs is not None and a_rs >= STEER_MIN_RAD:
            acilar[w.n] = a_me / a_rs
            y_me, y_rs = en_cok_aci_yeri(mine, w.entry, w.exit), en_cok_aci_yeri(ref, w.entry, w.exit)
            if y_me is not None and y_rs is not None and y_me - y_rs >= STEER_LATE_M:
                out[w.n].append({"kod": "direksiyon_gec", "ses": "dönüşe biraz daha erken başla",
                                 "ekran": f"direksiyonun en çok çevrildiği ana {y_me - y_rs:.0f} m geç ulaştın: "
                                          "dönüşe daha erken ve kararlı başla, sonra gaza erken geç"})
    tipik = ortanca(list(acilar.values())) if len(acilar) >= 3 else None
    if tipik:
        for n, oran in acilar.items():
            if oran >= STEER_RATIO * tipik:
                fazla = round(100 * (oran / tipik - 1))
                out[n].append({"kod": "direksiyon", "ses": "girişte biraz yavaş ol, direksiyonu az çevir",
                               "ekran": f"burada turun geri kalanına göre %{fazla} fazla direksiyon "
                                        "çevirdin: önden kayıyor olabilir; girişte biraz yavaş ol, "
                                        "gazı açarken direksiyonu aç"})
    return out


def duzluk_kesmeleri(mine, ref, wins, rs_of, bounds):
    """Virajların fren-tam gaz bölgesi dışında, en iyi geçişte tam gazla geçilen yerde
    gaz kesme ya da fren: [{"no": viraj, "once": bool, "m": metre, "sn": kayıp, "fren": bool}]"""
    bolge = []
    for w in wins:
        rs = rs_of(w.n)
        a = (rs.brake_on if rs and rs.brake_on is not None else w.entry) - 10
        b = (rs.throttle_full if rs and rs.throttle_full is not None else w.exit) + 20
        bolge.append((min(a, w.entry - 10), max(b, w.exit + 10)))
    son = min(mine["dist"][-1], ref["dist"][-1])

    def serbest(d):
        return not any(a <= d <= b for a, b in bolge)

    def kotu(d):
        if not serbest(d):
            return None
        rb = _deger(ref, "brake", d) or 0
        if rb > 5:
            return None
        mb = _deger(mine, "brake", d) or 0
        if mb > 5:
            return "fren"
        mt, rt = _deger(mine, "throttle", d), _deger(ref, "throttle", d)
        if mt is not None and rt is not None and mt < LIFT_THR and mt < rt - LIFT_GAP:
            return "gaz"
        return None

    def fark(d):
        return _interp(mine["dist"], mine["t"], d) - _interp(ref["dist"], ref["t"], d)

    out, d = [], 20.0
    while d < son - 20:
        tur = kotu(d)
        if not tur:
            d += STEP_M
            continue
        bas, fren, bit = d, tur == "fren", d
        while d < son - 20 and d - bit < MERGE_M:   # 10 m'den kısa aralıklar tek kesme sayılır
            k = kotu(d)
            if k:
                fren = fren or k == "fren"
                bit = d + STEP_M
            d += STEP_M
        d = bit
        if bit - bas >= LIFT_MIN_M:
            # Kayıp: başlangıçtan tekrar tam gaza gelene kadar (en fazla 200 m)
            e = bit
            while e < min(son, bit + 200) and (_deger(mine, "throttle", e) or 0) < LIFT_THR:
                e += STEP_M
            kayip = fark(e) - fark(bas)
            if kayip >= LIFT_MIN_S:
                i = next((k for k, (a, b) in enumerate(bounds) if a <= bas < b), len(bounds) - 1)
                w = wins[i]
                out.append({"no": w.n, "once": bas < w.apex, "m": round(bit - bas),
                            "sn": round(kayip, 2), "fren": fren})
    return out


def kesme_cumlesi(k):
    yer = f"Viraj {k['no']} {'öncesi' if k['once'] else 'sonrası'} düzlükte"
    ne = "frene dokundun" if k["fren"] else "gaz kestin"
    return f"{yer} {k['m']} m {ne} ({k['sn']:.2f} sn kaybettin); en iyi geçişinde orası tam gazdı"

