# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Canlı ek telemetri (arayüz için)
PS5'in gönderdiği ama koçun önceden kullanmadığı veriler:
- Lastik sıcaklıkları (4 teker), motor (su/yağ sıcaklığı, yağ basıncı, turbo)
- G kuvveti: yanal = hız × yön değişimi, ileri-geri = hız değişimi (konumdan hesaplanır;
  oyunun sway/surge alanlarının birimi belgelenmemiş, gt7-datalogger da aynı yolu izliyor)
- Devir ışığı (oyunun devir uyarı aralığı), devir sınırı
- Yerden yükseklik, yarış sırası, hibrit enerji, teker zemini (C biçimi)
Ek paket gerekmez.
"""
import math
from collections import deque

G = 9.80665
LASTIK_SOGUK = 60     # °C altı soğuk (mavi)  — tahmini aralık, lastik türüne göre değişir
LASTIK_IDEAL = (70, 95)  # ideal (yeşil)
LASTIK_SICAK = 100    # °C üstü çok sıcak (kırmızı), gt7_yorum.LASTIK_SICAK ile aynı
G_PENCERE_S = 0.25    # G hesabı için bakılan süre
ZEMIN = {"T": "asfalt", "K": "kerb", "G": "çim", "S": "kum", "D": "toprak", "s": "kar", "I": "buz"}


def lastik_durumu(c):
    if c is None:
        return "yok"
    if c < LASTIK_SOGUK:
        return "soguk"
    if c > LASTIK_SICAK:
        return "sicak"
    if LASTIK_IDEAL[0] <= c <= LASTIK_IDEAL[1]:
        return "ideal"
    return "ilik" if c < LASTIK_IDEAL[0] else "isindi"


class CanliOlcer:
    """Her pakette çağrılır, arayüzün canlı ek bilgilerini hazırlar."""

    def __init__(self):
        self.gecmis = deque()     # (t, x, z, hız m/s)
        self.g_yan = 0.0
        self.g_ileri = 0.0
        self.tepe_turbo = 0.0
        self.tepe_devir = 0.0     # bu arabada görülen en yüksek devir
        self.devir_araba = None

    def update(self, t, x, z, v_kmh, pkt, flags):
        v = v_kmh / 3.6
        h = self.gecmis
        h.append((t, x, z, v))
        while h and t - h[0][0] > G_PENCERE_S:
            h.popleft()
        if len(h) >= 3 and h[-1][0] - h[0][0] > 0.05:
            a, b, c = h[0], h[len(h) // 2], h[-1]
            dt = c[0] - a[0]
            yon1 = math.atan2(b[2] - a[2], b[1] - a[1])
            yon2 = math.atan2(c[2] - b[2], c[1] - b[1])
            dyon = (yon2 - yon1 + math.pi) % (2 * math.pi) - math.pi
            yan = v * dyon / (dt / 2) / G if v > 8 and math.hypot(c[1] - a[1], c[2] - a[2]) > 2 else 0.0
            ileri = (c[3] - a[3]) / dt / G
            # yumuşat (gürültü), uç değerleri kırp
            self.g_yan = 0.7 * self.g_yan + 0.3 * max(-4.0, min(4.0, yan))
            self.g_ileri = 0.7 * self.g_ileri + 0.3 * max(-4.0, min(4.0, ileri))

        # Devir göstergesi: eskiden sadece oyunun vites
        # uyarı aralığında (devrin en üst ucu) yanıyordu, çoğu zaman sönük kalıyordu. Artık 0 → tavan devir;
        # tavan = oyunun devir uyarı üst sınırı ya da bu arabada görülen en yüksek devir (hangisi büyükse).
        lo, hi = pkt.rpm_alert_min, pkt.rpm_alert_max
        rpm = max(0.0, pkt.engine_rpm or 0.0)
        araba = getattr(pkt, "car_id", None)
        if araba != self.devir_araba:
            self.devir_araba, self.tepe_devir = araba, 0.0
        if rpm < 25000:                        # bozuk değeri sayma
            self.tepe_devir = max(self.tepe_devir, rpm)
        gecerli = bool(hi and hi > lo > 0 and hi < 25000)
        tavan = max(hi if gecerli else 0.0, self.tepe_devir, 3000.0)
        isik = min(1.0, rpm / tavan)
        uyari = round(lo / tavan, 2) if gecerli else None
        boost = pkt.boost if pkt.boost and pkt.boost > 0.01 else 0.0
        self.tepe_turbo = max(self.tepe_turbo, boost)
        out = {
            "lastik": [round(pkt.tire_temp_fl, 1), round(pkt.tire_temp_fr, 1),
                       round(pkt.tire_temp_rl, 1), round(pkt.tire_temp_rr, 1)],
            "g": [round(self.g_yan, 2), round(self.g_ileri, 2)],
            "devir_isigi": round(isik, 3),
            "devir_uyari": uyari,             # vites uyarısının başladığı yer (göstergede oran)
            "devir": round(rpm),
            "devir_sinir": bool(flags & 0x20),
            "motor": {"su": round(pkt.water_temp), "yag": round(pkt.oil_temp),
                      "yag_basinci": round(pkt.oil_pressure, 1),
                      "turbo": round(boost, 2) if self.tepe_turbo > 0.05 else None},
            "yukseklik_mm": round(pkt.body_height * 1000) if pkt.body_height else None,
            "sira": [pkt.race_position, pkt.total_positions]
            if pkt.total_laps > 0 and pkt.total_positions >= 2 and pkt.race_position >= 1 else None,
        }
        if pkt.energy_recovery_available:
            out["hibrit"] = round(pkt.energy_recovery, 2) if pkt.energy_recovery is not None else None
        if pkt.surface_types:
            out["zemin"] = [ZEMIN.get(ch, "?") for ch in pkt.surface_types]
        return out


def vites_sayisi(pkt):
    """Arabanın ileri vites sayısı (şanzıman oranlarından). Bilinmiyorsa None."""
    r = [g for g in (pkt.gear_ratios or ()) if g and g > 0]
    return len(r) or None
