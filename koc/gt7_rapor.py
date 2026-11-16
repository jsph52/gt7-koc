# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Seans raporu
Tek sayfalık özet: kaç tur, en iyi tur, gelişim (tur süreleri grafiği), en çok düzelen ve hâlâ zaman
kaybettiren virajlar, hedef, öneriler. Koç ekranında "Rapor" düğmesiyle açılır; telefondan
http://<bilgisayar>:8765/rapor adresiyle. Her turdan sonra raporlar/ klasörüne de yazılır
(seans başına bir dosya, açılınca tarayıcıda görünür).
"""
import html
import os
import re
import time

from gt7_paket import sure
from gt7_yol import USER_DIR

RAPOR_DIR = os.path.join(USER_DIR, "raporlar")
EN_AZ_FARK = 0.03      # viraj düzelmesi / kaybı bundan küçükse yazılmaz


def _e(s):
    return html.escape(str(s))


def _ort(v):
    return sum(v) / len(v) if v else None


def viraj_gelisimi(seans_viraj, adi=None):
    """Seansın ilk ve son yarısında her virajın ortalama farkı: (en çok düzelenler, hâlâ kaybettirenler)."""
    temiz = [g["v"] for g in seans_viraj if g.get("temiz", True)]
    if len(temiz) < 3:
        return [], []
    yari = len(temiz) // 2
    ilk, son = temiz[:yari], temiz[yari:]
    nolar = sorted({int(n) for g in temiz for n in g})
    duzelen, kayip = [], []
    for no in nolar:
        a = _ort([g[str(no)] for g in ilk if g.get(str(no)) is not None])
        b = _ort([g[str(no)] for g in son if g.get(str(no)) is not None])
        if a is None or b is None:
            continue
        ad = adi(no) if adi else f"Viraj {no}"
        if a - b >= EN_AZ_FARK:
            duzelen.append((ad, a - b))
        son3 = _ort([g[str(no)] for g in temiz[-3:] if g.get(str(no)) is not None])
        if son3 is not None and son3 >= EN_AZ_FARK:
            kayip.append((ad, son3))
    duzelen.sort(key=lambda x: -x[1])
    kayip.sort(key=lambda x: -x[1])
    return duzelen[:3], kayip[:3]


def _grafik(turlar):
    """Tur süreleri: temiz turlar turuncu noktalar + çizgi, referans dışı gri halka, en iyi yıldız."""
    noktalar = [(t["no"], t["ms"], t.get("ref_disi")) for t in turlar if t.get("ms")]
    if len(noktalar) < 2:
        return ""
    W, H, SOL, SAG, UST, ALT = 640, 230, 64, 16, 28, 30
    temiz = [m for _, m, r in noktalar if not r] or [m for _, m, _ in noktalar]
    lo, hi = min(temiz), max(temiz)
    # referans dışı çok yavaş turlar grafiği ezmesin: üst sınır en iyinin %8 fazlası
    hi = min(max(hi, max(m for _, m, _ in noktalar)), lo * 1.08)
    if hi - lo < 500:
        hi = lo + 500
    n0, n1 = noktalar[0][0], noktalar[-1][0]
    X = lambda no: SOL + (no - n0) / ((n1 - n0) or 1) * (W - SOL - SAG)
    Y = lambda ms: UST + (min(ms, hi) - lo) / (hi - lo) * (H - UST - ALT)
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Tur süreleri">']
    for k in range(4):
        ms = lo + (hi - lo) * k / 3
        y = Y(ms)
        s.append(f'<line x1="{SOL}" x2="{W - SAG}" y1="{y:.1f}" y2="{y:.1f}" stroke="#232833"/>'
                 f'<text x="{SOL - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="11" fill="#8a93a3">{sure(int(ms))}</text>')
    temiz_n = [(no, ms) for no, ms, r in noktalar if not r]
    if len(temiz_n) >= 2:
        s.append('<polyline fill="none" stroke="#ff6a3d" stroke-width="2" stroke-linejoin="round" points="'
                 + " ".join(f"{X(no):.1f},{Y(ms):.1f}" for no, ms in temiz_n) + '"/>')
    en_iyi = min(temiz_n, key=lambda x: x[1]) if temiz_n else None
    for no, ms, r in noktalar:
        x, y = X(no), Y(ms)
        if r:
            s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="none" stroke="#5d6575" stroke-width="2"/>')
        else:
            s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#ff6a3d" stroke="#12151b" stroke-width="2"/>')
        s.append(f'<text x="{x:.1f}" y="{H - 10}" text-anchor="middle" font-size="11" fill="#5d6575">{no}</text>')
    if en_iyi:
        s.append(f'<text x="{X(en_iyi[0]):.1f}" y="{Y(en_iyi[1]) - 10:.1f}" text-anchor="middle" font-size="12" '
                 f'font-weight="700" fill="#eef1f6">★ {sure(en_iyi[1])}</text>')
    s.append("</svg>")
    return "".join(s)


CSS = """
:root{color-scheme:dark}*{box-sizing:border-box}
body{margin:0;background:#0a0c10;color:#eef1f6;font:15px/1.5 "Segoe UI",system-ui,sans-serif;font-variant-numeric:tabular-nums}
main{max-width:860px;margin:0 auto;padding:20px 16px 40px}
h1{font-size:24px;margin:0}h2{font-size:12px;letter-spacing:.14em;color:#5d6575;text-transform:uppercase;margin:22px 0 8px}
.alt{color:#8a93a3;font-size:14px}
.kutular{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:14px}
.kutu{background:#12151b;border:1px solid #232833;border-radius:14px;padding:10px 14px}
.kutu small{display:block;font-size:11px;letter-spacing:.1em;color:#5d6575;text-transform:uppercase;font-weight:700}
.kutu b{font-size:24px}.kutu span{display:block;font-size:13px;color:#8a93a3}
.iyi{color:#26c281}.kotu{color:#ef5350}
.kart{background:#12151b;border:1px solid #232833;border-radius:14px;padding:12px 16px}
svg{width:100%;height:auto;display:block}
ul{margin:0;padding-left:20px}li{margin:3px 0}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:6px 8px;border-bottom:1px solid #232833;text-align:left}
th{color:#8a93a3;font-weight:600}tr.disi td{color:#5d6575}
.iki{display:grid;grid-template-columns:1fr 1fr;gap:10px}@media(max-width:600px){.iki{grid-template-columns:1fr}}
"""


def rapor_html(state, pist_adi, adi=None):
    """Bu seansın raporu (tam HTML sayfası)."""
    turlar = state.get("turlar") or []
    temiz = [t for t in turlar if not t.get("ref_disi")]
    bas = state.get("seans_bas") or time.strftime("%d.%m.%Y %H:%M")
    arabalar = sorted({t.get("araba") for t in turlar if t.get("araba")})
    p = [f'<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">'
         f'<meta name="viewport" content="width=device-width, initial-scale=1">'
         f'<title>Seans raporu · {_e(pist_adi)}</title><style>{CSS}</style></head><body><main>',
         f'<h1>Seans raporu · {_e(pist_adi)}</h1>',
         f'<div class="alt">{_e(bas)}' + (f' – {_e(turlar[-1]["saat"])}' if turlar else "")
         + (f' · {_e(", ".join(arabalar))}' if arabalar else "") + '</div>']
    if not turlar:
        p.append('<p class="alt" style="margin-top:20px">Bu seansta henüz tamamlanan tur yok.</p></main></body></html>')
        return "".join(p)
    en_iyi = min(temiz, key=lambda t: t["ms"]) if temiz else None
    ilk = temiz[0] if temiz else None
    kutu = lambda ust, b, alt="", sinif="": (f'<div class="kutu"><small>{_e(ust)}</small><b class="{sinif}">{_e(b)}</b>'
                                             f'<span>{_e(alt)}</span></div>')
    k = [kutu("Tur", len(turlar), f"{len(temiz)} temiz, {len(turlar) - len(temiz)} referans dışı")]
    if en_iyi:
        k.append(kutu("Seansın en iyisi", en_iyi["sure"], f"{en_iyi['no']}. tur, {en_iyi['saat']}"))
    if ilk and en_iyi and ilk is not en_iyi:
        g = (ilk["ms"] - en_iyi["ms"]) / 1000
        k.append(kutu("Gelişim", f"−{g:.3f} sn", f"ilk temiz tur {ilk['sure']}", "iyi"))
    ideal = (state.get("harita") or {}).get("ideal")
    if ideal:
        k.append(kutu("İdeal tur", ideal, "her virajın en iyi geçişi"))
    hd = state.get("hedef")
    if hd and hd.get("kalan") is not None:
        k.append(kutu("Hedef", hd["hedef"], "geçildi ✓" if hd["kalan"] <= 0 else f"{hd['kalan']:.3f} sn kaldı",
                      "iyi" if hd["kalan"] <= 0 else ""))
    p.append('<div class="kutular">' + "".join(k) + "</div>")
    graf = _grafik(turlar)
    if graf:
        p.append('<h2>Tur süreleri</h2><div class="kart">' + graf
                 + '<div class="alt">Turuncu: temiz turlar · gri halka: referans dışı turlar · alttaki sayılar tur numarası</div></div>')
    duzelen, kayip = viraj_gelisimi(state.get("seans_viraj") or [], adi)
    if duzelen or kayip:
        p.append('<h2>Virajlar</h2><div class="iki">')
        p.append('<div class="kart"><b class="iyi">En çok düzelen</b><ul>'
                 + ("".join(f"<li>{_e(a)}: {v:.2f} sn daha hızlı</li>" for a, v in duzelen)
                    or '<li class="alt">Belirgin düzelme yok.</li>') + "</ul></div>")
        p.append('<div class="kart"><b class="kotu">Hâlâ zaman kaybettiren (son 3 tur)</b><ul>'
                 + ("".join(f"<li>{_e(a)}: tur başına {v:.2f} sn</li>" for a, v in kayip)
                    or '<li class="alt">Yok, virajlar en iyi geçişlerine yakın.</li>') + "</ul></div>")
        p.append("</div>")
    if hd and hd.get("satirlar"):
        p.append('<h2>Hedef</h2><div class="kart"><ul>' + "".join(f"<li>{_e(x)}</li>" for x in hd["satirlar"])
                 + "</ul></div>")
    oneriler = state.get("oneriler") or []
    if oneriler:
        p.append('<h2>Ayar önerileri</h2><div class="kart"><ul>' + "".join(
            f"<li><b>{_e(o.get('baslik', ''))}</b> — {_e(o.get('neden', ''))}</li>" for o in oneriler[:5]) + "</ul></div>")
    oz = [t["ozet"] for t in temiz if t.get("ozet")]
    if oz:
        o = {k_: _ort([x[k_] for x in oz]) for k_ in ("tam_gaz", "fren", "bosta")}
        p.append(f'<h2>Sürüş özeti (temiz tur ortalaması)</h2><div class="kart">Tam gaz %{o["tam_gaz"]:.0f} · '
                 f'fren %{o["fren"]:.0f} · boşta %{o["bosta"]:.0f} · en yüksek hız '
                 f'{max(x["max_hiz"] for x in oz):.0f} km/s</div>')
    p.append('<h2>Turlar</h2><div class="kart"><table><tr><th>#</th><th>Saat</th><th>Süre</th><th>Fark</th><th></th></tr>')
    for t in turlar:
        fark = "" if t.get("fark") is None else f"{t['fark']:+.3f}"
        p.append(f'<tr class="{"disi" if t.get("ref_disi") else ""}"><td>{t["no"]}</td><td>{_e(t["saat"])}</td>'
                 f'<td>{_e(t["sure"])}</td><td>{fark}</td>'
                 f'<td>{"★" if t.get("rekor") else ("ref. dışı" if t.get("ref_disi") else "")}</td></tr>')
    p.append("</table></div>")
    p.append('<p class="alt" style="margin-top:20px">GT7 Türkçe Koç · fark: o andaki en iyi temiz tura göre.</p>')
    p.append("</main></body></html>")
    return "".join(p)


def dosya_adi(state, pist_adi):
    bas = state.get("seans_dosya") or time.strftime("%Y%m%d_%H%M")
    ad = re.sub(r"[^A-Za-z0-9]+", "_", pist_adi or "pist").strip("_")[:40] or "pist"
    return f"seans_{bas}_{ad}.html"


def kaydet(state, pist_adi, adi=None):
    """Raporu raporlar/ klasörüne yazar (seans boyunca aynı dosya). Yolu döndürür, olmazsa None."""
    try:
        os.makedirs(RAPOR_DIR, exist_ok=True)
        yol = os.path.join(RAPOR_DIR, dosya_adi(state, pist_adi))
        with open(yol, "w", encoding="utf-8") as f:
            f.write(rapor_html(state, pist_adi, adi))
        return yol
    except OSError:
        return None
