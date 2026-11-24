# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Fren noktası geri sayımı (3 bip)
Virajdan önce 3 kez "bip" çalar; 3. bip frene basman gereken andır.
Fren noktası: temiz turların arasında o virajı EN HIZLI geçtiğin turdaki fren başlangıcı.
Ses için Windows'un kendi "winsound" modülü kullanılır (ek paket gerekmez).
"""
import io
import math
import queue
import struct
import sys
import threading
import time
import wave

from gt7_kalibrasyon import BEEP_GAP, BRAKE_ON, DEFAULT_DELAY, clamp, median
from gt7_kopru import (LapTrace, measure, place_corners, section_bounds,
                       section_time, to_samples)

# Tepki payı (ses gecikmesi + tepki + pedal) ve bip aralığı gt7_kalibrasyon.py'den gelir
ADJUST_RATE = 0.4     # tur sonunda ölçülen hatanın ne kadarı düzeltilir
MAX_ERR_S = 0.6       # bundan büyük sapma "bilerek farklı frenledi" sayılır, ölçüme girmez
MIN_SPEED_KMH = 60    # bundan yavaşken bip çalmaz (pit, kalkış)
TRACK_LOST_M = 25     # konum referans çizgisinden bu kadar uzaksa (pist dışı) bip yok
BEEPS = ((700, 110), (700, 110), (1050, 220))  # (frekans Hz, süre ms): 3. bip ince ve uzun
VOLUME = 0.35         # yumuşak ses seviyesi (0-1)
# Discord (gt7_discord): bipler PS5 kulaklığına da gider; sadece Discord seçiliyse bilgisayarda çalmaz
EK_CALICI = None      # fn(k): her bipte çağrılır
YEREL = True          # bilgisayarın hoparlöründen de çalsın mı
TONES = BEEPS
# Hıza göre fren noktası: bipler yaklaşma hızını da hesaba katar. Viraja referans turdan hızlı geliyorsan fren mesafen uzar, son bip erken çalar;
# yavaş geliyorsan geç. Fren mesafesi farkı = (v² - v_ref²) / (2 × yavaşlama); yavaşlama referans turun
# o fren bölgesinden ölçülür. İlk bipten sonra nokta sabitlenir (bipler arası kaymasın).
YAVASLAMA_VARSAYILAN = 12.0   # m/s² (~1,2 G), ölçülemezse
YAVASLAMA_ARALIK = (6.0, 20.0)
YAVASLAMA_OLCU_M = 40.0       # fren başlangıcından bu kadar metrede ölçülür
KAYMA_EN_COK_M = 40.0         # fren noktası en fazla bu kadar öne / geri kayar
# Rekor turu referansken fren noktası (load cell pedalı olmadan rekorun fren noktasında etkili
# frenlemek zor, araba yoldan taşabilir):
# - Güvenlik payı (ayar fren_payi): fren noktası rekorunkinden bu kadar metre önce.
# - "Benim fren gücüme göre" (ayar fren_noktasi = benim): kendi temiz turlarında her virajda fren başından
#   en yavaş noktaya ortalama ne kadar yavaşlayabildiğin ölçülür (turların arasında en güçlüsü).
#   Rekor sürücüsü aynı hız farkını daha kısa mesafede eritiyorsa aradaki mesafe kadar fren noktası öne alınır (sadece öne, en fazla KENDI_EN_COK_M).
FREN_PAYI_M = {"yok": 0, "az": 10, "orta": 20, "cok": 30}
KENDI_EN_COK_M = 60.0
KENDI_MIN_FREN_M = 15.0       # fren bölgesi bundan kısaysa (hafif dokunuş) ölçülmez
# Ekrandaki 3. ışık (FREN!): 3. bipten sonra en az bu kadar yanık kalır. Fren noktası 3. bipten
# "tepki payı" kadar sonra geçilir; pay küçükken (kalibrasyonsuz 0,15 sn) ışık ekranda görünmüyordu.
UCUNCU_GOSTER_S = 0.8


# ---------------- Ses ----------------
def soft_wav(freq, ms, rate=22050):
    """Yumuşak bip: sinüs dalgası, yavaş başlangıç ve sönümlenen bitiş (bellekte WAV)."""
    n = int(rate * ms / 1000)
    attack = max(1, int(rate * 0.010))
    frames = bytearray()
    for i in range(n):
        env = min(1.0, i / attack) * (1 - i / n) ** 1.5
        v = int(32767 * VOLUME * env * math.sin(2 * math.pi * freq * i / rate))
        frames += struct.pack("<h", v)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return buf.getvalue()


class Beeper:
    """Sesleri arka planda sırayla çalar, ana döngüyü bekletmez."""

    def __init__(self):
        self.q = queue.Queue()
        self.sounds = [soft_wav(f, ms) for f, ms in TONES]
        try:
            import winsound

            def play(k):
                try:
                    winsound.PlaySound(self.sounds[k], winsound.SND_MEMORY)
                except Exception:  # ses kartı WAV çalamazsa eski bipe dön
                    winsound.Beep(*TONES[k])
            self.play = play
        except ImportError:  # Windows dışı: terminal zili
            self.play = lambda k: (sys.stdout.write("\a"), sys.stdout.flush())
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            k = self.q.get()
            try:
                self.play(k)
            except Exception:
                pass

    def beep(self, k):
        if EK_CALICI:
            try:
                EK_CALICI(k)
            except Exception:
                pass
        if YEREL:
            self.q.put(k)

    def test(self):
        """Deneme: gerçek aralıkla 3 bip (ana döngüyü bekletmez)."""
        def run():
            import time
            for k in range(3):
                self.beep(k)
                time.sleep(BEEP_GAP)
        threading.Thread(target=run, daemon=True).start()


# ---------------- Fren noktaları ----------------
def _interp(xs, ys, x):
    if x <= xs[0]:
        return ys[0]
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    t = (x - xs[lo]) / ((xs[hi] - xs[lo]) or 1)
    return ys[lo] + t * (ys[hi] - ys[lo])


def _ortalama_yavaslama(s, m):
    """Fren başından virajın en yavaş noktasına ortalama yavaşlama (m/s²) ve mesafe (m), ya da None."""
    if not m or m.brake_on is None or m.min_speed_dist is None:
        return None
    mesafe = m.min_speed_dist - m.brake_on
    if mesafe < KENDI_MIN_FREN_M:
        return None
    v0 = _interp(s["dist"], s["speed"], m.brake_on) / 3.6
    v1 = _interp(s["dist"], s["speed"], m.min_speed_dist) / 3.6
    if v0 <= v1 + 2:
        return None
    return (v0 * v0 - v1 * v1) / (2 * mesafe), mesafe


def kendi_kaymalari(rekor, kendi_turlar, corners):
    """Rekor turuna göre fren noktası, kendi fren gücüne göre kaç metre öne alınmalı: {viraj no: m}.
    Her virajda kendi turlarındaki en güçlü yavaşlama kullanılır (erken ve hafif frenleme alışkanlığı fren
    noktasını daha da öne çekmesin); rekor kadar ya da daha güçlü frenliyorsan 0."""
    def olc(L):
        s = to_samples(L)
        wins = place_corners(corners, s)
        return s, measure(LapTrace(s), wins)
    s_r, m_r = olc(rekor)
    kendi = [olc(L) for L in kendi_turlar]
    out = {}
    for c in corners:
        no = c["no"]
        r = _ortalama_yavaslama(s_r, m_r.get(no))
        if not r:
            continue
        a_ref, d_ref = r
        olcumler = sorted(x[0] for x in (_ortalama_yavaslama(s, m.get(no)) for s, m in kendi) if x)
        if not olcumler:
            continue
        a_ben = olcumler[-1]     # o virajda gösterdiğin EN güçlü frenleme (alışkanlık değil, kapasite)
        if a_ben >= a_ref:
            continue
        out[no] = round(min(KENDI_EN_COK_M, d_ref * (a_ref / a_ben - 1)), 1)
    return out


def brake_points(pool, corners, kayma=None):
    """Her viraj için en iyi geçişindeki fren başlangıcının pistteki konumu (x, z).
    kayma: {viraj no: m}: fren noktası bu kadar metre öne alınır (güvenlik payı / kendi fren gücü)."""
    per_lap = []
    for L in pool:
        s = to_samples(L)
        wins = place_corners(corners, s)
        per_lap.append((s, wins, section_bounds(wins, s["dist"][-1]),
                        measure(LapTrace(s), wins)))
    out = []
    for i, c in enumerate(corners):
        best = None
        for s, wins, bounds, ms in per_lap:
            if i >= len(wins):
                continue
            n = wins[i].n
            a, b = bounds[i]
            tm = section_time(s, a, b)
            if best is None or tm < best[0]:
                best = (tm, s, ms.get(n), n)
        if not best or not best[2] or best[2].brake_on is None:
            continue  # bu viraj frensiz (gaz kesmeden) geçiliyor
        _, s, m, n = best
        bas = m.brake_on - (kayma or {}).get(n, 0.0)
        v0 = _interp(s["dist"], s["speed"], m.brake_on) / 3.6
        v1 = _interp(s["dist"], s["speed"], m.brake_on + YAVASLAMA_OLCU_M) / 3.6
        dec = (v0 * v0 - v1 * v1) / (2 * YAVASLAMA_OLCU_M) if v0 > v1 else YAVASLAMA_VARSAYILAN
        out.append({"no": n, "x": _interp(s["dist"], s["x"], bas),
                    "z": _interp(s["dist"], s["z"], bas),
                    "speed": m.brake_on_speed,
                    "yavaslama": min(max(dec, YAVASLAMA_ARALIK[0]), YAVASLAMA_ARALIK[1])})
    return out


# ---------------- Canlı geri sayım ----------------
class BrakeCountdown:
    """Pistteki konumu referans turun çizgisine oturtur, fren noktasına kalan
    süreyi hesaplar ve zamanı gelince bipleri çalar."""

    def __init__(self, base_lap, points, beeper, delay=DEFAULT_DELAY):
        step = 2  # ~her 1-2 metrede bir nokta yeterli
        self.x = base_lap["x"][::step]
        self.z = base_lap["z"][::step]
        self.d = base_lap["dist"][::step]
        self.v = (base_lap.get("speed") or [])[::step]   # referans turun hızı (km/s), yaklaşma hızı karşılaştırması
        self.length = base_lap["dist"][-1]
        self.idx = None
        self.beeper = beeper
        self.delay = delay        # tepki payı (saniye): bipler bu kadar erken çalar
        self.errs = []            # bu turdaki fren zamanlama hataları (+ geç, - erken)
        self.prev_brake = 0
        self.points = []
        for p in points:
            k, gap = self._nearest(p["x"], p["z"], range(len(self.x)))
            if gap < TRACK_LOST_M:
                self.points.append({"no": p["no"], "d": self.d[k], "done": 0,
                                    "speed": p["speed"], "armed": False, "kayma": 0.0,
                                    "yavaslama": p.get("yavaslama") or YAVASLAMA_VARSAYILAN})
        self.points.sort(key=lambda p: p["d"])

    def _nearest(self, x, z, idxs):
        best, bk = float("inf"), 0
        for i in idxs:
            g = (self.x[i] - x) ** 2 + (self.z[i] - z) ** 2
            if g < best:
                best, bk = g, i
        return bk, math.sqrt(best)

    def _locate(self, x, z):
        n = len(self.x)
        if self.idx is not None:
            k, gap = self._nearest(x, z, (i % n for i in range(self.idx - 10, self.idx + 80)))
            if gap < TRACK_LOST_M:
                self.idx = k
                return self.d[k]
        k, gap = self._nearest(x, z, range(n))
        self.idx = k if gap < TRACK_LOST_M else None
        return self.d[k] if self.idx is not None else None

    def kayma(self, p, speed_kmh):
        """Fren noktası kaç metre öne alınmalı (+ öne / erken, - geriye / geç): şu anki hızın referans
        turun aynı yerdeki hızına oranı, referansın fren noktasındaki hızına uygulanır."""
        if not self.v or self.idx is None or not p.get("speed"):
            return 0.0
        v_ref_burada = self.v[self.idx]
        if not v_ref_burada or v_ref_burada < MIN_SPEED_KMH:
            return 0.0
        v_ref = p["speed"] / 3.6
        v_tahmin = v_ref * speed_kmh / v_ref_burada
        m = (v_tahmin * v_tahmin - v_ref * v_ref) / (2 * p["yavaslama"])
        return max(-KAYMA_EN_COK_M, min(KAYMA_EN_COK_M, m))

    def update(self, x, z, speed_kmh, brake_pct):
        """Her pakette çağrılır. Fren noktasına kalan süreye göre bip çalar ve
        bipten sonra frene basılan yeri ölçer (kalibrasyon için)."""
        pressed = brake_pct >= BRAKE_ON and self.prev_brake < BRAKE_ON
        self.prev_brake = brake_pct
        cur = self._locate(x, z)
        if cur is None or speed_kmh < MIN_SPEED_KMH:
            return
        v = speed_kmh / 3.6
        half = self.length / 2
        simdi = time.monotonic()
        # Arayüz için: geri sayımı süren viraj ve çalan bip sayısı. Az önce 3. bipi çalan viraj bir süre gösterilir.
        self.bip_durum = None
        for p in self.points:
            if p.get("t3") is not None and simdi - p["t3"] < UCUNCU_GOSTER_S:
                self.bip_durum = {"no": p["no"], "bip": 3}
                break
        for p in self.points:
            if p["done"] == 0 and not p["armed"]:
                p["kayma"] = self.kayma(p, speed_kmh)   # ilk bipe kadar güncellenir, sonra sabit
            d_fren = p["d"] - p["kayma"]
            if p["armed"]:
                past = (cur - d_fren + half) % self.length - half  # + ise noktayı geçtik (m)
                if pressed:
                    err = past / v
                    if abs(err) <= MAX_ERR_S:
                        self.errs.append(err)
                    p["armed"] = False
                elif past / v > MAX_ERR_S:
                    p["armed"] = False  # bu virajda frene basılmadı / çok geç
            rem = (d_fren - cur) % self.length  # başlangıç çizgisini geçen virajlar için
            t_left = rem / v - self.delay
            if t_left > 2 * BEEP_GAP + 1.0:
                if not p["armed"]:
                    p["done"] = 0  # henüz uzak (ya da yeni geçildi): bir sonraki geçiş için hazırla
                continue
            if p["done"] == 0 and t_left < 2 * BEEP_GAP - 0.2:
                p["done"] = 3  # geç fark edildi (ör. pitten çıkış): yarım geri sayım çalma
            while p["done"] < 3 and t_left <= (2 - p["done"]) * BEEP_GAP:
                self.beeper.beep(p["done"])
                p["done"] += 1
                if p["done"] == 1:
                    p["armed"] = True  # ilk bipten itibaren frene basış izlenir
                elif p["done"] == 3:
                    p["t3"] = simdi
            if rem < half and self.bip_durum is None:
                self.bip_durum = {"no": p["no"], "bip": p["done"]}

    def lap_summary(self):
        """Tur sonunda: ortalama zamanlama hatasına göre tepki payını yavaşça düzeltir.
        Döndürür: (ölçüm sayısı, ortanca hata sn) ya da None."""
        errs, self.errs = self.errs, []
        if len(errs) < 3:
            return None
        e = median(errs)
        self.delay = clamp(self.delay + ADJUST_RATE * e)
        return len(errs), e
