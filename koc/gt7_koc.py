# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Ana döngü (Koc sınıfı; arayüz gt7_arayuz.py başlatır)
- PS5'ten telemetriyi alır, her turu kaydeder (turlar/ klasörü)
- Virajları çıkarır, pist hafızasını tutar (referanslar/ klasörü)
- Her tur sonunda viraj viraj karşılaştırır, Türkçe tavsiye ve sesli özet üretir
"""
import csv
import json
import bisect
import math
import os
import re
import socket
import struct
import threading
import time

from gt7_paket import (decrypt_packet, parse, sure, vites_yazi, send_heartbeat,
                      RECV_PORT, IP_FILE)
from gt7_pistler import (corners_for_lap, distance_to_path, load_catalog,
                         lap_on_path, write_last, FAR_LIMIT)
from gt7_pist_tanima import PistTanima
from gt7_ipucu import kesme_cumlesi
from gt7_kopru import (LINE_MIN_M, compare, corner_table, de, faz_ozeti, fren_kaymasi_uygula, fuel_laps_left,
                       ideal_ms, kilit_ekle, lap_fuel,
                       parse_packet, wheel_events)
from gt7_canli import CanliKoc, ayar_oku, esikler, gecmise_ekle, onemli_virajlar, vites_turu_tahmin
from gt7_konusma import acik_yaz
from gt7_yorum import ses_ozeti
from gt7_ayar import AyarKocu, tur_desenleri
from gt7_cekis import ADLAR as CEKIS_ADLARI, dagilim_yazi, ogren as cekis_ogren, cekis_turu
from gt7_fren_sesi import FREN_PAYI_M, Beeper, BrakeCountdown, brake_points, kendi_kaymalari
from gt7_kalibrasyon import ReactionTest, load_delay, save_delay
from gt7_tahmin import library_warner, track_summary
from gt7_telemetri import CanliOlcer, vites_sayisi
from gt7_muhendis import Muhendis
from gt7_bul import Tarayici
from gt7_analiz import (KURU_YAKIN, fren_aliskanligi, islak_tur, teker_tekrari, tempo, ters_yon,
                        tur_ozeti, tur_ozeti_satiri, tutarlilik)
from gt7_veri import araba_adi, pist_bilgi
from gt7_rekor import rekor_dili, rekor_ekle, rekor_karsilastir, rekor_turu
import gt7_tt
import gt7_strateji
import gt7_hedef
import gt7_karsilastir
import gt7_rapor
from gt7_viraj_adlari import adlandir, eslestir
from gt7_tur_kurallari import (ISINMA_C, LapClock, cizgide_basladi, drop_partial, isinma_turu,
                               lap_change_ok, lastik_ort, note_packet, off_track_count,
                               onceki_son, pit_turu,
                               race_start, records, span_limit, tam_tur, tasmalar,
                               time_problem)

from gt7_yol import USER_DIR as BASE
LAP_DIR = os.path.join(BASE, "turlar")


# ---------------- Yardımcılar ----------------
def smooth(vals, w=7):
    out, n = [], len(vals)
    for i in range(n):
        a, b = max(0, i - w), min(n, i + w + 1)
        out.append(sum(vals[a:b]) / (b - a))
    return out


# ---------------- Viraj tespiti ----------------
def find_corners(lap):
    sp = smooth(lap["speed"], 10)
    d = lap["dist"]
    n = len(sp)
    cands = []
    for i in range(n):
        # +-80 m içindeki en düşük hız noktası mı?
        j = i
        while j > 0 and d[i] - d[j] < 80:
            j -= 1
        k = i
        while k < n - 1 and d[k] - d[i] < 80:
            k += 1
        if sp[i] > min(sp[j:k + 1]):
            continue
        # Öncesinde (300 m) yeterince hızlı mıydı?
        j2 = i
        while j2 > 0 and d[i] - d[j2] < 300:
            j2 -= 1
        if max(sp[j2:i + 1]) - sp[i] < 12:
            continue
        if cands and d[i] - d[cands[-1]] < 120:
            if sp[i] < sp[cands[-1]]:
                cands[-1] = i
            continue
        cands.append(i)

    total = d[-1]
    return [{"no": num, "frac": d[i] / total, "x": lap["x"][i], "z": lap["z"][i]}
            for num, i in enumerate(cands, 1)]


# ---------------- Harita (HTML) ----------------
def speed_color(v, vmin, vmax):
    t = 0 if vmax == vmin else (v - vmin) / (vmax - vmin)
    t = max(0.0, min(1.0, t))
    # yavaş = kırmızı, hızlı = yeşil
    r = int(230 * (1 - t) + 40 * t)
    g = int(60 * (1 - t) + 200 * t)
    b = int(60 * (1 - t) + 90 * t)
    return f"rgb({r},{g},{b})"


GECMIS_TUR = 20      # pist + araba için saklanan viraj geçmişi (tur)
GECMIS_GOSTER = 10   # haritadaki geçmiş tablosunda gösterilen tur


def delta_color(d, lim=0.3):
    """Viraj farkı rengi: kazanç yeşil, 0 gri, kayıp kırmızı (lim saniyede tam renk)."""
    if d is None:
        return "#555"
    t = max(-1.0, min(1.0, d / lim))
    gri = (110, 110, 110)
    hedef = (231, 76, 60) if t > 0 else (46, 204, 113)
    a = abs(t)
    r, g, b = (int(gri[i] * (1 - a) + hedef[i] * a) for i in range(3))
    return f"rgb({r},{g},{b})"


def isaretli(v):
    """+0.21 / -0.13 / 0.00 (eksi sıfır yazmaz)."""
    return "0.00" if abs(v) < 0.005 else f"{v:+.2f}"


def gecmis_tablosu(corners, gecmis):
    """Her virajın son turlardaki +/- süreleri, renkli tablo."""
    son = (gecmis or [])[-GECMIS_GOSTER:][::-1]
    if not son:
        return ""
    bas = "".join(f'<th>{g["saat"]}<br><small>{sure(g["sure"])}</small></th>' for g in son)
    rows = []
    for c in corners:
        k = str(c["no"])
        vals = [g["v"].get(k) for g in son]
        hucre = "".join(f'<td style="background:{delta_color(v)};color:#fff;text-align:center">'
                        f'{"" if v is None else isaretli(v)}</td>' for v in vals)
        tum = [g["v"][k] for g in gecmis if g["v"].get(k) is not None]
        ort = sum(tum) / len(tum) if tum else None
        hucre += (f'<td style="background:{delta_color(ort)};color:#fff;text-align:center"><b>'
                  f'{"" if ort is None else isaretli(ort)}</b></td>')
        rows.append(f"<tr><td>{c['no']}</td>{hucre}</tr>")
    return (f'<h3>Viraj geçmişi (son {len(son)} tur, kendi en iyi geçişine göre sn)</h3>'
            '<p class="k">Yeşil = kazandın, kırmızı = kaybettin. En sağda kayıtlı tüm turların ortalaması.</p>'
            f'<div class="tablo"><table><tr><th>Viraj</th>{bas}<th>Ortalama</th></tr>{"".join(rows)}</table></div>')


def map_body(best, corners, laps_info, last_compare, gecmis=None):
    """Harita, viraj tablosu ve son turlar (HTML parçası). Arayüz de bunu gösterir."""
    xs, zs = best["x"], best["z"]
    minx, maxx, minz, maxz = min(xs), max(xs), min(zs), max(zs)
    w, h = maxx - minx or 1, maxz - minz or 1
    size = 600
    sc = size / max(w, h)
    pad = 30
    vbw, vbh = w * sc + 2 * pad, h * sc + 2 * pad

    def P(x, z):
        return (pad + (x - minx) * sc, pad + (z - minz) * sc)

    vmin, vmax = min(best["speed"]), max(best["speed"])
    segs = []
    step = 3
    for i in range(0, len(xs) - step, step):
        x1, y1 = P(xs[i], zs[i])
        x2, y2 = P(xs[i + step], zs[i + step])
        segs.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                    f'stroke="{speed_color(best["speed"][i], vmin, vmax)}" '
                    f'stroke-width="5" stroke-linecap="round"/>')
    sx, sy = P(xs[0], zs[0])
    marks = [f'<rect x="{sx-6:.1f}" y="{sy-6:.1f}" width="12" height="12" fill="#fff"/>']
    deltas = {r["no"]: r for r in (last_compare or [])}
    for c in corners:
        cx, cy = P(c["x"], c["z"])
        dl = deltas[c["no"]]["delta"] if c["no"] in deltas else None
        col = delta_color(dl)
        marks.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="13" fill="{col}" stroke="#fff" stroke-width="2"/>'
                     f'<text x="{cx:.1f}" y="{cy+5:.1f}" text-anchor="middle" '
                     f'font-size="14" font-weight="bold" fill="#fff">{c["no"]}</text>')
        if dl is not None:
            sag = cx > vbw - 60   # sağ kenarda etiket dairenin soluna yazılır
            marks.append(f'<text x="{cx - 17 if sag else cx + 17:.1f}" y="{cy-12:.1f}" font-size="13" '
                         f'font-weight="bold" text-anchor="{"end" if sag else "start"}" fill="{col}" '
                         f'stroke="#111" stroke-width="3" paint-order="stroke">{isaretli(dl)}</text>')

    table = corner_table(best, corners)
    rows = []
    for c in corners:
        r = deltas.get(c["no"])
        fark = ""
        neden = ""
        cizgi = ""
        if r:
            fark = f'{r["delta"]:+.2f} sn'
            neden = "; ".join(r["reasons"])
            kisa = {"girişte": "giriş", "tepe noktasında": "tepe", "çıkışta": "çıkış"}
            parca = [f'{kisa[n]} {abs(m):.1f} m {"sağda" if m > 0 else "solda"}'
                     for n, m in r.get("line", []) if abs(m) >= LINE_MIN_M]
            cizgi = ", ".join(parca) if parca else "aynı"
        st = table.get(c["no"])
        if not st:
            continue
        hiz = f'{st["min"]:.0f} km/s' if st["min"] is not None else ""
        vites = vites_yazi(st["gear"]) if st["gear"] is not None else ""
        bd = f'{st["brake_m"]:.0f} m önce' if st["brake_m"] and st["brake_m"] > 0 else "fren yok"
        rows.append(f'<tr><td>{c["no"]}</td><td>{st["entry"]:.0f} km/s</td><td>{hiz}</td>'
                    f'<td>{st["exit"]:.0f} km/s</td><td>{vites}</td><td>{bd}</td>'
                    f'<td>{fark}</td><td>{cizgi}</td><td>{neden}</td></tr>')

    lap_rows = "".join(f"<li>{t}</li>" for t in laps_info[-10:][::-1])
    return f"""<h2>En iyi tur: {sure(best["lap_ms"])}</h2>
<p class="k">Çizgi rengi: kırmızı = yavaş, yeşil = hızlı. Viraj rengi ve yanındaki sayı (son tur, kendi en iyi
geçişine göre sn): kırmızı = zaman kaybettin, yeşil = kazandın, koyulaştıkça fark büyür.</p>
<svg viewBox="0 0 {vbw:.0f} {vbh:.0f}" width="{vbw:.0f}" data-minx="{minx:.3f}" data-minz="{minz:.3f}"
 data-sc="{sc:.6f}" data-pad="{pad}">{''.join(segs)}{''.join(marks)}<circle class="arac" r="9" fill="#ff5a36"
 stroke="#fff" stroke-width="3" cx="-50" cy="-50"/></svg>
