# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Yarış öncesi pist özeti ve viraj uyarıları
- Pist çizgisinden virajların yönünü, keskinliğini ve kaba hız tahminini çıkarır
- Pist seçilince kısa Türkçe özet yazar
- Sürerken viraja yaklaşınca tek satırlık uyarı verir; kendi temiz turların varsa
  tahmin yerine o virajdaki kendi en iyi geçişini söyler
Tahminler arabayı bilmez: ortalama bir yol/spor arabası tutuşu varsayılır.
"""
import math

from gt7_veri import araba_adi, pist_bilgi_satiri

ROUTE_STEP = 20       # şekil hesabı için çizgi bu aralıkla (m) yeniden örneklenir
LAT_ACC = 11.5        # m/s², viraj tutuşu (~1,2 g; Tokyo kayıtlarıyla kabaca ayarlandı)
BRAKE_ACC = 11.0      # m/s², fren yavaşlaması (~1,1 g)
MAX_EST_KMH = 250     # bundan hızlı tahmin "neredeyse tam gaz" sayılır
NO_BRAKE_KMH = 10     # yaklaşma hızı tahminden bu kadar fazla değilse fren gerekmeyebilir
STRAIGHT_DEG = 8      # 40 m'de bundan az yön değişimi düzlük sayılır
STRAIGHT_MIN = 400    # özette gösterilen en kısa düzlük (m)
WARN_SEC = 4.0        # viraja bu kadar saniye kala uyar
WARN_MIN_M = 150      # ... ama en az bu kadar
WARN_MAX_M = 450      # ... en fazla bu kadar metre önce
REWARN_SEC = 25       # aynı viraj bundan kısa sürede tekrar söylenmez (başlangıç çizgisi)
OFF_ROUTE_M = 100     # çizgiye bundan uzaksa (pit, başka pist) uyarı verilmez
LOCAL_SEARCH = 8      # konum ararken son noktanın iki yanına bakılan nokta sayısı


# ---------------- Geometri ----------------
def resample(pts, step=ROUTE_STEP):
    """Çizgiyi eşit aralıklı noktalara çevirir."""
    out = [tuple(pts[0])]
    left = step
    for a, b in zip(pts, pts[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        pos = 0.0
        while seg - pos >= left:
            pos += left
            t = pos / seg
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            left = step
        left -= seg - pos
    return out


def circle_radius(a, b, c):
    ab, bc, ca = math.dist(a, b), math.dist(b, c), math.dist(c, a)
    cross = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
    return 1e9 if cross < 1e-6 else ab * bc * ca / (2 * cross)


def turn_shape(pts, i, closed):
    """Virajın yönü, toplam açısı (°) ve en dar yarıçapı (m)."""
    n = len(pts)

    def pt(k):
        return pts[k % n] if closed else pts[max(0, min(n - 1, k))]

    total = 0.0
    for k in range(i - 5, i + 5):
        a, b, c = pt(k - 1), pt(k), pt(k + 1)
        if a == b or b == c:
            continue
        h1 = math.atan2(b[1] - a[1], b[0] - a[0])
        h2 = math.atan2(c[1] - b[1], c[0] - b[0])
        total += (h2 - h1 + math.pi) % (2 * math.pi) - math.pi
    radius = min(circle_radius(pt(k - 2), pt(k), pt(k + 2)) for k in range(i - 2, i + 3))
    # GT7 koordinatlarında (x, z) bu yönde dönüş, yukarıdan bakınca sağa dönüştür
    return {"dir": "sağ" if total > 0 else "sol", "angle": abs(math.degrees(total)),
            "radius": radius}


def severity(c):
    r = c["radius"]
    if r < 45 or (r < 80 and c["angle"] > 150):
        return "firkete"
    if r < 100:
        return "sert"
    if r < 180:
        return "orta"
    return "hafif"


def corner_speed(radius):
    """Kaba viraj hızı (km/s): v = kök(tutuş x yarıçap)."""
    return min(MAX_EST_KMH, math.sqrt(LAT_ACC * radius) * 3.6)


def brake_distance(v_kmh, corner_kmh):
    """Bu hızdan viraj hızına inmek için gereken kaba mesafe (m)."""
    v, c = v_kmh / 3.6, corner_kmh / 3.6
    return max(0.0, (v * v - c * c) / (2 * BRAKE_ACC))


def is_closed(pts):
    return math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 350


# ---------------- Çizgi üzerinde konum ----------------
class Route:
    def __init__(self, pts, closed=None):
        self.pts = resample(pts)
        self.closed = is_closed(pts) if closed is None else closed
        self.cum = [0.0]
        for a, b in zip(self.pts, self.pts[1:]):
            self.cum.append(self.cum[-1] + math.dist(a, b))
        self.length = self.cum[-1] + (math.dist(self.pts[-1], self.pts[0]) if self.closed else 0)
        self.hint = None

    def _seg(self, k, x, z):
        """k. parçaya izdüşüm: (uzaklık², çizgi üzerindeki mesafe)."""
        n = len(self.pts)
        a = self.pts[k]
        if k + 1 < n:
            b, end = self.pts[k + 1], self.cum[k + 1]
        elif self.closed:
            b, end = self.pts[0], self.length
        else:
            return (a[0] - x) ** 2 + (a[1] - z) ** 2, self.cum[k]
        dx, dz = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dz * dz or 1e-9
        t = max(0.0, min(1.0, ((x - a[0]) * dx + (z - a[1]) * dz) / L2))
        px, pz = a[0] + dx * t, a[1] + dz * t
        return (px - x) ** 2 + (pz - z) ** 2, self.cum[k] + t * (end - self.cum[k])

    def locate(self, x, z, track=True):
        """(çizgideki mesafe, çizgiye uzaklık). Hızlı olsun diye önce son konumun yakınına bakar."""
        n = len(self.pts)
        best = None
        if track and self.hint is not None:
            ks = [(self.hint + d) % n for d in range(-LOCAL_SEARCH, LOCAL_SEARCH + 1)]
            best = min((self._seg(k, x, z) + (k,) for k in ks))
            if best[0] > 60 ** 2:
                best = None
        if best is None:
            best = min(self._seg(k, x, z) + (k,) for k in range(n))
        if track:
            self.hint = best[2]
        return best[1], math.sqrt(best[0])

    def index_at(self, s):
        return min(range(len(self.pts)), key=lambda k: abs(self.cum[k] - s))


def build_corners(route, corner_xy):
    """Viraj noktalarını çizgiye oturtur, sürüş sırasına göre numaralar ve şeklini ölçer."""
    out = []
    for x, z in corner_xy:
        s, off = route.locate(x, z, track=False)
        if off > OFF_ROUTE_M:
            continue
        c = turn_shape(route.pts, route.index_at(s), route.closed)
        c.update({"s": s, "x": x, "z": z})
        c["est"] = corner_speed(c["radius"])
        c["kind"] = severity(c)
        out.append(c)
    out.sort(key=lambda c: c["s"])
    for no, c in enumerate(out, 1):
        c["no"] = no
    return out


def longest_straight(route, corners):
    """En uzun düz bölüm: (uzunluk m, önceki viraj no, sonraki viraj no)."""
    n = len(route.pts)
    flat = []
    for i in range(n):
        if not route.closed and (i < 2 or i >= n - 2):
            flat.append(False)
            continue
        a, b, c = route.pts[(i - 2) % n], route.pts[i], route.pts[(i + 2) % n]
        h1 = math.atan2(b[1] - a[1], b[0] - a[0])
        h2 = math.atan2(c[1] - b[1], c[0] - b[0])
        d = abs((h2 - h1 + math.pi) % (2 * math.pi) - math.pi)
        flat.append(math.degrees(d) < STRAIGHT_DEG)
    if all(flat):
        return None
    # Kapalı pistte başlangıç çizgisinden geçen düzlük de bütün sayılsın
    start = next(i for i in range(n) if not flat[i]) if route.closed else 0
    best_run, best_start, run, run_start = 0, 0, 0, 0
    for j in range(n):
        i = (start + j) % n
        if flat[i]:
            if run == 0:
                run_start = i
            run += 1
            if run > best_run:
                best_run, best_start = run, run_start
        else:
            run = 0
    if best_run == 0:
        return None
    s0 = route.cum[best_start]
    s1 = s0 + best_run * ROUTE_STEP

    def gap(a, b):
        return (b - a) % route.length if route.closed else b - a

    behind = [c for c in corners if gap(c["s"], s0) >= 0]
    front = [c for c in corners if gap(s1, c["s"]) >= 0]
    before = min(behind, key=lambda c: gap(c["s"], s0))["no"] if behind else None
    after = min(front, key=lambda c: gap(s1, c["s"]))["no"] if front else None
    return best_run * ROUTE_STEP, before, after


# ---------------- Yarış öncesi özet ----------------
def corner_name(c):
    return f"Viraj {c['no']} ({c['kind']} {c['dir']}, ~{c['est']:.0f} km/s)"


def track_summary(sel, tr=None):
    """Pist seçildikten sonra ekrana yazılacak satırlar."""
    if not sel:
        return ["Pist seçilmedi: özet yok. Virajları senin turlarından öğreneceğim,",
                "ilk temiz turundan sonra virajlara yaklaşırken uyarı vereceğim."]
    lines = [f"PİST ÖZETİ — {sel['name']} ({sel['length'] / 1000:.2f} km)"]
    bilgi = pist_bilgi_satiri(sel.get("id"))
    if bilgi:
        lines.append(bilgi)
    shape = sel.get("shape")
    corners = []
    route = None
    if shape and len(shape) > 5:
        route = Route(shape, closed=False if sel["partial"] else None)
        corners = build_corners(route, sel["corner_xy"])
    if corners:
        sag = sum(c["dir"] == "sağ" for c in corners)
        lines.append(f"  {len(corners)} viraj: {sag} sağ, {len(corners) - sag} sol"
                     f" (resmi sayı {sel['turns']}; çok hafif kıvrımlar sayılmaz).")
        sharp = sorted(corners, key=lambda c: c["radius"])[:3]
        lines.append("  En keskin virajlar: " + ", ".join(corner_name(c) for c in sharp) + ".")
    elif route and not sel["corner_xy"]:
        lines.append("  Pist çizgisinde belirgin viraj yok (uzun düzlükler ve hafif kıvrımlar): "
                     "viraj uyarısı verilmeyecek.")
    elif sel["corner_xy"]:
        lines.append(f"  Haritada {len(sel['corner_xy'])} viraj noktası var ama pist çizgisi yok: "
                     "yön ve keskinlik hesaplanamadı.")
    else:
        lines.append("  Bu pistin viraj haritası yok: virajları senin turlarından öğreneceğim.")
    if route:
        st = longest_straight(route, corners)
        if st and st[0] >= STRAIGHT_MIN:
            where = ""
            if st[1] and st[2] and st[1] != st[2]:
                where = f" (Viraj {st[1]} ile Viraj {st[2]} arası)"
            elif st[2]:
                where = f" (Viraj {st[2]} öncesi)"
            lines.append(f"  En uzun düzlük (hafif kıvrımlar dahil): ~{st[0] / 1000:.1f} km{where}.")
    if sel["partial"]:
        eksik = sel["length"] - route.length if route else 0
        lines.append("  Dikkat: bu pistin kaydının sonu eksik"
                     + (f" (son ~{eksik / 1000:.1f} km)" if eksik > 100 else "")
                     + ": oradaki virajlar özette yok ve uyarı verilmez.")
    best = best_times(tr)
    if best:
        lines.append("  Senin en iyi turun: " + ", ".join(f"{t} ({araba_adi(car)})" for car, t in best) + ".")
    else:
        lines.append("  Bu pistte henüz kayıtlı temiz turun yok.")
    if corners:
        lines.append("  Hızlar KABA TAHMİNDİR: virajın şeklinden hesaplandı, arabaya ve ayara göre değişir.")
    return lines


def best_times(tr):
    from gt7_paket import sure
    if not tr:
        return []
    out = []
    for car, laps in (tr.get("laps") or {}).items():
        ms = [L["lap_ms"] for L in laps if L.get("lap_ms")]
        if ms:
            out.append((min(ms), car))
    return [(car, sure(ms)) for ms, car in sorted(out)][:3]


# ---------------- Sürerken viraj uyarısı ----------------
class Warner:
    """Viraja yaklaşınca tek satırlık uyarı üretir. Her pakette çağrılır, hafif çalışır."""

    def __init__(self, route, corners, source):
        self.route = route
        self.corners = corners
        self.source = source      # "tahmin" veya "kendi"
        self.warned = {}          # viraj no -> (tur no, zaman)

    def update(self, x, z, speed, lap_no, now):
        s, off = self.route.locate(x, z)
        if off > OFF_ROUTE_M:
            return []
        reach = max(WARN_MIN_M, min(WARN_MAX_M, speed / 3.6 * WARN_SEC))
        out = []
        for c in self.corners:
            ahead = c["s"] - s
            if self.route.closed:
                ahead %= self.route.length
            if not 0 <= ahead <= reach:
                continue
            last = self.warned.get(c["no"])
            if last and (last[0] == lap_no or now - last[1] < REWARN_SEC):
                continue
            self.warned[c["no"]] = (lap_no, now)
            out.append((ahead, self.message(c, speed)))
        return [m for _, m in sorted(out)]

    def message(self, c, speed):
        head = f"Viraj {c['no']} yaklaşıyor: {c['kind']} {c['dir']}"
        own = c.get("own")
        if own and own.get("min") is not None:
            txt = f"{head}, en iyi geçişin {own['min']:.0f} km/s"
            if own.get("brake_m"):
                txt += f", fren ~{own['brake_m']:.0f} m önce"
            if own.get("gear"):
                txt += f", {own['gear']}. vites"
            return txt
        txt = f"{head}, kaba tahmin {c['est']:.0f} km/s"
        if c["est"] >= MAX_EST_KMH or speed < c["est"] + NO_BRAKE_KMH:
            return txt + " (fren gerekmeyebilir)"
        return txt + f", fren ~{round(brake_distance(speed, c['est']), -1):.0f} m önce"


def library_warner(sel):
    """Pist kütüphanesinden: referans turu yokken kaba tahminle uyarır."""
    if not sel or not sel.get("shape") or not sel["corner_xy"] or len(sel["shape"]) <= 5:
        return None
    route = Route(sel["shape"], closed=False if sel["partial"] else None)
    corners = build_corners(route, sel["corner_xy"])
    return Warner(route, corners, "tahmin") if corners else None


def own_warner(best_lap, corners, bests):
    """Kendi turlarından: çizgi en iyi turundan, değerler her virajdaki en iyi geçişinden."""
    pts = list(zip(best_lap["x"], best_lap["z"]))
    if len(pts) < 50 or not corners:
        return None
    route = Route(pts)
    out = build_corners(route, [(c["x"], c["z"]) for c in corners])
    # Numaralar tur sonu analiziyle aynı olsun
    for c in out:
        src = min(corners, key=lambda k: (k["x"] - c["x"]) ** 2 + (k["z"] - c["z"]) ** 2)
        c["no"] = src["no"]
        c["own"] = bests.get(src["no"])
    return Warner(route, out, "kendi")
