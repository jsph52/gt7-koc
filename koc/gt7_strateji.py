# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Pit / yakıt stratejisi (yarışta)
Yarışın toplam tur sayısı (telemetri 0x76) ve son turların ortalama tüketiminden:
- yakıt bitişe yetiyor mu, yetmiyorsa kaç pit gerekli,
- pit penceresi (en erken / en geç tur) ve pitte en az kaç litre alınmalı,
- pitsiz bitirmek için tur başına ne kadar az yakmak gerekir.
Yakıt ayarı telemetride yok ve bir kademenin ne kadar tasarruf ettirdiği bilinmiyor. Bu yüzden koç kesin kademe
sayısı söylemez: "söyle, ölç, düzelt" (24 Kasım 2026, kullanıcı seçti): "Yakıt ayarını bir kademe artır." ->
sonraki turun ölçülen tüketimiyle "Tamam, bu ayarla yakıt bitişe yetiyor." / "bir kademe daha artır" /
(tüketim değişmediyse) pit planı; yakıt fazla gelirse "bir kademe azaltabilirsin".
Lastik aşınması telemetride yok: strateji sadece yakıta göre. Eşikler tahmini, gerçek oyunda denenmedi.
"""
import math

YEDEK_TUR = 0.3        # her stintin sonunda depoda kalsın istenen pay (tur)
ARTIS_ORANI = 1.10      # son tur ortalamadan bu kadar fazla yaktıysa "tüketim arttı" (harita değişti)
AZALIS_ORANI = 0.95     # son tur ortalamadan bu kadar az yaktıysa "tüketim azaldı" (ayar tasarrufluya çevrildi)
TASARRUF_BEKLE_TUR = 2  # "bir kademe artır"dan sonra bu kadar tur tüketim düşmezse pit planına dönülür
TASARRUF_EN_COK = 0.10  # pitsiz bitirmek için bundan az tasarruf gerekiyorsa seçenek olarak söylenir
# Yakıt ayarı / yakıt haritası (yarış içi menü, 1 = en güçlü, 6 = en tasarruflu); seste "yakıt ayarı" denir. Numarayı her bir artırmak tüketimi yaklaşık %10
# azaltır, turu ~0,25 sn yavaşlatır (tahmini). Oyun şu anki haritayı göndermez: koç sadece kaç numara artırılacağını söyler.
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
        if kapasite:
            # Pit ekranı yakıtı litre değil, depo doluluğu (%) olarak gösterir ("Refuel 91%" = pitten sonra
            # depo %91 dolu): gereken doluluk 5'lik basamağa yukarı yuvarlanır (biraz pay, ekranda kolay ayar)
            yuzde = math.ceil((depoda + p["alinacak"]) / kapasite * 100 / 5 - 1e-9) * 5
            p["doluluk"] = yuzde if yuzde < 100 else None     # None: depoyu doldur
    else:
        p["alinacak"] = None                        # depoyu doldur
    return p


def tuketim(turlar):
    """Planın kullanacağı tur başı tüketim. turlar: bu yarıştaki tam turların tüketimi (L), en yenisi sonda.
    Son 3 turun ortalaması; son tur önceki turlardan belirgin fazla ya da az yaktıysa son tur (yakıt ayarı
    değiştiyse plan 3 tur gecikmesin). Döner: (L/tur, "artti" / "azaldi" / None) ya da (None, None)."""
    if not turlar:
        return None, None
    son3 = turlar[-3:]
    ort = sum(son3) / len(son3)
    if len(turlar) >= 2:
        onceki = turlar[-4:-1]
        o_ort = sum(onceki) / len(onceki)
        if turlar[-1] > ort * ARTIS_ORANI:
            return turlar[-1], "artti"
        if turlar[-1] < o_ort * AZALIS_ORANI:
            return turlar[-1], "azaldi"
    return ort, None


def degisim_satiri(turlar, degisim):
    """Tur notları: yakıt ayarı değişmiş görünüyorsa ölçülen tüketim."""
    if not degisim or len(turlar) < 2:
        return None
    onceki = turlar[-4:-1]
    return (f"Yakıt: son tur {turlar[-1]:.2f} L, önceki turların ortalaması {sum(onceki) / len(onceki):.2f} L: "
            "yakıt ayarı değişmiş görünüyor, plan son tura göre.")


def guclu_ek(p, turlar):
    """Pitsiz bitiş planına, yarışın en çok yakan turuyla da yetip yetmeyeceğini ekler (p["guclu_yeter"]).
    Sadece bu yarışta belirgin daha çok yakan bir tur görüldüyse (yani ayar sonradan tasarrufluya çevrildiyse).
    Ölçülmüş tüketim: kaç kademe olduğu bilinmez, yetiyorsa koç "bir kademe azaltabilirsin" der."""
    if not p or p["pit"] or not turlar:
        return p
    en_cok = max(turlar)
    if en_cok > p["tur_basi"] * ARTIS_ORANI:
        p["guclu_yeter"] = p["yakit"] >= en_cok * (p["kalan_tur"] + YEDEK_TUR)
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
    if p.get("doluluk"):
        s += f", depoyu en az %{p['doluluk']} doldur (en az {p['alinacak']} L)."
    elif p.get("alinacak") and "doluluk" not in p:
        s += f", en az {p['alinacak']} L al."
    else:
        s += ", depoyu doldur."
    if pit_sn:
        s += f" Pit ~{pit_sn:.0f} sn kaybettirir."
    h = harita(p, pit_sn)
    if h:
        s += (f" Daha hızlısı: yakıt ayarını artırıp (tahminen {h['kademe']} kademe; koç birer kademe söyler ve "
              f"her turu ölçer) pitsiz bitirmek: tur başına %{math.ceil(p['tasarruf'] * 100)} az yakmalısın "
              f"(tahminen toplam ~{h['kayip']:.0f} sn yavaşlarsın, pitten ~{h['kazanc']:.0f} sn kazançlı).")
    elif p["pit_sayisi"] == 1 and p["tasarruf"] <= TASARRUF_EN_COK:
        s += (f" Ya da tur başına %{math.ceil(p['tasarruf'] * 100)} az yakarak pitsiz bitirebilirsin "
              "(daha tasarruflu yakıt ayarı, erken vites, düzlük sonunda gazı biraz erken bırakma).")
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
    """Sesli söylenecek cümle (ya da None). durum: yarış boyunca saklanan sözlük (neyin söylendiği).
    Sadece durum değişince konuşur. Yakıt ayarı için "söyle, ölç, düzelt": durum["tasarruf"] =
    {"tur": öneri turu, "tb": o andaki tüketim} iken her tur ölçülen tüketime bakılır."""
    if not p:
        return None
    if p["pit"] and p["acil"]:
        return "Yakıt bu turu bitirmeye yetmeyebilir. Hemen pite gir."
    onceki = durum.get("pit")
    durum["pit"] = p["pit"]
    ts = durum.get("tasarruf")
    if not p["pit"]:
        if ts:                       # ayar artırıldı, ölçülen tüketimle artık yetiyor
            durum.pop("tasarruf", None)
            durum.pop("pit_turu_dedi", None)
            durum["fazla_dedi"] = True
            return "Tamam, bu ayarla yakıt bitişe yetiyor."
        if onceki:                   # pite girildi ya da tüketim azaldı, yakıt artık yetiyor
            durum.pop("pit_turu_dedi", None)
            if p.get("guclu_yeter") is False:
                durum["fazla_dedi"] = True
                # Şu anki (tasarruflu) tüketimle yetiyor ama yarışın en çok yakan turlarıyla yetmez
                return "Yakıt artık bitişe yeter. Yakıt ayarını değiştirme, daha güçlüsü yetmez."
            if p.get("guclu_yeter"):
                durum["fazla_dedi"] = True
                return "Yakıt artık bitişe yeter. İstersen yakıt ayarını bir kademe azaltabilirsin."
            durum["fazla_dedi"] = False
            return "Yakıt artık bitişe yeter."
        if p.get("guclu_yeter") and not durum.get("fazla_dedi"):
            durum["fazla_dedi"] = True
            return "Yakıt fazla geliyor, yakıt ayarını bir kademe azaltabilirsin."
        return None
    durum["fazla_dedi"] = False
    # "al." cümle sonunda ses motorunca harf harf okunuyordu: "almalısın" denir
    arti = "Yakıt tüketimin arttı. " if p.get("artti") else ""
    if p.get("doluluk"):
        al = f"Depoyu en az yüzde {p['doluluk']} doldur."
    elif p.get("alinacak") and "doluluk" not in p:      # depo kapasitesi bilinmiyorsa litre
        al = f"En az {p['alinacak']} litre yakıt almalısın."
    else:
        al = "Depoyu doldur."
    if p["tur"] == p["en_gec"] and durum.get("pit_turu_dedi") != p["en_gec"]:
        durum["pit_turu_dedi"] = p["en_gec"]
        durum.pop("tasarruf", None)
        return f"Bu tur sonunda pite gir. {al}"
    pit_plani = f"Yakıt bitişe yetmeyecek. En geç {p['en_gec']}. turda pite gir."
    h = harita(p, pit_sn)
    if ts:
        son = p.get("son_tur") or p["tur_basi"]          # son turun ölçülen tüketimi
        if son < ts["tb"] * AZALIS_ORANI:                 # ayar artırıldı ama hâlâ yetmiyor
            if h and ts.get("adim", 1) < HARITA_EN_COK:
                durum["tasarruf"] = {"tur": p["tur"], "tb": son, "adim": ts.get("adim", 1) + 1}
                return "Tüketim azaldı ama henüz yetmiyor. Yakıt ayarını bir kademe daha artır."
            durum.pop("tasarruf", None)
            return pit_plani
        if p["tur"] - ts["tur"] >= TASARRUF_BEKLE_TUR or not h:   # tüketim düşmedi: pit planına dön
            durum.pop("tasarruf", None)
            durum["vazgecti"] = True
            return pit_plani
        return None
    if not onceki:
        if h and not durum.get("vazgecti"):
            durum["tasarruf"] = {"tur": p["tur"], "tb": p["tur_basi"], "adim": 1}
            return f"{arti}Yakıt bitişe yetmeyecek. Yakıt ayarını bir kademe artır."
        return f"{arti}{pit_plani}"
    return None