<div class="tablo"><table><tr><th>Viraj</th><th>Giriş</th><th>En düşük hız</th><th>Çıkış</th><th>Vites</th><th>Fren</th>
<th>Son tur farkı</th><th>Çizgi (son tur)</th><th>Neden</th></tr>{''.join(rows)}</table></div>
{gecmis_tablosu(corners, gecmis)}
<h3>Son turlar</h3><ul>{lap_rows}</ul>"""


HARITA_W, HARITA_H = 1000, 600   # arayüz haritasının çizim alanı (SVG birimi)
# Haritadaki daire ve etiket boyları
DAIRE_R = 14                      # viraj dairesi yarıçapı (eskiden 20)
HAP_W, HAP_H = 58, 26             # fark etiketi ("hap") boyu (eskiden 80 × 36)


def etiket_yerlestir(noktalar, cizgi, W, H):
    """Viraj farkı etiketleri: pist merkezinden dışa doğru, pistin, dairelerin, kenarın ve
    birbirinin üstüne binmeyecek ilk yere. noktalar: [(x, y)], cizgi: pist noktaları."""
    cx0 = sum(p[0] for p in cizgi) / len(cizgi)
    cy0 = sum(p[1] for p in cizgi) / len(cizgi)
    seyrek = cizgi[::2]
    konan = []

    def bos(lx, ly):
        if not (HAP_W / 2 + 6 <= lx <= W - HAP_W / 2 - 6 and HAP_H / 2 + 4 <= ly <= H - HAP_H / 2 - 4):
            return False
        if any(abs(lx - a) < HAP_W + 8 and abs(ly - b) < HAP_H + 4 for a, b in konan):
            return False
        if any(math.hypot(lx - qx, ly - qy) < DAIRE_R + HAP_W / 2 + 4 for qx, qy in noktalar):
            return False
        return all(math.hypot(lx - tx, ly - ty) > HAP_H / 2 + 12 for tx, ty in seyrek)

    for px, py in noktalar:
        taban = math.atan2(py - cy0, px - cx0)
        yer = None
        for r in (40, 48, 58, 70, 84, 100, 118):
            for da in (0, 30, -30, 60, -60, 90, -90, 120, -120, 150, -150, 180):
                a = taban + math.radians(da)
                lx, ly = px + math.cos(a) * r, py + math.sin(a) * r
                if bos(lx, ly):
                    yer = (lx, ly)
                    break
            if yer:
                break
        konan.append(yer or (px, max(HAP_H / 2 + 4, py - 40)))
    return konan


def bolum_yollari(pts, daireler, oranlar=None):
    """Her virajın pist bölümü (süre farkının ölçüldüğü yer, gt7_kopru.section_bounds gibi):
    önceki virajla ortası → sonraki virajla ortası; ilk bölüm başlangıçtan, son bölüm bitişe.
    oranlar: her viraj için (başlangıç, bitiş) tur oranı ya da None (14 Kasım 2026: virajdan sonraki
    düzlük o virajın sayılıyor, gt7_kopru.bolum_sinirlari).
    pts: pist çizgisi (piksel), daireler: viraj noktaları. Dönüş: her viraj için [(x, y)] ya da
    sıra tutmazsa (viraj çizgiye oturmadı) None."""
    if len(pts) < 2 or not daireler:
        return None
    cum = [0.0]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot(x2 - x1, y2 - y1))
    yer = []
    for qx, qy in daireler:
        i = min(range(len(pts)), key=lambda k: (pts[k][0] - qx) ** 2 + (pts[k][1] - qy) ** 2)
        yer.append(cum[i])
    if any(b <= a for a, b in zip(yer, yer[1:])):
        return None
    out = []
    for k, s in enumerate(yer):
        a = 0.0 if k == 0 else (yer[k - 1] + s) / 2
        b = cum[-1] if k == len(yer) - 1 else (s + yer[k + 1]) / 2
        o = oranlar[k] if oranlar and k < len(oranlar) else None
        if o:
            a, b = o[0] * cum[-1], o[1] * cum[-1]
        i0 = max(0, bisect.bisect_left(cum, a) - 1)
        i1 = min(len(pts), bisect.bisect_right(cum, b) + 1)
        out.append(pts[i0:i1])
    return out


def harita_svg(cizgi_xz, corners, deltas=None, sinirlar=None):
    """Arayüz haritası: gri pist, numaralı viraj daireleri, renkli fark etiketleri, araç noktası.
    cizgi_xz: [(x, z)] pist çizgisi; corners: [{"no", "x", "z"}]; deltas: {no: saniye};
    sinirlar: {no: (başlangıç, bitiş) tur oranı} (compare'in bölümleri; yoksa iki virajın ortası)."""
    deltas = deltas or {}
    W, H, PAD = HARITA_W, HARITA_H, 70
    xs = [p[0] for p in cizgi_xz]
    zs = [p[1] for p in cizgi_xz]
    minx, maxx, minz, maxz = min(xs), max(xs), min(zs), max(zs)
    sc = min((W - 2 * PAD) / ((maxx - minx) or 1), (H - 2 * PAD) / ((maxz - minz) or 1))
    ox = (W - (maxx - minx) * sc) / 2
    oz = (H - (maxz - minz) * sc) / 2

    def P(x, z):
        return (ox + (x - minx) * sc, oz + (z - minz) * sc)

    adim = max(1, len(cizgi_xz) // 700)
    pts = [P(x, z) for x, z in cizgi_xz[::adim]]
    yol = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    daireler = [P(c["x"], c["z"]) for c in corners]
    etiketler = etiket_yerlestir(daireler, pts, W, H)
    sx, sy = pts[0]
    out = [f'<path d="{yol}" class="pist-dis"/><path d="{yol}" class="pist-ic"/>',
           ]
    # Pistin her viraj bölümü son turdaki farka göre renkli
    bolumler = bolum_yollari(pts, daireler, [(sinirlar or {}).get(c["no"]) for c in corners]) if deltas else None
    for c, parca in zip(corners, bolumler or []):
        dl = deltas.get(c["no"])
        if dl is None or len(parca) < 2:
            continue
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in parca)
        out.append(f'<path d="{d}" class="pist-renk" stroke="{delta_color(dl)}"/>')
    out.append(f'<rect x="{sx - 3:.0f}" y="{sy - 15:.0f}" width="6" height="30" rx="2" fill="#fff" class="h-bas"/>')
    for c, (px, py), (lx, ly) in zip(corners, daireler, etiketler):
        dl = deltas.get(c["no"])
        renk = delta_color(dl) if dl is not None else "#5d6575"
        if dl is not None:
            out.append(f'<line x1="{px:.0f}" y1="{py:.0f}" x2="{lx:.0f}" y2="{ly:.0f}" stroke="{renk}" '
                       f'stroke-width="1.5" opacity=".6" class="h-cizgi"/>')
        out.append(f'<circle cx="{px:.0f}" cy="{py:.0f}" r="{DAIRE_R}" fill="#0d0f13" stroke="{renk}" stroke-width="3" class="h-daire"/>'
                   f'<text x="{px:.0f}" y="{py + 5:.0f}" class="vno">{c["no"]}</text>')
        if dl is not None:
            out.append(f'<rect x="{lx - HAP_W / 2:.0f}" y="{ly - HAP_H / 2:.0f}" width="{HAP_W}" height="{HAP_H}" '
                       f'rx="{HAP_H / 2:.0f}" fill="{renk}" stroke="#0a0c10" stroke-width="2" class="h-hap"/>'
                       f'<text x="{lx:.0f}" y="{ly + 5:.0f}" class="vfark">{isaretli(dl).replace("-", "−")}</text>')
    return (f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet" data-minx="{minx:.3f}" '
            f'data-minz="{minz:.3f}" data-sc="{sc:.6f}" data-ox="{ox:.2f}" data-oz="{oz:.2f}">'
            + "".join(out) + '<circle class="arac" r="9" fill="#ff6a3d" stroke="#fff" stroke-width="2.5" '
            'cx="-50" cy="-50"/></svg>')


def inceleme_svg(cizgi_xz, corners, sinirlar=None):
    """İnceleme ekranının haritası: gri pist, her viraj bölümü ayrı yol (data-no; arayüz ortalama kayba göre
    boyar), numaralı daireler."""
    W, H, PAD = 600, 420, 34
    xs = [p[0] for p in cizgi_xz]
    zs = [p[1] for p in cizgi_xz]
    minx, maxx, minz, maxz = min(xs), max(xs), min(zs), max(zs)
    sc = min((W - 2 * PAD) / ((maxx - minx) or 1), (H - 2 * PAD) / ((maxz - minz) or 1))
    ox = (W - (maxx - minx) * sc) / 2
    oz = (H - (maxz - minz) * sc) / 2
    pts = [(ox + (x - minx) * sc, oz + (z - minz) * sc) for x, z in cizgi_xz[::max(1, len(cizgi_xz) // 600)]]
    daireler = [(ox + (c["x"] - minx) * sc, oz + (c["z"] - minz) * sc) for c in corners]
    yol = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    out = [f'<path d="{yol}" fill="none" stroke="#3a3d44" stroke-width="9" stroke-linejoin="round"/>']
    bolumler = bolum_yollari(pts, daireler, [(sinirlar or {}).get(c["no"]) for c in corners]) or []
    for c, parca in zip(corners, bolumler):
        if len(parca) >= 2:
            d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in parca)
            out.append(f'<path d="{d}" class="ib" data-no="{c["no"]}" fill="none" stroke="transparent" '
                       f'stroke-width="9" stroke-linecap="round"/>')
    for c, (px, py) in zip(corners, daireler):
        out.append(f'<g class="id" data-no="{c["no"]}"><circle cx="{px:.0f}" cy="{py:.0f}" r="13" fill="#0a0a0b" '
                   f'stroke="#5d6575" stroke-width="2.5"/><text x="{px:.0f}" y="{py + 5:.0f}" text-anchor="middle" '
                   f'font-size="15" font-weight="800" fill="#fff">{c["no"]}</text></g>')
    return f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">' + "".join(out) + "</svg>"


def viraj_tablosu(best, corners, last_compare):
    """Viraj ayrıntı tablosu (arayüzde "Tur incelemesi" penceresinde)."""
    deltas = {r["no"]: r for r in (last_compare or [])}
    table = corner_table(best, corners)
    rows = []
    for c in corners:
        r = deltas.get(c["no"])
        st = table.get(c["no"])
        if not st:
            continue
        fark = isaretli(r["delta"]) if r else ""
        neden = "; ".join(r["reasons"]) if r else ""
        kisa = {"girişte": "giriş", "tepe noktasında": "tepe", "çıkışta": "çıkış"}
        parca = [f'{kisa.get(n, n)} {abs(m):.1f} m {"sağda" if m > 0 else "solda"}'
                 for n, m in (r.get("line", []) if r else []) if abs(m) >= LINE_MIN_M]
        cizgi = ", ".join(parca) if parca else ("aynı" if r else "")
        hiz = f'{st["min"]:.0f}' if st["min"] is not None else ""
        vites = vites_yazi(st["gear"]) if st["gear"] is not None else ""
        bd = f'{st["brake_m"]:.0f} m' if st["brake_m"] and st["brake_m"] > 0 else "yok"
        renk = delta_color(r["delta"]) if r else "transparent"
        rows.append(f'<tr><td><b>{c["no"]}</b></td><td>{st["entry"]:.0f}</td><td>{hiz}</td><td>{st["exit"]:.0f}</td>'
                    f'<td>{vites}</td><td>{bd}</td><td><span class="hap" style="background:{renk}">{fark}</span></td>'
                    f'<td>{cizgi}</td><td>{neden}</td></tr>')
    return ('<table class="vtablo"><tr><th>Viraj</th><th>Giriş km/s</th><th>En düşük</th><th>Çıkış</th><th>Vites</th>'
            '<th>Fren önce</th><th>Son tur</th><th>Çizgi</th><th>Neden</th></tr>' + "".join(rows) + "</table>")


def viraj_seridi(corners, gecmis, n=5):
    """Alt şerit için: son n tur × viraj farkı ve tüm kayıtların ortalaması."""
    son = (gecmis or [])[-n:][::-1]
    nolar = [c["no"] for c in corners]
    ort = {}
    for no in nolar:
        tum = [g["v"][str(no)] for g in gecmis or [] if g["v"].get(str(no)) is not None]
        ort[no] = round(sum(tum) / len(tum), 3) if tum else None
    return {"virajlar": nolar,
            "turlar": [{"saat": g["saat"], "sure": sure(g["sure"]),
                        "v": [g["v"].get(str(no)) for no in nolar]} for g in son],
            "ortalama": [ort[no] for no in nolar]}


def write_map(best, corners, laps_info, last_compare, gecmis=None):
    """Arayüzdeki pist haritası ve tablolar (HTML parçası)."""
    return map_body(best, corners, laps_info, last_compare, gecmis)


# ---------------- Mesajlar (konsol + arayüz) ----------------
LISTENERS = []   # arayüz buraya kendi fonksiyonunu ekler: fn(baslik, satirlar, tur, ses)
ADLAR = {}       # bu pistte adı bilinen virajlar {no: kayıt} (gt7_viraj_adlari); mesajlarda "Viraj 13" -> "Spoon"


def adlari_guncelle(state):
    """Pistin virajlarını bilinen viraj adlarıyla eşleştirir (Suzuka'da "Spoon" gibi)."""
    global ADLAR
    tr = state.get("track") or {}
    try:
        ADLAR = eslestir(tr.get("official_id"), tr.get("corners") or [])
    except Exception:
        ADLAR = {}
    state["adlar"] = {no: k["ad"] for no, k in ADLAR.items()}
    return ADLAR


def viraj_adi(no):
    """Ekranda: "Viraj 13" ya da adı varsa "Spoon (V13)"."""
    return adlandir(f"Viraj {no}", ADLAR, ekran=True)


def notify(title, lines=(), kind="bilgi", ses=None):
    """Koçun bir mesajını konsola yazar ve arayüze iletir.
    kind: "bilgi", "uyari", "tur" (tur sonu), "anlik" (virajdan önce uyarı), "muhendis" (telsiz anonsu),
    "sonra" (viraj çıkışı yorumu), "tahmin" (ilk temiz turdan önce kaba viraj bilgisi, sesli okunmaz).
    ses: sesli okunacak kısa metin (yoksa okunmaz).
    Adı bilinen virajlar: ekranda "Spoon'da (V13)", seste sadece numara ("Viraj 13'te")."""
    # Seste viraj adı yok, sadece numara (14 Kasım 2026: İngilizce adların okunuşu anlaşılmıyordu);
    # kısaltmalar açılır (TCS -> çekiş kontrolü). Ekranda adlar durur.
    ses = acik_yaz(ses) if ses else ses
    if ADLAR:
        title = adlandir(title, ADLAR, ekran=kind not in ("uyari", "muhendis"))
        lines = [adlandir(ln, ADLAR, ekran=True) for ln in lines]
    if kind in ("anlik", "sonra", "tahmin"):
        print("\n» " + title)
    else:
        print("\n" + title)
        for ln in lines:
            print("  " + ln)
    for fn in LISTENERS:
        try:
            fn(title, list(lines), kind, ses)
        except Exception:
            pass


# ---------------- Kayıt ----------------
def new_lap():
    return {k: [] for k in ("t", "dist", "x", "z", "speed", "throttle",
                            "brake", "gear", "rpm", "suggested_gear",
                            "slip_fl", "slip_fr", "slip_rl", "slip_rr",
                            "sus_fl", "sus_fr", "sus_rl", "sus_rr", "fuel",
                            "revlim", "tt_f", "tt_r", "slip_body", "yaw", "wheel_angle", "body_h")}


def save_lap_csv(lap, lap_ms, car):
    os.makedirs(LAP_DIR, exist_ok=True)
    name = time.strftime("tur_%Y%m%d_%H%M%S") + f"_{lap_ms}ms_araba{car}.csv"
    with open(os.path.join(LAP_DIR, name), "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        keys = [k for k, v in lap.items() if isinstance(v, list) and len(v) == len(lap["t"])]
        wr.writerow(keys)
        for i in range(len(lap["t"])):
            wr.writerow([lap[k][i] for k in keys])


REF_DIR = os.path.join(BASE, "referanslar")
TARAMA_BEKLE_S = 8   # bu kadar saniye veri gelmezse PS5 ev ağında aranır
PIST_ONAY_S = 10           # seçilen pist, çizgisine bu kadar saniye üst üste yakın sürülünce doğrulanmış sayılır
KEEP_LAPS = 8        # her araba için saklanan en iyi temiz tur sayısı
SLOW_LIMIT = 1.07    # en iyiden %7'den yavaş tur referans olmaz
SLOW_START_KMH = 40  # başlangıç hızı en iyi turdan bu kadar düşükse tur referans olmaz
CSV_ONLY = ("slip_fl", "slip_fr", "slip_rl", "slip_rr",
            "sus_fl", "sus_fr", "sus_rl", "sus_rr", "fuel",
            "revlim", "tt_f", "tt_r", "slip_body", "yaw", "loose",
            "body_h")  # referans dosyasına yazılmaz


def check_lap(lap):
    """Turda referansı bozacak bir hata var mı? Varsa sebebini döndürür."""
    d, sp, g = lap["dist"], lap["speed"], lap["gear"]
    for i in range(1, len(d)):
        if math.hypot(lap["x"][i] - lap["x"][i - 1], lap["z"][i] - lap["z"][i - 1]) > 30:
            return "konum sıçraması (reset/geri sarma)"
    if any(g[i] == 0 and sp[i] > 3 for i in range(len(g))):
        return "geri vites kullanıldı"
    if min(sp[int(len(sp) * 0.03):int(len(sp) * 0.97)] or [99]) < 15:
        return "araç neredeyse durdu (savrulma/çarpma)"
    return None


def track_key(lap):
    return f"{int(round(lap['dist'][-1] / 25.0) * 25)}m"


def find_saved_track(lap):
    if not os.path.isdir(REF_DIR):
        return None
    L = lap["dist"][-1]
    x0, z0 = lap["x"][0], lap["z"][0]
    for fn in os.listdir(REF_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(REF_DIR, fn), encoding="utf-8") as f:
                tr = json.load(f)
        except Exception:
            continue
        if not tr.get("start"):
            continue
        if abs(tr["length"] - L) < 0.03 * L and \
                math.hypot(tr["start"][0] - x0, tr["start"][1] - z0) < 80:
            tr["file"] = fn
            return tr
    return None


def load_selected_track(sel):
    """Menüden seçilen pisti hazırlar; daha önce sürdüysen kendi turlarınla birlikte yükler."""
    fn = f"pist_{sel['id']}.json"
    try:
        with open(os.path.join(REF_DIR, fn), encoding="utf-8") as f:
            tr = json.load(f)
    except (OSError, ValueError):
        tr = {"key": sel["id"], "official_id": sel["id"], "length": sel["length"],
              "start": None, "corners": [], "frozen": False, "laps": {}, "file": fn}
    # Çizgi ve hazır virajlar her açılışta kütüphaneden gelir
    tr["name"] = sel["name"]
    tr["path"] = sel["path"]
    tr["corner_xy"] = sel["corner_xy"]
    return tr


def kucult(L):
    """Diske yazılacak tur: liste değerleri yuvarlanır, sadece CSV'ye giden alanlar atılır."""
    return {k: ([v if v is None else round(v, 3 if k == "wheel_angle" else 2) for v in val]
                if isinstance(val, list) else val)
            for k, val in L.items() if k not in CSV_ONLY}


def save_track(tr):
    os.makedirs(REF_DIR, exist_ok=True)
    fn = tr.get("file") or (f"pist_{tr['key']}_" + time.strftime("%Y%m%d%H%M%S") + ".json")
    tr["file"] = fn
    small = dict(tr)
    small["laps"] = {car: [kucult(L) for L in laps] for car, laps in tr["laps"].items()}
    if tr.get("rekor"):
        small["rekor"] = {car: kucult(L) for car, L in tr["rekor"].items()}
    with open(os.path.join(REF_DIR, fn), "w", encoding="utf-8") as f:
        json.dump(small, f)


def consensus_corners(laps):
    """Temiz turların çoğunda görülen virajları kalıcı yap."""
    found = [[c["frac"] for c in find_corners(L)] for L in laps]
    allf = sorted(f for fs in found for f in fs)
    clusters = []
    for f in allf:
        if clusters and f - clusters[-1][-1] < 0.012:
            clusters[-1].append(f)
        else:
            clusters.append([f])
    need = (len(laps) // 2) + 1
    base = min(laps, key=lambda L: L["lap_ms"])
    out = []
    for cl in clusters:
        if len(cl) >= need:
            fr = sum(cl) / len(cl)
            k = min(range(len(base["dist"])),
                    key=lambda i: abs(base["dist"][i] / base["dist"][-1] - fr))
            out.append({"no": len(out) + 1, "frac": fr,
                        "x": base["x"][k], "z": base["z"][k]})
    return out


def slow_start(lap, best):
    return lap["speed"][0] < best["speed"][0] - SLOW_START_KMH


def reference_pool(laps):
    """Karşılaştırmaya girecek turlar: en iyiye yakın ve yavaş başlamamış olanlar."""
    if not laps:
        return []
    best = min(laps, key=lambda L: L["lap_ms"])
    return [L for L in laps if L["lap_ms"] <= SLOW_LIMIT * best["lap_ms"] and not slow_start(L, best)]


def pist_hazirla(lap, state, out):
    """Hangi pistteyiz? Seçilen pist yoksa kayıtlı pistlerde arar ya da yenisini açar.
    Döner: (pist kaydı, pist menüden seçildi mi)."""
    tr = state.get("track")
    selected = bool(tr and tr.get("official_id"))
    if not selected and (tr is None or tr.get("provisional")
                         or abs(tr["length"] - lap["dist"][-1]) > 0.04 * tr["length"]):
        # Yarışın 1. turu ızgaradan başlar: pisti onunla arama, sonraki turda yeniden ara
        tr = None if race_start(lap) else find_saved_track(lap)
        if tr:
            out.append(f"Kayıtlı pist bulundu ({tr['key']}), önceki referansların yüklendi.")
        else:
            tr = {"key": track_key(lap), "length": lap["dist"][-1],
                  "start": [lap["x"][0], lap["z"][0]],
                  "corners": [], "frozen": False, "laps": {}}
            if race_start(lap):
                tr["provisional"] = True
        state["track"] = tr
        state["laps_info"] = []
        state["spans"] = []
    return tr, selected


def pist_adi(tr):
    tr = tr or {}
    return tr.get("name") or (f"Pist ({tr['key']})" if tr.get("key") else "Pist")


def secili_rekor(tr, car):
    """Koçun referans alacağı rekor turu ("hedef tur"):
    Time Trial hazırlıkta seçilen rekor turu (tr["hedef_tur"] = {"tip": "rekor", "araba": kod}). Hiç seçim
    yapılmamışsa (eski kayıtlar) bu arabanın rekor turu; kendi turun ya da sadece süre seçildiyse None."""
    tr = tr or {}
    rekorlar = tr.get("rekor") or {}
    if "hedef_tur" not in tr:
        return rekorlar.get(str(car)) if car is not None else None
    ht = tr.get("hedef_tur") or {}
    return rekorlar.get(str(ht.get("araba"))) if ht.get("tip") == "rekor" else None


def tt_hedefi(tr):
    """Time Trial'dan seçilen hedef (pist için, arabadan bağımsız; Gr.3 gibi sınıflı
    etkinlikte her arabayla geçerli): {"ms", "etiket", "etkinlik", "bitis"} ya da etkinlik bittiyse None."""
    h = (tr or {}).get("tt_hedef")
    if not h or not h.get("ms"):
        return None
    kalan = gt7_tt._kalan(h.get("bitis"))
    return None if kalan is not None and kalan < 0 else h


def hedef_bul(tr, car):
    """Hedef süre: (ms, kaynak). Önce Time Trial hedefi (pist için, kaynak "tt"), sonra bu arabaya kendi
    koyduğun hedef ("kendi"), yoksa rekor turu kaydedildiyse onun süresi ("rekor"; 14 Kasım 2026).
    Hiçbiri yoksa (None, None)."""
    ht = (tr or {}).get("hedef_tur") or {}
    if ht.get("tip") == "rekor":                   # seçilen hedef tur: rekor turu (hem hedef hem referans)
        r = ((tr or {}).get("rekor") or {}).get(str(ht.get("araba")))
        if r and r.get("lap_ms"):
            return r["lap_ms"], "rekor"
    if ht.get("tip") == "eniyi" and car is not None:   # seçilen hedef tur: kendi en iyi turun
        laps = ((tr or {}).get("laps") or {}).get(str(car)) or []
        if laps:
            return min(L["lap_ms"] for L in laps), "eniyi"
    th = tt_hedefi(tr)
    if th:
        return th["ms"], "tt"
    if not tr or car is None:
        return None, None
    ms = (tr.get("hedef") or {}).get(str(car))
    if ms:
        return ms, "kendi"
    rek = (tr.get("rekor") or {}).get(str(car)) if "hedef_tur" not in tr else None   # eski kayıt: rekor turu
    if rek and rek.get("lap_ms"):
        return rek["lap_ms"], "rekor"
    return None, None


def hedef_durumu(tr, car, corners=None):
    """Bu pist + arabanın hedef süre analizi (hedef yoksa None)."""
    hedef_ms, kaynak = hedef_bul(tr, car)
    if not hedef_ms:
        return None
    pool = reference_pool(tr["laps"].get(str(car), [])) if car is not None else []
    out = gt7_hedef.analiz(hedef_ms, pool, corners or tr.get("corners") or [],
                           (tr.get("rekor") or {}).get(str(car)), adi=viraj_adi)
    out["kaynak"] = kaynak
    # Time Trial'dan seçilen hedef: "altin" / "gumus" / "bronz" / "rekor" (dünya rekoru)
    out["etiket"] = tt_hedefi(tr)["etiket"] if kaynak == "tt" else None
    if kaynak == "rekor":
        out["satirlar"][0] = out["satirlar"][0].replace("Hedef ", "Hedef (rekor turu süresi) ", 1)
    return out


def lap_end(lap, lap_ms, car, state, opts=None):
    """Tur bitince: kaydet, karşılaştır, ekrana ve sese özet çıkar.
    opts: {"manuel": bool, "kalan_tur": int ya da None}. Karşılaştırma sonucunu döndürür."""
    opts = opts or {}
    manuel = opts.get("manuel", False)
    if lap_ms <= 0 or len(lap["t"]) < 600 or lap["dist"][-1] < 500:
        notify("Tur eksik kaydedildi, analiz edilmedi.", kind="uyari")
        return None
    lap["lap_ms"] = lap_ms
    lap["car"] = car
    lap["kayit_id"] = f"{time.time():.3f}"
    state.setdefault("seans_bas", time.strftime("%d.%m.%Y %H:%M"))   # seans raporu için
    state.setdefault("seans_dosya", time.strftime("%Y%m%d_%H%M"))   # arayüzdeki "bu turu sayma" düğmesi için
    save_lap_csv(lap, lap_ms, car)
    out = []  # ekrandaki ayrıntılı notlar

    tr, selected = pist_hazirla(lap, state, out)

    pool_all = tr["laps"].setdefault(str(car), [])
    # Tur uzunluğu ölçütü (son turların ortancası) değiştikçe eski referanslar da yargılanır
    spans = state.setdefault("spans", [])
    spans.append(lap["dist"][-1])
    dropped = drop_partial(pool_all, spans)
    if dropped:
        out.append(f"{dropped} eski referans tur, son turlara göre eksik kaldığı için çıkarıldı.")
    best_ms = min((L["lap_ms"] for L in pool_all), default=None)
    pool = [L for L in reference_pool(pool_all) if not slow_start(L, lap)]

    problem = check_lap(lap) or time_problem(lap, lap_ms)
    if not problem and race_start(lap):
        problem = "yarışın ilk turu (ızgaradan kalkış, çizgiden değil)"
    if not problem:
        problem = pit_turu(lap)
    if not problem and isinma_turu(lap):
        problem = "ısınma turu (lastikler soğuktu)"
    limit = span_limit(spans)
    if not problem and limit and lap["dist"][-1] < limit:
        problem = "tur eksik kaydedildi (son turlardan belirgin kısa)"
    if not problem and not cizgide_basladi(lap):
        problem = "tur başlangıç çizgisinden başlamadı (kayıt eksik)"
    if not problem and not tam_tur(lap):
        problem = "tur başladığı yere dönmedi (kayıt eksik)"
    if not problem and off_track_count(lap):
        problem = "pist dışına çıktın (3+ teker çim, kum ya da toprakta)"
    if not problem and selected and tr["path"] and ters_yon(tr["path"], lap):
        problem = "pisti ters yönde sürdün (seçilen düzenin tersi)"
        if not state.get("ters_uyarildi"):
            state["ters_uyarildi"] = True
            notify("UYARI: Pisti ters yönde sürüyorsun.",
                   [f"Seçilen düzen: {tr.get('name', '?')}. Pist listesinden '(Reverse)' / ters düzenini seç."],
                   kind="uyari")
    if not problem and selected and tr["path"] and not lap_on_path(tr["path"], lap):
        problem = "tur seçilen pistin dışında kaldı"
    if not problem and pool_all and slow_start(lap, pool_all[0]):
        problem = "yavaş başlangıç"
    if not problem and best_ms and lap_ms > SLOW_LIMIT * best_ms:
        problem = "en iyi turundan %7'den fazla yavaş"

    # Hazır viraj konumları ilk temiz turda bu pistin viraj haritasına çevrilir
    if not problem and selected and tr["corner_xy"] and not tr["corners"]:
        tr["corners"] = corners_for_lap(tr["corner_xy"], lap)
        tr["frozen"] = True

    if best_ms is None:
        title = f"Tur bitti: {sure(lap_ms)}"
    else:
        title = f"Tur bitti: {sure(lap_ms)}  (en iyiye göre {(lap_ms - best_ms) / 1000:+.3f} sn)"
    if problem:
        out.append(f"Not: Bu tur referans alınmadı -> {problem}.")

    # Rekor turu referans modunda (ayar "referans" = rekor ve bu arabanın rekor turu var) her şey o tura göre
    rek_ref = opts["rekor_tur"] if "rekor_tur" in opts else secili_rekor(tr, car)
    rek = rek_ref or (tr.get("rekor") or {}).get(str(car))   # referans değilse notlarda ek karşılaştırma
    rekor_ref = bool(rek_ref)
    state["rekor_ref"] = rekor_ref
    corners = tr["corners"] or find_corners(rek if rekor_ref else lap if not pool
                                            else min(pool, key=lambda L: L["lap_ms"]))
    cmp_res = None
    # Teker kilitlenme / patinaj (tüm tur): kilitlenme virajın sorunu olarak tavsiyeye de girer
    teker_olay = wheel_events(lap, corners, limit=50) if lap.get("slip_fl") and corners else []
    kpool = [rek] if rekor_ref else pool
    if kpool:
        cmp_res = compare(lap, kpool, corners)
        if rekor_ref:      # cümlelerde "en iyi geçişin" yerine "rekor turu"
            for r in cmp_res:
                r["reasons"] = [rekor_dili(x) for x in r["reasons"]]
                for i in r["issues"]:
                    i["ekran"] = rekor_dili(i["ekran"])
            out.append(f"Koç rekor turuna göre konuşuyor (rekor {sure(rek['lap_ms'])}, "
                       f"bu tur {(lap_ms - rek['lap_ms']) / 1000:+.3f} sn). Ayarlar › Koç'tan değiştirilebilir.")
            if state.get("fren_kayma"):   # güvenlik payı / kendi fren gücü: erken-geç fren kaymış noktaya göre
                fren_kaymasi_uygula(cmp_res, state["fren_kayma"])
        if teker_olay:
            kilit_ekle(cmp_res, teker_olay)
        kayip = sorted([r for r in cmp_res if r["delta"] > 0.05],
                       key=lambda r: -r["delta"])[:3]
        if kayip:
            out.append("En çok zaman kaybettiğin virajlar (rekor turuna göre):" if rekor_ref else
                       "En çok zaman kaybettiğin virajlar (kendi en iyi geçişine göre):")
            for r in kayip:
                nedenler = r["reasons"] + ([r["gear_reason"]] if manuel and r["gear_reason"] else [])
                fo = faz_ozeti(r)    # zamanın çoğunun gittiği aşama + virajdan sonraki düzlük payı
                out.append(f"Viraj {r['no']}: {r['delta']:+.2f} sn -> "
                           + ("; ".join(nedenler) or ("fren, çizgi ve gaz rekor turuna yakın; " if rekor_ref else
                                                      "fren, çizgi ve gaz en iyi geçişine yakın; ")
                              + "fark küçük ayrıntılarda")
                           + (f" ({fo})" if fo else ""))
        kesmeler = sorted((k for r in cmp_res for k in r.get("kesmeler", [])), key=lambda k: -k["sn"])
        for k in kesmeler[:3]:
            out.append(kesme_cumlesi(k) + ".")
        kazanc = [r for r in cmp_res if r["delta"] < -0.05 and not r.get("kaza")]
        if kazanc:
            iyi = min(kazanc, key=lambda r: r["delta"])
            out.append(f"Aferin: Viraj {de(iyi['no'])} rekor turundan {-iyi['delta']:.2f} sn hızlıydın." if rekor_ref else
                       f"Aferin: Viraj {de(iyi['no'])} en iyi geçişini {-iyi['delta']:.2f} sn geliştirdin.")
        yuksek = [r["no"] for r in cmp_res if r["gear_high"]][:3]
        if manuel and yuksek:
            out.append("Vites: GT7'nin önerisine göre bir vites yüksek geçtiğin virajlar: "
                       + ", ".join(str(n) for n in yuksek))
    else:
        out.append("Viraj viraj karşılaştırma için uygun önceki tur yok"
                   + (" (kayıtlı temiz turun yavaş başlamıştı, ilk turlarda bu normal)" if best_ms else "")
                   + ". Sonraki turlarda gelecek.")

    # Rekor turu (replay'den kaydedildiyse): aynı arabayla viraj viraj karşılaştırma
    state.pop("rekor_cmp", None)
    if rek:
        try:
            r_satir, state["rekor_cmp"] = rekor_karsilastir(lap, rek, corners or find_corners(rek))
            out += [] if rekor_ref else r_satir     # rekor modunda ana liste zaten rekora göre
        except Exception as e:  # rekor karşılaştırması tur analizini durdurmasın
            out.append(f"Rekor turuyla karşılaştırılamadı ({e!r}).")

    # Zemin (C biçimi): tekerlerin çime / kuma taştığı virajlar
    for yer, teker in tasmalar(lap):
        total = lap["dist"][-1] or 1
        near = min(corners, key=lambda c: abs(c["frac"] * total - yer), default=None) if corners else None
        nerede = f"Viraj {de(near['no'])}" if near and abs(near["frac"] * total - yer) <= 150 else "Pistte"
        out.append(f"{nerede} {teker} teker çime / kuma taştı.")

    # Teker kilitlenme/patinaj: ekranda hepsi, seste sadece aynı virajda üst üste tekrar edenler
    # (sesli: aynı virajda son 3 turun 3'ünde de olan, bir kez)
    teker_tekrar = []
    if lap.get("slip_fl"):
        olaylar = teker_olay[:3]
        for e in olaylar:
            out.append(e["metin"])
        teker_tekrar = teker_tekrari(state, olaylar)

    # Araç ayarı önerisi: son turlarda tekrar eden kilit / patinaj / önden-arkadan kayma
    ayar_ses = None
    cekis, dagilim = None, opts.get("dagilim")
    try:
        cekis, yeni = cekis_ogren(lap, car)
        if yeni:
            out.append(f"Çekiş türü bulundu: {CEKIS_ADLARI[cekis]}."
                       + (" Güç dağıtıcı takılıysa ayarını Ayarlar'a yaz, öneriler ona göre gelir."
                          if cekis == "4x4" and dagilim is None else ""))
    except Exception as e:
        print(f"(Çekiş türü ölçülemedi: {e!r})")
    try:
        ak = state.setdefault("ayar_kocu", AyarKocu())
        ayar_satir, ayar_ses = ak.tur_ekle(tur_desenleri(lap, corners), cekis,
                                           dagilim if cekis == "4x4" else None)
        out += ayar_satir
        state["oneriler"] = ak.liste()
    except Exception as e:  # öneri hatası tur analizini durdurmasın
        print(f"(Ayar önerisi hesaplanamadı: {e!r})")

    # 4 çekerde güç dağılımı denemeleri: her ayarla bu seanstaki en iyi temiz tur
    if cekis == "4x4" and dagilim is not None and not problem:
        ds = state.setdefault("dagilim_sure", {}).setdefault(str(car), {})
        ds[dagilim] = min(ds.get(dagilim, lap_ms), lap_ms)
        digerleri = {k: v for k, v in ds.items() if k != dagilim}
        if digerleri:
            k, v = min(digerleri.items(), key=lambda kv: kv[1])
            fark = (ds[dagilim] - v) / 1000
            out.append(f"Güç dağılımı {dagilim_yazi(dagilim)} ile en iyi turun {sure(ds[dagilim])}; "
                       f"{dagilim_yazi(k)} ile {sure(v)} "
                       + (f"(yeni ayar {abs(fark):.2f} sn daha hızlı)." if fark < -0.005 else
                          f"(yeni ayar {fark:.2f} sn daha yavaş)." if fark > 0.005 else "(aynı)."))

    yakit_tur = None
    strateji_ses = None
    pit_sn = pist_bilgi(tr.get("official_id")).get("pit_kaybi_sn")
    state.pop("strateji", None)
    if lap.get("fuel") and lap["fuel"][0] - lap["fuel"][-1] > 0:
        fuel_laps = state.setdefault("fuel_laps", [])
        fuel_laps.insert(0, lap_fuel(len(fuel_laps) + 1, lap_ms, lap["fuel"][0] - lap["fuel"][-1], car))
        yakit_tur = fuel_laps_left(fuel_laps, lap["fuel"][-1], car)
        kalan = opts.get("kalan_tur")
        if yakit_tur is not None and kalan:
            # Yarışta: pit / yakıt stratejisi (kaç pit, hangi tur, kaç litre)
            sp = gt7_strateji.plan(lap["fuel"][-1], opts.get("kapasite"), lap["fuel"][-1] / yakit_tur
                                   if yakit_tur > 0 else None, kalan, opts.get("tur_no") or 0)
            if sp:
                state["strateji"] = sp
                out.append(gt7_strateji.satir(sp, pit_sn))
                strateji_ses = gt7_strateji.sesli(sp, state.setdefault("strateji_durum", {}))
        elif yakit_tur is not None:
            out.append(f"Yakıt: bu tempoyla yaklaşık {yakit_tur:.1f} tur daha yeter.")

    ozet = tur_ozeti(lap)
    if ozet:
        out.append(tur_ozeti_satiri(ozet))

    lastik = {}
    for k, ad in (("tt_f", "on"), ("tt_r", "arka")):
        vals = [v for v in lap.get(k, []) if v and v > 0]
        if vals:
            lastik[ad] = sum(vals) / len(vals)
    if lastik:
        out.append("Lastik sıcaklığı (tur ortalaması): "
                   + ", ".join(f"{'ön' if k == 'on' else 'arka'} {v:.0f}°C" for k, v in lastik.items()))
    # Islak pist tahmini: her virajda kayıp + yavaş tur + soğuyan lastikler (ya da sürerken lastikler soğudu)
    hava_ses = None
    lastik_ort = sum(lastik.values()) / len(lastik) if lastik else None
    # Islak tahmini sadece kendi en iyi geçişlerine göre (rekor turuna göre her virajda kayıp olur) ve
    # tekerler çime/kuma taşmadıysa (14 Kasım 2026: 2 teker çime çıkınca "pist ıslak" denmişti)
    islak_cmp = None
    if not problem and not tasmalar(lap):
        try:
            islak_cmp = cmp_res if not rekor_ref else (compare(lap, pool, corners) if pool else None)
        except Exception:
            islak_cmp = None
    islak_satir, hava_ses, islak = islak_tur(state, islak_cmp, lap_ms, best_ms, lastik_ort)
    if islak_satir:
        out.append(islak_satir)
    if islak:
        state["islak"] = True
    elif state.get("islak") and not problem and best_ms and lap_ms <= KURU_YAKIN * best_ms:
        state["islak"] = False
        out.append("Tur en iyine yakın: pist kurumuş görünüyor, viraj uyarıları yeniden açık.")
    revlim_s = sum(1 for v in lap.get("revlim", []) if v) / 60.0
    if manuel and revlim_s > 0.5:
        out.append(f"Devir sınırında geçen süre: {revlim_s:.1f} sn.")

    if not problem:
        # Pistin başlangıç noktası temiz bir turdan alınır (yarışın 1. turu ızgaradadır)
        if not tr.get("start_ok"):
            tr["start"] = [lap["x"][0], lap["z"][0]]
            tr["start_ok"] = True
        pool_all.append(lap)
        pool_all.sort(key=lambda L: L["lap_ms"])
        del pool_all[KEEP_LAPS:]
        if best_ms is None or lap_ms < best_ms:
            out.append("YENİ EN İYİ TUR!" if best_ms else "İlk temiz tur kaydedildi, referans oluşmaya başladı.")
        pool = reference_pool(pool_all)
        state.setdefault("gecmis", []).append(lap_ms)
        # Virajlar: 3 temiz turdan sonra ortak kararla kalıcı olur
        if not tr["frozen"]:
            if len(pool) >= 3:
                tr["corners"] = consensus_corners(pool[:5])
                tr["frozen"] = True
                out.append(f"Viraj haritası kalıcı hale geldi ({len(tr['corners'])} viraj).")
            else:
                tr["corners"] = find_corners(pool[0])
            corners = tr["corners"]
        save_track(tr)

    if pool and len(pool) >= 2:
        out.append(f"İdeal turun (her virajdaki en iyi geçişlerin toplamı): {sure(ideal_ms(pool, corners))}")

    adlari_guncelle(state)   # viraj haritası değişmiş olabilir

    # Hedef süre (pist + araba başına): farkı hangi virajlar kapatır
    hedef_ms, _ = hedef_bul(tr, car)
    hedef_ses = None
    state["hedef"], state["hedef_araba"] = None, car
    if hedef_ms:
        try:
            state["hedef"] = hedef_durumu(tr, car, corners)
            out += state["hedef"]["satirlar"]
        except Exception as e:  # hedef analizi tur analizini durdurmasın
            out.append(f"Hedef analizi yapılamadı ({e!r}).")
        hedef_ses = gt7_hedef.ses(hedef_ms, lap_ms, best_ms, problem)

    # Arayüzdeki "Tur incelemesi": virajlar en çok kaybettirenden başlayarak, 4 aşamasıyla
    if cmp_res:
        state["inceleme"] = {"id": time.time(),
                             "saat": time.strftime("%H:%M"), "sure": sure(lap_ms),
                             "virajlar": [{"no": r["no"], "delta": round(r["delta"], 3),
                                           "fazlar": r.get("fazlar", []), "nedenler": r["reasons"]}
                                          for r in sorted(cmp_res, key=lambda r: -r["delta"])]}
    duzeltilen = opts.get("duzeltilen") or []
    if duzeltilen:
        out.append("Geçen sefer söylenen sorunu düzelttiğin virajlar: "
                   + ", ".join(str(n) for n in duzeltilen) + ". Aferin!")
    fren_satir, fren_ses = fren_aliskanligi(state, cmp_res) if cmp_res and not problem else ([], None)
    out += fren_satir
    tempo_ses = tempo(state, state.get("gecmis", [])) if not problem else None
    if tempo_ses:
        out.append(tempo_ses)
    sira = opts.get("sira")
    if sira:
        out.insert(0, f"Yarış sırası: {sira[0]}. / {sira[1]}")
    # Önemli virajlar (kayıp + aynı sorunun tekrarı): tur sonu sesi ve sonraki turun hatırlatmaları aynı sırayı kullanır
    puan_gecmis = state.setdefault("viraj_puan", [])
    state["onemli"] = onemli_virajlar(cmp_res, puan_gecmis, manuel) if cmp_res else []
    if cmp_res and not problem:
        gecmise_ekle(puan_gecmis, cmp_res, manuel)
    odak_no = opts.get("odak")       # odak virajı (16 Kasım 2026): sesli tavsiye sadece o viraj için
    if odak_no:
        state["onemli"] = [o for o in state["onemli"] if o["no"] == odak_no]
        if fren_ses and not re.search(rf"Viraj {odak_no}\b", fren_ses):
            fren_ses = None
    viraj_tavsiyesi = not opts.get("yaris_sessiz")   # yarışta (ayar kapalıysa) viraj tavsiyesi okunmaz
    soylenen = []        # tur sonu sesinde tavsiye verilen virajlar: sonraki turda o viraja gelirken hatırlatılır
    ses = ses_ozeti(lap_ms, best_ms, problem, state.get("gecmis", []), cmp_res, manuel,
                    yakit_tur=None if state.get("strateji") else yakit_tur, kalan_tur=opts.get("kalan_tur"),
                    lastik=lastik, strateji_ses=strateji_ses, hava_ses=hava_ses,
                    teker_tekrar=teker_tekrar, revlim_s=revlim_s, ayar_ses=ayar_ses,
                    duzeltilen=duzeltilen, sira=sira, tempo=tempo_ses, fren_ses=fren_ses,
                    pit_sn=pit_sn, onemli=state["onemli"], soylenen=soylenen, rekor=rekor_ref,
                    tavsiye=viraj_tavsiyesi)
    state["hatirlat"] = soylenen
    if hedef_ses:
        ses = f"{ses} {hedef_ses}"
    tt = opts.get("tt")       # sürdüğün pist + araba haftalık time trial'a uyuyorsa
    if tt:
        tt_satir, tt_ses = gt7_tt.tur_satiri(tt, lap_ms, best_ms)
        out.insert(0, tt_satir)
        if tt_ses and not problem:
            ses = f"{ses} {tt_ses}"

    state.setdefault("laps_info", []).append(
        f"{time.strftime('%H:%M')} — {sure(lap_ms)}" + (" (referans dışı)" if problem else ""))
    best_lap = pool_all[0] if pool_all else lap
    gecmis = tr.setdefault("gecmis", {}).setdefault(str(car), [])
    if cmp_res:
        gecmis.append({"saat": time.strftime("%H:%M"), "sure": lap_ms, "temiz": not problem,
                       "v": {str(r["no"]): round(r["delta"], 3) for r in cmp_res}})
        del gecmis[:-GECMIS_TUR]
        save_track(tr)
    if cmp_res:   # seans raporu: bu seansta virajların gelişimi
        state.setdefault("seans_viraj", []).append({"temiz": not problem,
                                                    "v": {str(r["no"]): round(r["delta"], 3) for r in cmp_res}})
    out += tutarlilik(state.get("gecmis", []), [g for g in gecmis if g.get("temiz", True)])
    state["map_html"] = write_map(best_lap, corners, state["laps_info"], cmp_res, gecmis)
    # Yeni arayüz: harita SVG'si, viraj tablosu, viraj şeridi, tur listesi
    deltas = {r["no"]: r["delta"] for r in (cmp_res or [])}
    sinirlar = {r["no"]: r["bolum"] for r in (cmp_res or []) if r.get("bolum")}
    state["harita"] = {"svg": harita_svg(list(zip(best_lap["x"], best_lap["z"])), corners, deltas, sinirlar),
                       "tablo": viraj_tablosu(best_lap, corners, cmp_res),
                       "serit": viraj_seridi(corners, gecmis),
                       "en_iyi": sure(best_lap["lap_ms"]),
                       "ideal": sure(ideal_ms(pool, corners)) if pool and len(pool) >= 2 else None}
    # İnceleme ekranı (oyun duraklatılınca): her turun viraj farkları ve sorunları
    if cmp_res:
        kazali = any(r.get("kaza") for r in cmp_res) or bool(tasmalar(lap))
        state.setdefault("inceleme_turlar", []).append({
            "no": len(state.get("turlar", [])) + 1, "ms": lap_ms, "sure": sure(lap_ms), "t": time.time(),
            "gecersiz": bool(problem), "kaza": kazali,
            "v": {str(r["no"]): [round(r["delta"], 3),
                                 (r["issues"][0]["kod"] if r["issues"] else None),
                                 (r["issues"][0]["ekran"] if r["issues"] else None)] for r in cmp_res}})
        del state["inceleme_turlar"][:-60]
        state["inceleme_ref"] = {str(r["no"]): r.get("ref_s") for r in cmp_res}
        state["inceleme_harita"] = inceleme_svg(list(zip(best_lap["x"], best_lap["z"])), corners, sinirlar)
        state["inceleme_ideal"] = state["harita"]["ideal"]
    gt7_karsilastir.iz_sakla(state, len(state.setdefault("turlar", [])) + 1, lap)   # iki tur grafiği için
    state.setdefault("turlar", []).append({
        "no": len(state["turlar"]) + 1, "saat": time.strftime("%H:%M"), "sure": sure(lap_ms), "ms": lap_ms,
        "t": time.time(),
        "fark": round((lap_ms - best_ms) / 1000, 3) if best_ms else None,
        "rekor": bool(not problem and (best_ms is None or lap_ms < best_ms)),
        "ref_disi": bool(problem), "baslik": title, "notlar": list(out),
        "kayit_id": None if problem else lap["kayit_id"], "araba": araba_adi(car), "ozet": ozet})
    del state["turlar"][:-30]
    state["harita"]["adlar"] = state.get("adlar", {})
    state["map_ver"] = state.get("map_ver", 0) + 1
    gt7_rapor.kaydet(state, pist_adi(tr), viraj_adi)
    notify(title, out, kind="tur", ses=ses)
    print(f"  (Sesli özet: {ses})")
    return cmp_res


class Koc:
    """Telemetriyi dinler, turları kaydeder; arayüz (gt7_arayuz.py) başlatır."""

    def __init__(self, sel=None, catalog=None):
        self.lock = threading.Lock()
        self.sel = sel
        self.catalog = catalog if catalog is not None else load_catalog()
        self.pending = None             # arayüzden gelen (ya da otomatik bulunan) yeni pist
        self.isinma = False             # bu tur soğuk lastiklerle başladı (viraj tavsiyesi yok)
        try:                            # pist seçilmediyse ya da yanlışsa konumdan bulur
            self.tanima = PistTanima(self.catalog)
        except Exception:
            self.tanima = None
        self.state = self.new_state(sel)
        self.live = {"connected": False, "recording": False}
        self.error = None
        self.ip_request = None          # arayüzden elle girilen PS5 adresi
        self.bul_istek = False          # arayüzden "PS5'i bul" düğmesi
        self.sayma_istek = []           # arayüzden "bu turu sayma" (kayıt kimlikleri)
        self.rekor_modu = False         # açıkken replay izlenirken de tur kaydedilir (rekor turu)
        self.rekor_sil_istek = False
        self.odak = None                # odak virajı (koç ekranından): koç sadece o viraj hakkında konuşur
        self.pist_dogru = False         # seçilen pist konumdan doğrulandı mı (Time Trial hazırlık ✓)
        self.hedef_istek = None         # arayüzden hedef süre: (ms ya da None, Time Trial bilgisi ya da None)
        self.hedef_tur_istek = None     # arayüzden hedef tur: ({"tip", "araba"} ya da {} = seçim yok,)
        self.fren_ayar_istek = None     # arayüzden rekor turu fren ayarı: {"nokta", "pay"}
        self.tarayici = Tarayici()      # kayıtlı IP cevap vermezse ev ağını tarar
        self.started = time.time()
        self.canli = CanliKoc()         # virajlardan önce konuşan koç
        self.olcer = CanliOlcer()       # lastik, G, devir ışığı, motor... (arayüz)
        self.muhendis = Muhendis()      # motor / lastik / sıra / son tur telsiz anonsları
        self.muhendis_dedi = False      # "Yarış mühendisi devrede." bir kez söylenir
        self.ayar = ayar_oku()
        self.vites_oylari = []          # son turların manuel/otomatik tahmini
        self.car = None
        self.son_cmp = None
        self.hazirla_gerek = True
        # Fren noktası geri sayımı (3 bip) ve kalibrasyonu
        self.beeper = None
        self.fren = None              # BrakeCountdown
        self.fren_notu = "Fren sesi kapalı."
        self.delay, kaynak = load_delay()
        self.kalib_kaynak = kaynak
        self.kalib = None             # ReactionTest (sürüyorsa)
        self.kalib_istek = False
        if self.ayar.get("fren_sesi") != "kapali":
            self.beeper = Beeper()

    def bip_dene(self):
        if self.beeper is None:
            self.beeper = Beeper()
        self.beeper.test()

    def kalibrasyon_baslat(self):
        with self.lock:
            self.kalib_istek = True

    def rekor_ref(self):
        """Koçun referans alacağı rekor turu (Time Trial hazırlıkta seçilen hedef tur), yoksa None."""
        return secili_rekor(self.state.get("track"), self.car)

    def fren_kayma_hesapla(self, tr, kendi_pool, rek, corners):
        """Rekor turu referansken fren noktası kaç metre öne alınsın: {viraj no: m} (state["fren_kayma"]).
        Güvenlik payı (fren_payi) + "benim fren gücüme göre" (fren_noktasi = benim). Fren uyarısı da,
        "erken / geç fren" tavsiyeleri de bu kaymış noktaya göre olur. Döner: (kayma, açıklama)."""
        kayma, notlar = {}, []
        if rek and corners:
            fa = (tr or {}).get("fren_ayar") or {}       # Time Trial hazırlıkta, pist için seçilir
            if fa.get("nokta", self.ayar.get("fren_noktasi")) == "benim":
                if kendi_pool:
                    try:
                        kayma = kendi_kaymalari(rek, kendi_pool[:5], corners)
                    except Exception as e:   # ölçülemezse birebir kalır
                        print(f"(Fren gücü ölçülemedi: {e!r})")
                    notlar.append(f"kendi fren gücüne göre {len(kayma)} virajda öne alındı "
                                  f"(en çok {max(kayma.values()):.0f} m)" if kayma else
                                  "kendi fren gücün rekor turuna yakın, fren noktaları aynı")
                else:
                    notlar.append("kendi fren gücün ilk temiz turundan sonra ölçülecek")
            pay = FREN_PAYI_M.get(fa.get("pay", self.ayar.get("fren_payi")), 0)
            if pay:
                for c in corners:
                    kayma[c["no"]] = kayma.get(c["no"], 0.0) + pay
                notlar.append(f"güvenlik payı {pay} m")
        self.state["fren_kayma"] = {k: v for k, v in kayma.items() if v}
        self.canli.fren_kayma = self.state["fren_kayma"]
        return self.state["fren_kayma"], ", ".join(notlar)

    def fren_hazirla(self):
        """Fren bip sesini bu pist ve araba için en iyi fren noktalarıyla hazırlar."""
        if self.fren:
            self.delay = self.fren.delay
        self.fren = None
        tr = self.state.get("track")
        pool = reference_pool(tr["laps"].get(str(self.car), [])) if tr and self.car is not None else []
        rek = self.rekor_ref()
        corners = (tr or {}).get("corners") or (find_corners(rek) if rek else None)
        kayma, kayma_notu = self.fren_kayma_hesapla(tr, pool, rek, corners)
        if self.ayar.get("fren_sesi") == "kapali":
            self.fren_notu = "Fren sesi kapalı."
            return
        if self.beeper is None:
            self.beeper = Beeper()
        if rek:
            pool = [rek]        # bipler rekor turunun fren noktalarında
        if not tr or not corners or not pool:
            self.fren_notu = "Fren sesi ilk temiz turdan sonra başlar."
            return
        try:
            pts = brake_points(pool[:5], corners, kayma)
            self.fren = BrakeCountdown(pool[0], pts, self.beeper, self.delay)
        except Exception as e:  # ses hatası koçu durdurmasın
            self.fren_notu = f"Fren sesi hazırlanamadı: {e!r}"
            return
        self.fren_notu = (f"Fren sesi hazır: {len(self.fren.points)} fren noktası"
                          + (f" (rekor turunun fren noktaları{'; ' + kayma_notu if kayma_notu else ''})."
                             if rek else "."))

    def fren_tur_sonu(self):
        """Tur sonunda frene basma zamanlamasına göre tepki payını düzeltir."""
        if not self.fren:
            return
        res = self.fren.lap_summary()
        if res:
            n, e = res
            ne = "tam zamanındaydın" if abs(e) < 0.03 else \
                f"ortalama {abs(e):.2f} sn " + ("geç" if e > 0 else "erken")
            self.delay = self.fren.delay
            self.kalib_kaynak = "sürüş içi düzeltme"
            save_delay(self.delay, self.kalib_kaynak)
            notify(f"Fren zamanlaman: {n} virajda {ne}. "
                   f"Fren uyarısı tepki payı {self.delay:.2f} sn olarak ayarlandı.")

    @property
    def vites_turu(self):
        """("manuel"/"otomatik"/None, algılandı mı)"""
        elle = (self.ayar.get("vites_araba") or {}).get(str(self.car))   # koç ekranından bu araba için seçildi
        if elle in ("manuel", "otomatik"):
            return elle, False
        if self.ayar["vites"] in ("manuel", "otomatik"):
            return self.ayar["vites"], False
        oy = [v for v in self.vites_oylari[-3:] if v]
        if not oy:
            return None, True
        return max(set(oy), key=oy.count), True

    @property
    def manuel(self):
        return self.vites_turu[0] == "manuel"

    def set_ayar(self, ayar):
        with self.lock:
            self.ayar = ayar
            self.hazirla_gerek = True

    def canli_hazirla(self):
        self.hazirla_gerek = False
        self.fren_hazirla()
        adlari_guncelle(self.state)
        tr = self.state.get("track")
        if self.state.get("hedef_araba", -1) != self.hedef_arabasi():   # pist ya da araba değişti: hedef yeniden
            self.hedef_guncelle()
        eski = (tr or {}).get("soylenen", {}).get(str(self.car))
        rek = self.rekor_ref()
        if rek and tr and not tr.get("corners"):
            tr = dict(tr, corners=find_corners(rek))    # kendi temiz turun yokken: virajlar rekor turundan
        cmp_res, onemli = self.son_cmp, self.state.get("onemli") if self.son_cmp is not None else None
        hatirlat = self.state.get("hatirlat", ()) if self.son_cmp is not None else ()
        if self.odak:      # odak virajı: koç sadece o viraj hakkında konuşur
            cmp_res = [r if r["no"] == self.odak else dict(r, issues=[], delta=0.0) for r in cmp_res or []] \
                if cmp_res is not None else None
            onemli = [o for o in onemli or [] if o["no"] == self.odak] if onemli is not None else None
            hatirlat = [n for n in hatirlat if n == self.odak]
            eski = {k: v for k, v in (eski or {}).items() if str(k) == str(self.odak)} or None
        self.canli.odak = self.odak
        self.canli.hazirla(tr, self.car, cmp_res, self.manuel,
                           self.ayar["uyari"] == "sorunlu", self.ayar.get("fren_sesi") != "kapali",
                           esik=esikler(self.ayar), eski=eski, onemli=onemli, hatirlat=hatirlat, ref_tur=rek)
        # Hata takibi seanslar arası: bu turdan sonra söylenecek sorunlar pist kaydına yazılır
        if tr and self.son_cmp is not None and self.canli.ready:
            yeni = {str(k): {a: b for a, b in v.items() if a != "sessiz"}
                    for k, v in self.canli.soylenen.items()}
            if yeni != eski:
                tr.setdefault("soylenen", {})[str(self.car)] = yeni
                try:
                    save_track(tr)
                except OSError:
                    pass

    def new_state(self, sel):
        state = {}
        if sel:
            state["track"] = load_selected_track(sel)
        try:  # ilk temiz turdan önce pist çizgisinden kaba viraj bilgisi
            state["lib_warner"] = library_warner(sel)
        except Exception:
            state["lib_warner"] = None
        return state

    def pist_ozeti(self):
        """Pist seçilince yarış öncesi kısa özet (viraj sayısı, en keskin virajlar, düzlük)."""
        try:
            satirlar = track_summary(self.sel, self.state.get("track"))
        except Exception as e:
            satirlar = [f"Pist özeti hazırlanamadı: {e!r}"]
        if satirlar:
            notify("Pist özeti", satirlar)

    def set_track(self, sel):
        with self.lock:
            self.pending = ("track", sel)

    def set_ip(self, ip):
        with self.lock:
            self.ip_request = ip

    def tur_sayma(self, kayit_id):
        with self.lock:
            self.sayma_istek.append(str(kayit_id))

    def tur_cikar(self, kayit_id):
        """Bir turu referans turlardan çıkarır (sürücü "bu turu sayma" dedi)."""
        state = self.state
        tr = state.get("track")
        bulundu = False
        if tr:
            for car, laps in tr.get("laps", {}).items():
                kalan = [L for L in laps if L.get("kayit_id") != kayit_id]
                if len(kalan) != len(laps):
                    bulundu = True
                    laps[:] = kalan
        for t in state.get("turlar", []):
            if t.get("kayit_id") == kayit_id:
                bulundu = True
                t.update(ref_disi=True, rekor=False, kayit_id=None, sayilmadi=True)
                t["notlar"] = t["notlar"] + ["Bu tur senin isteğinle referans dışı bırakıldı."]
                if t.get("ms") in state.get("gecmis", []):
                    state["gecmis"].remove(t["ms"])
        if not bulundu:
            return
        if tr:
            try:
                save_track(tr)
            except OSError:
                pass
        self.son_cmp = None
        self.hazirla_gerek = True
        state["map_ver"] = state.get("map_ver", 0) + 1
        notify("Tur sayılmayacak: referans turlardan çıkarıldı.",
               ["Karşılaştırma ve fren uyarısı bir sonraki turdan itibaren kalan turlarla yapılır."])

    def rekor_ayarla(self, acik):
        """Arayüzden: rekor kaydı modunu aç / kapat."""
        with self.lock:
            self.rekor_modu = bool(acik)
        if acik:
            notify("Rekor kaydı açık: rekor replay'ini izle.",
                   ["GT7'de lider tablosundan rekor sahibinin replay'ini indir ve izle.",
                    "Replay'de başlangıç çizgisinden geçen ilk tam tur kaydedilir; sonra mod kendisi kapanır."])

    def rekor_sil(self):
        with self.lock:
            self.rekor_sil_istek = True

    def rekor_kaydet(self, lap, lap_ms, car):
        """Replay'den kaydedilen turu rekor turu yapar. Başarılıysa True."""
        if lap_ms <= 0 or len(lap["t"]) < 600 or lap["dist"][-1] < 500:
            notify("Rekor kaydı: tur eksik kaldı, bir sonraki tam tur bekleniyor.",
                   ["Replay'i turun başından (başlangıç çizgisinden) izlemelisin."], kind="uyari")
            return False
        problem = check_lap(lap) or time_problem(lap, lap_ms)
        out = []
        tr, selected = pist_hazirla(lap, self.state, out)
        if not problem and selected and tr.get("path") and not lap_on_path(tr["path"], lap):
            problem = "tur seçilen pistin dışında kaldı (yanlış pist mi?)"
        limit = tr["length"] if tr.get("start_ok") or selected else None
        if not problem and limit and lap["dist"][-1] < 0.95 * limit:
            problem = "tur pistten belirgin kısa (eksik kayıt)"
        if problem:
            notify("Rekor kaydı: bu tur alınmadı -> " + problem + ".",
                   ["Bir sonraki tam turu bekliyorum."], kind="uyari")
            return False
        eklendi, eski = rekor_ekle(tr, rekor_turu(lap, lap_ms, car))
        if not eklendi:
            notify(f"Rekor kaydı: {sure(lap_ms)} kayıtlı rekor turundan ({sure(eski['lap_ms'])}) yavaş, "
                   "eskisi korundu.")
            return True
        try:
            save_track(tr)
        except OSError:
            pass
        tr["hedef_tur"] = {"tip": "rekor", "araba": str(car)}   # yeni rekor turu hedef tur olur
        tr.pop("tt_hedef", None)
        try:
            save_track(tr)
        except OSError:
            pass
        self.hedef_guncelle()
        notify(f"Rekor turu kaydedildi: {sure(lap_ms)} ({araba_adi(car)})",
               out + ["Hedef tur olarak seçildi: fren uyarısı bu turun fren noktalarında çalar, canlı fark ve "
                      "tavsiyeler bu tura göredir. Time Trial hazırlık ekranından değiştirebilirsin."])
        self.son_cmp = None
        self.hazirla_gerek = True
        return True

    def tt_hedef(self, state, car):
        tr = state.get("track") or {}
        try:
            return gt7_tt.hedef(self.catalog, tr.get("official_id"), car)
        except Exception:
            return None

    def rekor_bilgi(self):
        """Arayüz için: bu pistteki rekor turları."""
        tr = self.state.get("track") or {}
        return [{"araba": araba_adi(int(c) if str(c).isdigit() else c), "kod": c, "sure": sure(r["lap_ms"]),
                 "saat": r.get("saat")} for c, r in (tr.get("rekor") or {}).items()]

    def rekor_sure(self):
        """Arayüz için: bu pist + arabanın rekor turu süresi (yoksa None)."""
        tr = self.state.get("track") or {}
        rek = (tr.get("rekor") or {}).get(str(self.car)) if self.car is not None else None
        return sure(rek["lap_ms"]) if rek and rek.get("lap_ms") else None

    def hedef_ayarla(self, ms, tt=None):
        """Arayüzden hedef süre (ms; None = sil). tt verilirse (Time Trial) {"etiket", "etkinlik", "bitis"}:
        hedef bu pist için, arabadan bağımsız; verilmezse bu arabanın kendi hedefi."""
        with self.lock:
            self.hedef_istek = (ms, tt)

    def odak_ayarla(self, no):
        """Koç ekranından odak virajı (None = kapalı)."""
        with self.lock:
            self.odak = no
            self.hazirla_gerek = True

    def hedef_tur_ayarla(self, secim):
        """Arayüzden (Time Trial hazırlık): {"tip": "rekor", "araba": kod} / {"tip": "eniyi"} / {} (seçim yok)."""
        with self.lock:
            self.hedef_tur_istek = (secim,)

    def fren_ayar_ayarla(self, ayar):
        with self.lock:
            self.fren_ayar_istek = ayar

    def hedef_tur_uygula(self, secim):
        """Hedef tur hem hedef süre hem referanstır; sadece süre hedefi (tt_hedef) kalkar."""
        tr = self.state.get("track")
        if not tr:
            notify("Hedef tur için önce antrenmanı başlat.", kind="uyari")
            return
        tr["hedef_tur"] = dict(secim) if secim and secim.get("tip") in ("rekor", "eniyi") else None
        if tr["hedef_tur"]:
            tr.pop("tt_hedef", None)
        try:
            save_track(tr)
        except OSError:
            pass
        self.son_cmp = None                  # referans değişti: eski karşılaştırma geçersiz
        self.hazirla_gerek = True
        self.hedef_guncelle()
        h = self.state.get("hedef")
        if tr["hedef_tur"] and tr["hedef_tur"]["tip"] == "rekor":
            notify(f"Hedef tur: rekor turu ({araba_adi(int(tr['hedef_tur']['araba']))}). Koç bu tura göre konuşur.")
        elif tr["hedef_tur"]:
            notify("Hedef tur: kendi en iyi turun." + (f" {h['hedef']}" if h else ""))

    def hedef_arabasi(self):
        """Hedef analizi hangi arabanın turlarıyla (sürülen araba)."""
        return self.car

    def hedef_guncelle(self):
        tr = self.state.get("track")
        try:
            self.state["hedef"] = hedef_durumu(tr, self.hedef_arabasi())
        except Exception as e:
            self.state["hedef"] = None
            print(f"(Hedef analizi yapılamadı: {e!r})")
        self.state["hedef_araba"] = self.hedef_arabasi()
        self.state["map_ver"] = self.state.get("map_ver", 0) + 1

    def hedef_uygula(self, ms, tt=None):
        tr = self.state.get("track")
        car = self.car
        if not tr or (tt is None and car is None):
            notify("Hedef süre için önce pisti seç ve arabayla piste çık.", kind="uyari")
            return
        if ms:
            tr["hedef_tur"] = None    # sadece süre hedefi: koç kendi en iyi geçişlerine göre konuşur
            self.son_cmp = None
            self.hazirla_gerek = True
        if tt is not None:            # Time Trial hedefi: pist için
            if ms:
                tr["tt_hedef"] = {"ms": int(ms), "etiket": tt.get("etiket"), "etkinlik": tt.get("etkinlik"),
                                  "bitis": tt.get("bitis")}
            else:
                tr.pop("tt_hedef", None)
        else:                         # elle yazılan hedef: bu araba için; Time Trial hedefinin yerine geçer
            tr.pop("tt_hedef", None)
            hd = tr.setdefault("hedef", {})
            if ms:
                hd[str(car)] = int(ms)
            else:
                hd.pop(str(car), None)
        etiket = (tt or {}).get("etiket")
        try:
            save_track(tr)
        except OSError:
            pass
        self.hedef_guncelle()
        h = self.state.get("hedef")
        if ms:
            ad = gt7_tt.HEDEF_ADLARI.get(etiket)
            notify(f"Hedef süre: {sure(int(ms))}" + (f" (Time Trial: {ad.lower()})" if ad else ""),
                   h["satirlar"] if h else [])
        elif h and h.get("kaynak") == "rekor":
            notify(f"Hedef artık rekor turu süresi: {h['hedef']}")
        else:
            notify("Hedef süre silindi.")

    def karsilastirma(self, a_id=None, b_id=None):
        """Arayüzdeki "iki tur" grafiği: seçenekler ve (a, b verildiyse) grafik verisi.
        Kimlikler: "t5" = bu seansın 5. turu, "eniyi" = bu arabanın kayıtlı en iyi turu, "rekor" = rekor turu."""
        state = self.state
        tr = state.get("track") or {}
        car = str(self.car) if self.car is not None else None
        kaynak = {}
        for t in state.get("turlar", []):
            iz = state.get("izler", {}).get(t["no"])
            if iz is not None:
                kaynak[f"t{t['no']}"] = (f"Tur {t['no']} · {t['sure']}" + (" (ref. dışı)" if t.get("ref_disi") else ""), iz)
        en_iyi = min(tr.get("laps", {}).get(car, []) if car else [], key=lambda L: L["lap_ms"], default=None)
        if en_iyi:
            kaynak["eniyi"] = (f"Kayıtlı en iyi tur · {sure(en_iyi['lap_ms'])}", en_iyi)
        rek = (tr.get("rekor") or {}).get(car) if car else None
        if rek:
            kaynak["rekor"] = (f"Rekor turu · {sure(rek['lap_ms'])}", rek)
        secenek = [{"id": k, "ad": v[0]} for k, v in kaynak.items()]
        son = [k for k in kaynak if k.startswith("t")]
        b = son[-1] if son else None
        if en_iyi and b and len(son) > 1 and kaynak[b][1].get("lap_ms") == en_iyi["lap_ms"]:
            b = son[-2]          # son tur zaten en iyi tur: kendisiyle değil bir öncekiyle karşılaştır
        out = {"secenekler": secenek[::-1],
               "varsayilan": {"a": "eniyi" if en_iyi else (son[-2] if len(son) > 1 else None), "b": b}}
        if a_id in kaynak and b_id in kaynak:
            out["grafik"] = gt7_karsilastir.karsilastir(kaynak[a_id][1], kaynak[b_id][1], tr.get("corners"))
            out["grafik"].update(a_ad=kaynak[a_id][0], b_ad=kaynak[b_id][0])
        return out

    def ps5_bul(self):
        with self.lock:
            self.bul_istek = True

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:  # tur analizi sürerken gelen paketler kaybolmasın diye büyük alım tamponu
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        except OSError:
            pass
        try:
            sock.bind(("0.0.0.0", RECV_PORT))
        except OSError:
            self.error = ("33740 kapısı kullanımda. Telemetri kullanan başka bir programı "
                          "veya açık kalan diğer koç penceresini kapatıp koçu yeniden başlat.")
            print("HATA: " + self.error)
            return
        sock.settimeout(1.0)

        target = "255.255.255.255"
        if os.path.exists(IP_FILE):
            target = open(IP_FILE, encoding="utf-8").read().strip() or target

        last_path_check = 0
        tt_kontrol = 0
        far_count = 0
        warned_far = False
        lap = new_lap()
        cur_lap_no = None
        clock = LapClock()              # tur saati: paket numarasından, duraklatma eklenmez
        clock_t = 0.0                   # aynı saatle sürekli zaman (G hesabı için)
        recording = False
        last_pos = None
        last_hb = 0
        connected = False
        # En zengin veri biçimini ("C") dene; cevap gelmezse "A" ile dönüşümlü dene
        hb_fmt = "C"
        yakin_say = 0                   # seçilen pistin çizgisine yakın geçen saniye (pist doğrulama)
        hb_switch = time.time() + 5
        self.pist_ozeti()

        while True:
            with self.lock:
                pending, self.pending = self.pending, None
                ip_req, self.ip_request = self.ip_request, None
                kalib_istek, self.kalib_istek = self.kalib_istek, False
                bul_istek, self.bul_istek = self.bul_istek, False
                sayma, self.sayma_istek = self.sayma_istek, []
                rekor_sil, self.rekor_sil_istek = self.rekor_sil_istek, False
                rekor_modu = self.rekor_modu
                hedef_istek, self.hedef_istek = self.hedef_istek, None
                hedef_tur_istek, self.hedef_tur_istek = self.hedef_tur_istek, None
                fren_ayar_istek, self.fren_ayar_istek = self.fren_ayar_istek, None
            if rekor_sil:
                tr = self.state.get("track")
                if tr and tr.get("rekor", {}).pop(str(self.car), None) is not None:
                    try:
                        save_track(tr)
                    except OSError:
                        pass
                    notify("Bu arabanın rekor turu silindi.")
                    self.hedef_guncelle()
                    self.son_cmp = None        # koç yeniden kendi en iyi turuna göre konuşur
                    self.hazirla_gerek = True
            for kid in sayma:
                try:
                    self.tur_cikar(kid)
                except Exception as e:
                    notify("Tur çıkarılamadı.", [repr(e)], kind="uyari")
            if kalib_istek:
                if self.beeper is None:
                    self.beeper = Beeper()
                self.kalib = ReactionTest(self.beeper, say=lambda m: notify(m))
            if pending:
                self.sel = pending[1]
                self.state = self.new_state(self.sel)
                self.pist_dogru = len(pending) > 2    # konumdan bulunduysa zaten doğrulandı
                self.odak = None
                yakin_say = 0
                self.son_cmp = None
                self.hazirla_gerek = True
                far_count, warned_far = 0, False
                if self.tanima:
                    self.tanima.sifirla()
                if len(pending) > 2:     # konumdan otomatik bulundu
                    notify("Pist otomatik bulundu: " + self.sel["name"],
                           ["Yanlışsa üstteki 'Pist değiştir' düğmesinden elle seçebilirsin."])
                else:
                    notify("Pist: " + (self.sel["name"] if self.sel else "seçilmedi (otomatik tanıma)"))
                self.pist_ozeti()
            if hedef_tur_istek:
                try:
                    self.hedef_tur_uygula(hedef_tur_istek[0])
                except Exception as e:
                    notify("Hedef tur kaydedilemedi.", [repr(e)], kind="uyari")
            if fren_ayar_istek and self.state.get("track"):
                self.state["track"]["fren_ayar"] = fren_ayar_istek
                try:
                    save_track(self.state["track"])
                except OSError:
                    pass
                self.son_cmp = None
                self.hazirla_gerek = True
            if hedef_istek:     # pist değişikliğinden sonra: Time Trial'dan "pisti seç + hedef" birlikte gelebilir
                try:
                    self.hedef_uygula(*hedef_istek)
                except Exception as e:
                    notify("Hedef süre kaydedilemedi.", [repr(e)], kind="uyari")
            if ip_req:
                target = ip_req
                last_hb = 0
            sel, state = self.sel, self.state

            now = time.time()
            if now - tt_kontrol > 60:   # haftalık time trial raporu (eskiyse arka planda indirilir)
                tt_kontrol = now
                gt7_tt.guncelle()
            # Kayıtlı adres cevap vermiyorsa (ya da düğmeye basıldıysa) ev ağında PS5'i ara
            sessiz = now - (self.live.get("last_packet") or self.started) > TARAMA_BEKLE_S
            if (bul_istek or sessiz) and not self.tarayici.aktif:
                self.tarayici.baslat()
                notify("PS5 ev ağında aranıyor" + (f" ({self.tarayici.ag})" if self.tarayici.ag else "") + "…",
                       ["PS5 açık ve GT7 çalışıyor olmalı."])
            if self.tarayici.aktif:
                self.tarayici.adim(sock, hb_fmt)
            if not connected and now > hb_switch:
                hb_fmt = "A" if hb_fmt == "C" else "C"
                hb_switch = now + 5
            if now - last_hb > 1.5:
                send_heartbeat(sock, target, hb_fmt)
                last_hb = now
            if connected and now - self.live.get("last_packet", now) > 5:
                # Veri kesildi (PS5 kapandı / oyun kapandı): yeniden gelince "bağlandı" denir,
                # o zamana kadar "C" / "A" biçimi dönüşümlü istenir (ilk açılıştaki gibi)
                self.live["connected"] = False
                connected = False
                hb_switch = now + 5
            try:
                data, addr = sock.recvfrom(4096)
            except (socket.timeout, ConnectionResetError):
                continue
            yonlendir_port = self.ayar.get("yonlendir_port")
            if yonlendir_port:
                # Veri yönlendirme (16 Kasım 2026): PS5'ten gelen paket olduğu gibi bu bilgisayarda başka bir porta
                # da kopyalanır; SimHub gibi bir program o portu dinleyerek koçla aynı anda çalışabilir.
                try:
                    sock.sendto(data, ("127.0.0.1", int(yonlendir_port)))
                except (OSError, ValueError):
                    pass
            p = decrypt_packet(data)
            if p is None:
                continue
            if not connected or addr[0] != target:
                eski_hedef = target
                connected = True
                target = addr[0]
                try:
                    with open(IP_FILE, "w", encoding="utf-8") as f:
                        f.write(target)
                except OSError:
                    pass
                if self.tarayici.aktif:
                    self.tarayici.durdur()
                    notify(f"PS5 bulundu: {target}" + (f" (eski adres {eski_hedef} artık geçersizdi)"
                                                       if eski_hedef and not eski_hedef.startswith("255.") else ""))
                else:
                    notify(f"PlayStation'a bağlandı: {target}")
                if not self.muhendis_dedi:
                    self.muhendis_dedi = True
                    notify("Yarış mühendisi devrede.", kind="muhendis")

            d = parse(p)
            pkt = parse_packet(p)
            pid = struct.unpack_from("<i", p, 0x70)[0]
            flags = struct.unpack_from("<H", p, 0x8E)[0]
            on_track = bool(flags & 1)
            paused = bool(flags & 2) or bool(flags & 4)
            # Rekor kaydında replay de kaydedilir (replay'de "pistte" bayrağı kapalıdır)
            kayit_acik = on_track or rekor_modu
            lap_no = d["tur"]

            if d["araba"] != self.car:
                self.car = d["araba"]
                notify(f"Araba: {araba_adi(self.car)}")
                self.son_cmp = None
                self.hazirla_gerek = True
            if cur_lap_no is None:
                cur_lap_no = lap_no
            dt = clock.step(pid)
            clock_t += dt
            if lap_no != cur_lap_no and lap_change_ok(lap_no, cur_lap_no, kayit_acik, paused):
                if recording and lap_no == cur_lap_no + 1 and rekor_modu:
                    try:
                        if self.rekor_kaydet(lap, d["son_tur"], d["araba"]):
                            with self.lock:
                                self.rekor_modu = False
                            self.son_cmp = None
                            self.hazirla_gerek = True
                    except Exception as e:
                        notify("Rekor turu kaydedilemedi.", [repr(e)], kind="uyari")
                elif recording and lap_no == cur_lap_no + 1:
                    try:
                        self.fren_tur_sonu()
                        self.vites_oylari.append(vites_turu_tahmin(lap))
                        kalan = d["toplam_tur"] - lap_no + 1 if d["toplam_tur"] > 0 else None
                        self.son_cmp = lap_end(lap, d["son_tur"], d["araba"], state,
                                               {"manuel": self.manuel, "kalan_tur": kalan,
                                                "dagilim": self.ayar.get("guc_dagilimi", {}).get(str(d["araba"])),
                                                "duzeltilen": list(self.canli.duzeltilen),
                                                "kapasite": pkt.fuel_capacity, "tur_no": lap_no,
                                                "fren_sesi": self.fren is not None,
                                                "rekor_tur": self.rekor_ref(), "odak": self.odak,
                                                "yaris_sessiz": d["toplam_tur"] > 0
                                                and self.ayar.get("yaris_tavsiye") != "acik",
                                                "tt": self.tt_hedef(state, d["araba"]),
                                                "sira": (pkt.race_position, pkt.total_positions)
                                                if d["toplam_tur"] > 0 and pkt.total_positions >= 2 else None})
                        self.hazirla_gerek = True
                    except Exception as e:  # analiz hatası koçu durdurmasın
                        notify("Tur analizinde hata oldu, kayıt devam ediyor.", [repr(e)], kind="uyari")
                # yeni tur başlıyor
                self.canli.reset()
                onceki = onceki_son(lap) if recording and lap_no == cur_lap_no + 1 else None
                lap = new_lap()
                if onceki:
                    lap["onceki_son"] = onceki
                recording = records(lap_no, d["toplam_tur"])
                last_pos = None
                cur_lap_no = lap_no

            if recording and kayit_acik and not paused:
                x, _, z = d["konum"]
                if last_pos is None:
                    dist = 0.0
                else:
                    dist = lap["dist"][-1] + math.hypot(x - last_pos[0], z - last_pos[1])
                last_pos = (x, z)
                lap["t"].append(lap["t"][-1] + dt if lap["t"] else 0.0)
                lap["dist"].append(dist)
                lap["x"].append(x)
                lap["z"].append(z)
                lap["speed"].append(d["hiz"])
                lap["throttle"].append(d["gaz"])
                lap["brake"].append(d["fren"])
                lap["gear"].append(d["vites"])
                lap["rpm"].append(d["devir"])
                lap["suggested_gear"].append(d["onerilen_vites"])
                for w, slip in zip(("fl", "fr", "rl", "rr"), pkt.wheel_slips):
                    lap[f"slip_{w}"].append(slip)
                lap["sus_fl"].append(pkt.suspension_fl)
                lap["sus_fr"].append(pkt.suspension_fr)
                lap["sus_rl"].append(pkt.suspension_rl)
                lap["sus_rr"].append(pkt.suspension_rr)
                lap["fuel"].append(pkt.fuel_level)
                note_packet(lap, pkt)
                lap["revlim"].append(1 if flags & 0x20 else 0)
                lap["tt_f"].append((pkt.tire_temp_fl + pkt.tire_temp_fr) / 2)
                lap["tt_r"].append((pkt.tire_temp_rl + pkt.tire_temp_rr) / 2)
                # Önden / arkadan kayma için: gövde kayması, dönme hızı, teker açısı (sadece C biçimi)
                lap["slip_body"].append(pkt.body_slip_deg)
                lap["yaw"].append(abs(pkt.angular_velocity_y))
                ws = pkt.wheel_steering_rad
                lap["wheel_angle"].append((ws[0] + ws[1]) / 2 if ws else None)
                if pkt.wheelbase_m:
                    lap["wheelbase"] = pkt.wheelbase_m
                lap["body_h"].append(pkt.body_height)
                vs = vites_sayisi(pkt)
                if vs:
                    lap["vites_sayisi"] = vs
                if len(lap["t"]) == 1:      # turun ilk paketi: lastikler soğuksa ısınma turu
                    ort = lastik_ort(lap["tt_f"][-1], lap["tt_r"][-1])
                    self.isinma = ort is not None and ort < ISINMA_C
                    if self.isinma and on_track:
                        notify("Isınma turu. Lastikleri ısıt, bu turu saymayacağım.", kind="muhendis")
                        self.muhendis.son_soylenen["lastik_soguk"] = clock_t   # aynı uyarı iki kez okunmasın

            # Henüz temiz tur yoksa: pist çizgisinden kaba viraj bilgisi (ekranda, sesli değil)
            lw = state.get("lib_warner")
            if lw and not self.canli.ready and recording and on_track and not paused:
                x, _, z = d["konum"]
                for msg in lw.update(x, z, d["hiz"], lap_no, time.time()):
                    notify(msg, kind="tahmin")
            # Canlı koç: referans turda neredeyiz, sıradaki viraj için uyarı var mı?
            if self.hazirla_gerek:
                try:
                    self.canli_hazirla()
                except Exception as e:
                    notify("Canlı koç hazırlanamadı.", [repr(e)], kind="uyari")
            fark = None
            if recording and on_track and not paused and lap["t"]:
                uyari, fark, _ = self.canli.adim(lap["x"][-1], lap["z"][-1], lap["dist"][-1], lap["t"][-1],
                                                 d["hiz"], d["fren"], d["gaz"],
                                                 lap["loose"][-1] if lap.get("loose") else None)
                islak = state.get("islak")   # ıslak pist şüphesi: kuru tura göre uyarılar susar
                if d["toplam_tur"] > 0 and self.ayar.get("yaris_tavsiye") != "acik":
                    uyari = self.canli.cikis = None   # yarışta viraj tavsiyesi yok (ayar yaris_tavsiye)
                if self.isinma:
                    uyari = self.canli.cikis = None   # ısınma turunda viraj tavsiyesi yok
                if uyari and not islak:
                    notify(uyari, kind="anlik", ses=uyari)
                cikis, self.canli.cikis = self.canli.cikis, None
                if cikis and not islak and self.ayar.get("cikis_yorumu") != "kapali":
                    notify(cikis, kind="sonra", ses=cikis)
            # Yarış mühendisi: motor, lastik, sıra, son tur (kısa telsiz anonsları)
            try:
                for metin, kritik in self.muhendis.guncelle(clock_t, pkt, on_track, paused):
                    notify(metin, kind="uyari" if kritik else "muhendis")
                if self.muhendis.islak_olay:
                    self.muhendis.islak_olay = False
                    if not state.get("islak"):
                        state["islak"] = True
                        notify("Islak pist şüphesi: viraj uyarıları susuyor.",
                               ["Viraj öncesi uyarılar ve çıkış yorumları kuru turlarına göre; pist kuruyana kadar "
                                "(en iyi turuna %2 yaklaşınca) susarlar. Mühendis anonsları sürer."])
            except Exception:
                pass

            # Kalibrasyon testi ve fren noktası geri sayımı (3 bip)
            if self.kalib:
                k = self.kalib
                k.update(now, d["hiz"], d["fren"], on_track, paused)
                if k.result is not None:
                    self.delay = k.result
                    self.kalib_kaynak = "tepki testi"
                    if self.fren:
                        self.fren.delay = k.result
                    self.kalib = None
            elif self.fren and on_track and not paused:
                x, _, z = d["konum"]
                self.fren.update(x, z, d["hiz"], d["fren"])

            # Seçilen pist bu değil gibiyse bir kez uyar (5 sn üst üste çizgiden uzaksa)
            if sel and sel["path"] and not warned_far and on_track and not paused \
                    and now - last_path_check >= 1:
                last_path_check = now
                x, _, z = d["konum"]
                uzak = distance_to_path(sel["path"], x, z) > FAR_LIMIT
                far_count = far_count + 1 if uzak else 0
                yakin_say = 0 if uzak else yakin_say + 1
                if yakin_say >= PIST_ONAY_S:
                    self.pist_dogru = True     # arayüzde "✓ Pist": konumdan doğrulandı
                if far_count >= 5:
                    warned_far = True
                    if self.tanima:
                        self.tanima.sifirla()
                    notify(f"UYARI: Seçtiğin pist bu değil gibi ({sel['name']}).",
                           ["Doğru pisti arıyorum; istersen üstteki 'Pist değiştir' düğmesinden elle seç."], kind="uyari")

            # Otomatik pist tanıma: pist seçilmediyse ya da seçilen pist yanlışsa konumdan bul
            if self.tanima and (sel is None or warned_far) and kayit_acik and not paused:
                x, _, z = d["konum"]
                bulunan = self.tanima.ekle(x, z)
                if bulunan and not (sel and bulunan["id"] == sel["id"]):
                    with self.lock:
                        if self.pending is None:   # bu arada elle seçildiyse ona dokunma
                            self.pending = ("track", bulunan, "oto")
                    try:
                        write_last(bulunan)
                    except OSError:
                        pass
                elif bulunan:
                    self.tanima.sifirla()

            try:
                ek = self.olcer.update(clock_t, d["konum"][0], d["konum"][2], d["hiz"], pkt, flags)
            except Exception:
                ek = {}
            self.live = {
                "connected": True, "target": target, "last_packet": now,
                "recording": recording, "on_track": on_track, "paused": paused,
                "hiz": d["hiz"], "vites": vites_yazi(d["vites"]),
                "onerilen": vites_yazi(d["onerilen_vites"]) if d["onerilen_vites"] not in (0, 15) else "",
                "devir": d["devir"], "gaz": d["gaz"], "fren": d["fren"],
                "tur": lap_no, "toplam_tur": d["toplam_tur"],
                "son_tur": sure(d["son_tur"]), "en_iyi": sure(d["en_iyi"]),
                "araba": d["araba"], "araba_adi": araba_adi(d["araba"]), "yakit": pkt.fuel_level, "x": d["konum"][0], "z": d["konum"][2],
                "fark": fark, "vites_turu": self.vites_turu[0], "vites_algilandi": self.vites_turu[1],
                "canli_hazir": self.canli.ready, "islak": bool(state.get("islak")),
                "c_bicimi": pkt.wheel_steering_rad is not None,
                "siradaki": self.canli.siradaki if self.canli.ready and recording else None,
                "bip": getattr(self.fren, "bip_durum", None) if self.fren else None,
                "fren_notu": self.fren_notu, "tepki_payi": round(self.delay, 2),
                "kalib_kaynak": self.kalib_kaynak, "kalibrasyon": self.kalib is not None,
                "rekor_modu": rekor_modu, "rekor_ref": bool(self.rekor_ref()),
                "pist_dogru": bool(self.pist_dogru and sel), "pist_secili": bool(sel),
                "cekis": cekis_turu(d["araba"]) if d["araba"] else None,
                "strateji": gt7_strateji.kisa(state.get("strateji")) if d["toplam_tur"] > 0 else None,
                **ek,
            }
