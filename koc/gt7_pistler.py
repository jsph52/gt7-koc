# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Pist kütüphanesi
- pistler/ klasöründeki hazır veriyi okur (kaynak: jbhoorasingh/gt7-datalogger-track-data)
- Pist arama (arayüzdeki seçim penceresi için)
- Hazır viraj yoksa virajları pist çizgisinden hesaplar
"""
import json
import math
import os
import unicodedata

from gt7_yol import DATA_DIR as _DATA, USER_DIR

DATA_DIR = os.path.join(_DATA, "pistler")
LAST_FILE = os.path.join(USER_DIR, "son_pist.txt")

FAR_LIMIT = 100      # pist çizgisine bundan uzaksa (m) pistin dışında sayılır
CLOSED_GAP = 350     # çizginin iki ucu bundan yakınsa (m) pist kapalı devre sayılır
CORNER_ANGLE = 15    # bu dereceden fazla yön değişimi viraj sayılır
CORNER_REACH = 5     # açı ölçümünde iki yana bakılan nokta sayısı (nokta aralığı 20 m)
CORNER_WINDOW = 5    # bu kadar nokta içindeki en keskin yer tek viraj sayılır


# ---------------- Veri okuma ----------------
def load_json(*parts):
    with open(os.path.join(DATA_DIR, *parts), encoding="utf-8") as f:
        return json.load(f)


def load_catalog():
    """Tüm pistler: ad, uzunluk, resmi viraj sayısı, varsa çizgi ve hazır virajlar."""
    paths = {}
    for s in load_json("signatures.json")["signatures"]:
        if s.get("path"):
            paths[s["official_id"]] = s["path"]
            if s.get("reverse"):
                paths[s["reverse"]["official_id"]] = s["path"][::-1]
    # Ana kaynakta çizgisi olmayan düzenler (gt-telemetry kayıtlarından).
    # Kısmi kayıtların sonu eksik: virajlar için kullanılır, pist kontrolü için kullanılmaz.
    partial, partial_paths = {}, {}
    for i, t in load_json("ek_cizgiler.json")["tracks"].items():
        if t["partial"]:
            partial[i] = corners_from_path(t["path"], closed=False)
            partial_paths[i] = t["path"]
        else:
            paths.setdefault(i, t["path"])

    apexes = {}
    folder = os.path.join(DATA_DIR, "tracks")
    for fn in os.listdir(folder):
        b = load_json("tracks", fn)
        apexes[b["meta"]["official"]["official_id"]] = [
            [c["apex"]["x"], c["apex"]["z"]] for c in b["corners"] if c.get("apex")]

    out = []
    for c in load_json("index.json")["configurations"]:
        i = c["official_id"]
        path = paths.get(i)
        out.append({"id": i, "name": c["official_name"], "length": c["length_m"],
                    "turns": c["turns"], "path": path,
                    "corner_xy": apexes.get(i) or partial.get(i)
                    or (corners_from_path(path) if path else []),
                    "partial": i in partial,
                    # Pist şekli (özet ve viraj uyarısı için); kısmi pistte sonu eksik çizgi
                    "shape": path or partial_paths.get(i)})
    return out


# ---------------- Geometri ----------------
def corners_from_path(path, closed=None):
    """Pist çizgisinde yönün belirgin değiştiği noktaları viraj olarak bulur."""
    n = len(path)
    r = CORNER_REACH
    if n < 2 * r + 1:
        return []
    if closed is None:
        closed = math.hypot(path[0][0] - path[-1][0], path[0][1] - path[-1][1]) < CLOSED_GAP

    def pt(i):
        return path[i % n]

    angles = []
    for i in range(n):
        if not closed and (i < r or i >= n - r):
            angles.append(0.0)
            continue
        a, b, c = pt(i - r), pt(i), pt(i + r)
        h1 = math.atan2(b[1] - a[1], b[0] - a[0])
        h2 = math.atan2(c[1] - b[1], c[0] - b[0])
        d = abs(h2 - h1)
        angles.append(math.degrees(min(d, 2 * math.pi - d)))

    # Çevresindeki en keskin nokta olan yerler viraj sayılır
    w = CORNER_WINDOW
    picked = []
    for i in range(n):
        if angles[i] < CORNER_ANGLE:
            continue
        if angles[i] < max(angles[(i + k) % n] for k in range(-w, w + 1)):
            continue
        if picked and i - picked[-1] <= w:
            continue
        picked.append(i)
    return [list(path[i]) for i in picked]


def distance_to_path(path, x, z):
    return min(math.hypot(p[0] - x, p[1] - z) for p in path)


def lap_on_path(path, lap):
    """Turun en az %90'ı seçilen pistin üzerinde mi?"""
    xs, zs = lap["x"], lap["z"]
    idx = range(0, len(xs), max(1, len(xs) // 200))
    near = sum(distance_to_path(path, xs[i], zs[i]) <= FAR_LIMIT for i in idx)
    return near >= 0.9 * len(idx)


def corners_for_lap(corner_xy, lap):
    """Viraj konumlarını turun üzerindeki en yakın noktaya eşler (koçun viraj biçimi)."""
    total = lap["dist"][-1]
    n = len(lap["x"])
    fr = []
    for x, z in corner_xy:
        k = min(range(0, n, 3), key=lambda i: (lap["x"][i] - x) ** 2 + (lap["z"][i] - z) ** 2)
        fr.append((lap["dist"][k] / total, lap["x"][k], lap["z"][k]))
    fr.sort()
    return [{"no": no, "frac": f, "x": x, "z": z} for no, (f, x, z) in enumerate(fr, 1)]


# ---------------- Arama ve menü ----------------
def normalize(text):
    text = text.replace("ı", "i").replace("İ", "i").lower()
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def search(catalog, query):
    words = normalize(query).split()
    return [t for t in catalog if all(w in normalize(t["name"]) for w in words)]


def read_last(catalog):
    try:
        with open(LAST_FILE, encoding="utf-8") as f:
            last = f.read().strip()
    except OSError:
        return None
    return next((t for t in catalog if t["id"] == last), None)


def write_last(track):
    with open(LAST_FILE, "w", encoding="utf-8") as f:
        f.write(track["id"])


def describe(t):
    if not t["corner_xy"]:
        return (f"{t['name']}, {t['length']} m, {t['turns']} viraj. Bu pistin viraj haritası yok: "
                "virajları senin turlarından öğreneceğim.")
    if t["partial"]:
        return (f"{t['name']}, {t['length']} m. Haritada {len(t['corner_xy'])} viraj noktası hazır, "
                "ama kaydın sonu eksik: son virajlar görünmeyebilir, yanlış pist uyarısı çalışmaz.")
    return f"{t['name']}, {t['length']} m. Haritada {len(t['corner_xy'])} viraj noktası hazır."
