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
import json
import math
import os
from collections import deque

from gt7_yol import USER_DIR

G = 9.80665
LASTIK_SOGUK = 60     # çalışma sıcaklığı henüz bilinmiyorsa genel aralık: °C altı soğuk (mavi)
LASTIK_IDEAL = (70, 95)  # ideal (yeşil)
LASTIK_SICAK = 100    # °C üstü çok sıcak (kırmızı), gt7_yorum.LASTIK_SICAK ile aynı
# Arabaya göre çalışma sıcaklığı: lastik ortalaması (40 km/s üstünde, 8 sn yumuşatılmış) 30 sn boyunca
# 1,5 °C'den az değişince o arabanın lastiklerinin oturduğu sıcaklık sayılır. Renkler buna göre (ideal R-8..R+10).
LASTIK_DOSYA = os.path.join(USER_DIR, "lastik.json")
CALISMA_TAU = 8.0
CALISMA_PENCERE_S = 30.0
CALISMA_SABIT = 1.5
CALISMA_EN_AZ = 40.0
CALISMA_OGRENME = 0.2     # her sabitlenmede kayıtlı değere bu oranla yaklaşılır
SOGUK_ALT, IDEAL_ALT, IDEAL_UST, SICAK_UST = 15, 8, 10, 20   # çalışma sıcaklığına göre °C
G_PENCERE_S = 0.25    # G hesabı için bakılan süre
ZEMIN = {"T": "asfalt", "K": "kerb", "G": "çim", "S": "kum", "D": "toprak", "s": "kar", "I": "buz"}


def _calisma_oku():
    try:
        with open(LASTIK_DOSYA, encoding="utf-8") as f:
            d = json.load(f)
        return {str(k): float(v) for k, v in d.items()}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def lastik_durumu(c, ref=None):
    """ref: arabanın çalışma sıcaklığı (bilinmiyorsa genel aralık)."""
    if c is None:
        return "yok"
    if ref:
        if c < ref - SOGUK_ALT:
            return "soguk"
        if c > max(LASTIK_SICAK, ref + SICAK_UST):
            return "sicak"
        if ref - IDEAL_ALT <= c <= ref + IDEAL_UST:
            return "ideal"
        return "ilik" if c < ref else "isindi"
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
        self.calisma = _calisma_oku()   # araba kodu -> lastiklerin oturduğu sıcaklık (°C)
        self.l_araba = None
        self.l_ema = self.l_t = None
        self.l_iz = deque()             # (t, yumuşatılmış ortalama)
        self.l_son_kayit = -1e9

    def lastik_ogren(self, t, araba, ort, kmh):
        """Lastik ortalaması sabitlenince bu arabanın çalışma sıcaklığını öğrenir (araba başına saklanır)."""
        if araba != self.l_araba:
            self.l_araba, self.l_ema, self.l_t = araba, None, None
            self.l_iz.clear()
        if araba is None or not ort or ort <= 0 or kmh < 40:
            self.l_t = None
            return
        if self.l_ema is None:
            self.l_ema, self.l_t = ort, t
            return
        dt = 0.0 if self.l_t is None else max(0.0, min(0.5, t - self.l_t))
        self.l_t = t
        self.l_ema += (ort - self.l_ema) * min(1.0, dt / CALISMA_TAU)
        iz = self.l_iz
        iz.append((t, self.l_ema))
        while iz and t - iz[0][0] > CALISMA_PENCERE_S:
            iz.popleft()
        if t - iz[0][0] < CALISMA_PENCERE_S - 1 or self.l_ema < CALISMA_EN_AZ:
            return
        if max(v for _, v in iz) - min(v for _, v in iz) < CALISMA_SABIT and t - self.l_son_kayit >= CALISMA_PENCERE_S:
            k = str(araba)
            eski = self.calisma.get(k)
            self.calisma[k] = round(self.l_ema if eski is None else eski + (self.l_ema - eski) * CALISMA_OGRENME, 1)
            self.l_son_kayit = t
            try:
                tmp = LASTIK_DOSYA + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.calisma, f)
                os.replace(tmp, LASTIK_DOSYA)
            except OSError:
                pass

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
        lastikler = (pkt.tire_temp_fl, pkt.tire_temp_fr, pkt.tire_temp_rl, pkt.tire_temp_rr)
        if min(lastikler) > 0:
            self.lastik_ogren(t, araba, sum(lastikler) / 4, v_kmh)
        out = {
            "lastik_ref": self.calisma.get(str(araba)) if araba is not None else None,
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
