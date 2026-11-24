# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Pit / yakıt stratejisi (yarışta)
Yarışın toplam tur sayısı (telemetri 0x76) ve son turların ortalama tüketiminden:
- yakıt bitişe yetiyor mu, yetmiyorsa kaç pit gerekli,
- pit penceresi (en erken / en geç tur) ve pitte en az kaç litre alınmalı,
- pitsiz bitirmek için tur başına ne kadar az yakmak gerekir.
Lastik aşınması telemetride yok: strateji sadece yakıta göre. Eşikler tahmini, gerçek oyunda denenmedi.
"""
import math

YEDEK_TUR = 0.3        # her stintin sonunda depoda kalsın istenen pay (tur)
TASARRUF_EN_COK = 0.10  # pitsiz bitirmek için bundan az tasarruf gerekiyorsa seçenek olarak söylenir
# Yakıt haritası (yarış içi menü): her kademe tüketimi yaklaşık %10 azaltır, turu ~0,25 sn yavaşlatır (tahmini)
HARITA_TUKETIM = 0.90
HARITA_YAVAS_S = 0.25
HARITA_EN_COK = 4       # en fazla bu kadar kademe önerilir
PIT_VARSAYILAN_S = 25   # pistin pit kaybı bilinmiyorsa


def plan(yakit, kapasite, tur_basi, kalan_tur, simdiki_tur):
    """yakit: tur başındaki depo (L), kapasite: depo (L), tur_basi: ortalama tüketim (L/tur),
    kalan_tur: şimdi başlayan tur dahil bitişe kalan tur, simdiki_tur: şimdi başlayan turun numarası.
    Döner: plan sözlüğü ya da (veri yetersizse) None."""
    if not tur_basi or tur_basi <= 0 or not kalan_tur or kalan_tur <= 0 or yakit is None:
        return None
    menzil = yakit / tur_basi                      # kaç tur gider
    gerek = kalan_tur * tur_basi
    p = {"yakit": yakit, "tur_basi": tur_basi, "kalan_tur": kalan_tur, "menzil": menzil,
         "gerek": gerek, "tur": simdiki_tur, "pit": False}
    if menzil >= kalan_tur:
        p["fazla_tur"] = menzil - kalan_tur
        return p
    p["pit"] = True
    p["tasarruf"] = 1 - yakit / gerek               # pitsiz bitirmek için gereken tasarruf oranı
    # Pitten önce kaç tur tamamlanabilir (sonunda YEDEK_TUR kalsın; sıkışıksa yedeksiz)
    k = math.floor(menzil - YEDEK_TUR)
    if k < 1 and menzil >= 1:
        k = 1
    p["acil"] = menzil < 1                          # bu turu bitirmeye bile yetmeyebilir
    k = max(k, 0)
    p["en_gec"] = simdiki_tur + max(k, 1) - 1       # bu turun sonunda pite girilir
    kapasite = kapasite if kapasite and kapasite > 0 else None
    tam_stint = math.floor(kapasite / tur_basi - YEDEK_TUR) if kapasite else None
    sonra = kalan_tur - k                           # pitten sonra kalan tur
    depoda = max(0.0, yakit - k * tur_basi)
    if tam_stint and tam_stint >= 1:
        p["pit_sayisi"] = 1 + max(0, math.ceil((sonra - tam_stint) / tam_stint))
        # Tek pitte: en erken, pitten sonra dolu depoyla bitişe yetecek tur
        p["en_erken"] = min(p["en_gec"], simdiki_tur + max(0, kalan_tur - tam_stint) - 1)
    else:
        p["pit_sayisi"] = 1
        p["en_erken"] = p["en_gec"]
    if p["pit_sayisi"] == 1:
        al = math.ceil((sonra + YEDEK_TUR) * tur_basi - depoda)
        if kapasite:
            al = min(al, math.floor(kapasite - depoda))
        p["alinacak"] = max(1, al)
    else:
        p["alinacak"] = None                        # depoyu doldur
    return p


def harita(p, pit_sn=None):
    """Pitsiz bitirmek için yakıt haritası kaç kademe düşürülmeli ve pite göre kazançlı mı?
    Döner: {"kademe", "kayip" (toplam sn), "pit_sn", "kazanc" (sn)} ya da (uygun değilse) None."""
    if not p or not p.get("pit") or p.get("acil") or p.get("pit_sayisi") != 1:
        return None
    t = p.get("tasarruf") or 0
    if t <= 0 or t >= 1:
        return None
    kademe = 1
    while 1 - HARITA_TUKETIM ** kademe < t:
        kademe += 1
        if kademe > HARITA_EN_COK:
            return None
    kayip = kademe * HARITA_YAVAS_S * p["kalan_tur"]
    pit = pit_sn or PIT_VARSAYILAN_S
    if kayip >= pit:
        return None
    return {"kademe": kademe, "kayip": kayip, "pit_sn": pit, "kazanc": pit - kayip}


def _tur(n):
    return f"{n}. tur"


def satir(p, pit_sn=None):
    """Tur notları için tek satır."""
    if not p:
        return None
    if not p["pit"]:
        return (f"Strateji: yakıt bitişe yeter (kalan {p['kalan_tur']} tur için ~{p['gerek']:.1f} L, depoda "
                f"{p['yakit']:.1f} L; {p['fazla_tur']:.1f} tur fazlası var). Pit gerekmez.")
    if p["acil"]:
        s = "Strateji: yakıt bu turu bitirmeye yetmeyebilir, hemen pite gir"
    else:
        pencere = (_tur(p["en_gec"]) if p["en_erken"] >= p["en_gec"]
                   else f"{p['en_erken']}.–{p['en_gec']}. tur")
        s = (f"Strateji: {p['pit_sayisi']} pit gerekli. Pit penceresi: {pencere} "
             f"(en geç {p['en_gec']}. turun sonunda gir)")
    s += (f", en az {p['alinacak']} L al." if p.get("alinacak") else ", depoyu doldur.")
    if pit_sn:
        s += f" Pit ~{pit_sn:.0f} sn kaybettirir."
    h = harita(p, pit_sn)
    if h:
        s += (f" Daha hızlısı: yakıt haritasını {h['kademe']} kademe düşür, pitsiz bitirirsin "
              f"(tur başına ~{h['kademe'] * HARITA_YAVAS_S:.2f} sn yavaşlarsın, toplam ~{h['kayip']:.0f} sn; "
              f"pitten ~{h['kazanc']:.0f} sn kazançlı).")
    elif p["pit_sayisi"] == 1 and p["tasarruf"] <= TASARRUF_EN_COK:
        s += (f" Ya da tur başına %{math.ceil(p['tasarruf'] * 100)} az yakarak pitsiz bitirebilirsin "
              "(daha tasarruflu yakıt haritası, erken vites, düzlük sonunda gazı biraz erken bırakma).")
    return s


def kisa(p):
    """Canlı ekrandaki yakıt kutusu için çok kısa durum."""
    if not p:
        return None
    if not p["pit"]:
        return "bitişe yeter"
    if p["acil"]:
        return "HEMEN PİT"
    return f"pit en geç {p['en_gec']}. tur"


def sesli(p, durum, pit_sn=None):
    """Sesli söylenecek cümle (ya da None). durum: seans boyunca saklanan sözlük (neyin söylendiği).
    Sadece durum değişince konuşur: pit ilk kez gerektiğinde, pit turunda, pitten sonra "artık yeter"."""
    if not p:
        return None
    if p["pit"] and p["acil"]:
        return "Yakıt bu turu bitirmeye yetmeyebilir. Hemen pite gir."
    onceki = durum.get("pit")
    durum["pit"] = p["pit"]
    if not p["pit"]:
        if onceki:          # pite girildi, yakıt artık yetiyor
            durum.pop("pit_turu_dedi", None)
            return "Yakıt artık bitişe yeter."
        return None
    al = f"En az {p['alinacak']} litre al." if p.get("alinacak") else "Depoyu doldur."
    if p["tur"] == p["en_gec"] and durum.get("pit_turu_dedi") != p["en_gec"]:
        durum["pit_turu_dedi"] = p["en_gec"]
        return f"Bu tur sonunda pite gir. {al}"
    if not onceki:
        h = harita(p, pit_sn)
        if h:
            return (f"Yakıt bitişe yetmeyecek. Yakıt haritasını {h['kademe']} kademe düşür, pite girmeden "
                    f"bitirirsin. Pitten yaklaşık {h['kazanc']:.0f} saniye kazançlı.")
        return f"Yakıt bitişe yetmeyecek. En geç {p['en_gec']}. turda pite gir."
    return None
