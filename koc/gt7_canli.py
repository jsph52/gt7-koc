# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Sürerken konuşan koç
- Araç referans turun neresinde? (canlı konum ve canlı zaman farkı)
- Virajlara yaklaşırken kısa sesli uyarı ("Viraj 6. Geçen tur frene erken bastın...")
- Vites türünü (manuel/otomatik) sürüşten tahmin eder
- Kullanıcı ayarları (ayarlar.json)
"""
import json
import os
import statistics

from gt7_yol import USER_DIR
from gt7_kopru import (COAST_MIN_M, EXIT_MIN_KMH, LINE_MIN_M, TRAIL_MIN_M, brake_point_delta,
                       coast_m, kaza_mi, min_speed_delta, section_bounds, section_time, side_offset)
from gt7_kopru import (buyuk_harf, de, ReferencePath, _interp, measure, LapTrace, place_corners,
                       to_samples)
from gt7_konusma import BIP_TAVSIYE, DUZELDI, HATIRLATMA, IYI, OVGU, YINE, hata_ve_tavsiye, kod_tavsiye, sec, tavsiye
from app.processing.alignment import PathTracker

AYAR_FILE = os.path.join(USER_DIR, "ayarlar.json")
VARSAYILAN = {"uyari": "sorunlu",    # "hepsi" ya da "sorunlu"
              "vites": "algila",     # "algila", "manuel", "otomatik"
              "fren_sesi": "acik",   # "acik", "kapali": virajdan önce 3 bip
              "cikis_yorumu": "acik",  # "acik", "kapali": viraj çıkışında kazanç/kayıp yorumu
              "hassasiyet": "ileri",   # baslangic/orta/ileri/uzman/uzayli: virajda yüzde kaç kayıp söylenir
              "guc_dagilimi": {},      # araba kodu -> güç dağıtıcının ön payı (40 = 40:60), 4 çekerde
              "vites_araba": {},       # araba kodu -> "manuel"/"otomatik": algılanan vites türü yanlışsa (koç ekranından)
              "ses": "ahmet",          # koçun sesi: "ahmet", "emel" (gt7_ses.SESLER)
              "ses_hizi": "normal",    # "yavas", "normal", "hizli", "cok_hizli" (gt7_ses.HIZLAR)
              "telsiz": "kapali",      # "kapali", "hafif", "guclu": sese telsiz efekti (arayüzde ve Discord'da)
              # Koç ne zaman konuşsun (Ayarlar > Ses). Varsayılan açık: sesli koç ilk açılışta susmasın.
              "ses_viraj": "acik",     # viraj öncesi uyarı / çıkış yorumu okunur
              "ses_tur": "acik",       # tur sonu özeti okunur
              "ses_muhendis": "acik",  # mühendis anonsları ve uyarılar (motor, lastik, sıra, yakıt…) okunur
              "sessiz": "kapali",      # "acik": koç hiç konuşmaz (üst çubuktaki ses düğmesi); fren uyarısı etkilenmez
              "ses_duzeyi": "100",     # koçun konuşma sesi, 10–100 (fren uyarısı etkilenmez)
              "ses_cikisi": "bilgisayar",  # "bilgisayar", "discord", "ikisi": ses ve bipler nereden çıkar
              "discord_kanal": "",     # Discord sesli kanal kimliği; boş = otomatik (insanların olduğu kanal)
              "referans": "rekor",     # koç neye göre konuşur: "rekor" (rekor turu varsa o) / "kendi" (kendi en iyin)
              # Rekor turu referansken fren noktası (16 Kasım 2026): "rekor" birebir / "benim" kendi fren gücüme göre
              "fren_noktasi": "rekor",
              "fren_payi": "yok",
              "yaris_tavsiye": "kapali",  # yarışta viraj tavsiyesi (16 Kasım 2026): kapalı = sadece mühendis + tur süresi
              "yonlendir_port": "",    # veri yönlendirme: PS5 paketleri bu porta da kopyalanır (boş = kapalı)
              "ses_cihazi": "",        # koçun sesi ve fren uyarısı hangi ses cihazından (boş = Windows varsayılanı)      # rekor turunda fren noktası önce: yok / az (10 m) / orta (20 m) / cok (30 m)
              "surum": 3}            # ayar dosyası sürümü (eski ayarları bir kez günceller)
AYAR_SURUM = 3
# Arayüzden gelebilecek değerler (başka değer yazılmaz; discord_kanal ve ses_duzeyi ayrıca denetlenir)
SECENEKLER = {"uyari": ("sorunlu", "hepsi"), "vites": ("algila", "manuel", "otomatik"),
              "fren_sesi": ("acik", "kapali"), "cikis_yorumu": ("acik", "kapali"),
              "hassasiyet": ("baslangic", "orta", "ileri", "uzman", "uzayli"),
              "ses": ("ahmet", "emel"), "ses_hizi": ("yavas", "normal", "hizli", "cok_hizli"),
              "telsiz": ("kapali", "hafif", "guclu"), "ses_viraj": ("acik", "kapali"),
              "ses_tur": ("acik", "kapali"), "ses_muhendis": ("acik", "kapali"),
              "sessiz": ("kapali", "acik"), "ses_cikisi": ("bilgisayar", "discord", "ikisi"),
              "referans": ("rekor", "kendi"), "fren_noktasi": ("rekor", "benim"),
              "fren_payi": ("yok", "az", "orta", "cok"), "yaris_tavsiye": ("kapali", "acik")}


def gecerli(ad, deger):
    """Bu ayar bu değeri alabilir mi? (arayüzden gelen istekler için)"""
    if ad in SECENEKLER:
        return deger in SECENEKLER[ad]
    if ad == "ses_duzeyi":
        return isinstance(deger, str) and deger.isdigit() and 0 <= int(deger) <= 100
    if ad == "yonlendir_port":
        return isinstance(deger, str) and (deger == "" or (deger.isdigit() and 1024 <= int(deger) <= 65535
                                                          and int(deger) not in (33739, 33740)))
    if ad == "ses_cihazi":
        return isinstance(deger, str) and len(deger) <= 300
    if ad == "discord_kanal":
        return isinstance(deger, str) and (deger == "" or deger.isdigit())
    return False


def ses_duzeyi(ayar):
    """Koçun konuşma sesi 0,1–1,0 (ayar bozuksa 1,0)."""
    try:
        return max(0.1, min(1.0, int(ayar.get("ses_duzeyi", 100)) / 100))
    except (TypeError, ValueError):
        return 1.0

LEAD_S = 3.5          # uyarı, fren noktasından bu kadar saniye önce söylenir
LEAD_MIN_M = 120      # ... ama en az bu kadar metre önce
MERGE_S = 3.0         # tetikleri bu kadar saniyeden yakın virajlar tek uyarıda birleşir
STALE_M = 250         # tetik noktasını bundan fazla geçtiysek (ör. pitten çıkış) susar
OFF_PATH_M = 40       # referans çizgiden bu kadar uzaksa canlı fark gösterilmez


# ---------------- Ayarlar ----------------
def ayar_oku():
    try:
        with open(AYAR_FILE, encoding="utf-8") as f:
            a = json.load(f)
    except (OSError, ValueError):
        a = {}
    if a and a.get("surum", 1) < 2:
        # Kullanıcı isteği (Kasım 2026): koç sadece sorunlu virajlarda konuşsun
        a["uyari"] = "sorunlu"
    if a and a.get("surum", 1) < 3:
        # Eskiden mühendis anonsları "Viraj sesi" ya da "Tur sesi" açıksa okunurdu: aynı davranış korunur
        if "ses_viraj" in a or "ses_tur" in a:
            a.setdefault("ses_muhendis", "acik" if "acik" in (a.get("ses_viraj"), a.get("ses_tur")) else "kapali")
        a["surum"] = AYAR_SURUM
    if a.get("hassasiyet") in ESKI_HASSASIYET:   # 14 Kasım 2026: 3 seviye (saniye) -> 5 seviye (yüzde)
        a["hassasiyet"] = ESKI_HASSASIYET[a["hassasiyet"]]
    a = {**VARSAYILAN, **{k: v for k, v in a.items() if k in VARSAYILAN}}
    for k in list(a):       # elle bozulmuş / eski sürümden kalan geçersiz değer: varsayılana dön
        if k not in ("guc_dagilimi", "vites_araba", "surum") and not gecerli(k, a[k]):
            a[k] = VARSAYILAN[k]
    for k in ("guc_dagilimi", "vites_araba"):
        a[k] = dict(a[k]) if isinstance(a[k], dict) else {}
    # 16 Kasım 2026: "Viraj uyarıları", "Çıkış yorumu", "Koç neye göre konuşsun" ve vites ayarı Ayarlar'dan
    # kalktı (koçun ne kadar konuştuğunu hassasiyet, referansı hedef tur belirler).
    a["uyari"], a["cikis_yorumu"], a["vites"] = "sorunlu", "acik", "algila"
    return a


def ayar_yaz(**degisen):
    a = ayar_oku()
    a.update({k: v for k, v in degisen.items() if k in VARSAYILAN})
    try:
        with open(AYAR_FILE, "w", encoding="utf-8") as f:
            json.dump(a, f, ensure_ascii=False)
    except OSError:
        pass
    return a


# ---------------- Vites türü tahmini ----------------
def _yayilim(vals):
    return statistics.pstdev(vals) / (statistics.mean(vals) or 1) if len(vals) >= 2 else None


def vites_turu_tahmin(lap):
    """Bir turdaki vites geçişlerinden manuel/otomatik tahmini. Emin değilse None.
    Otomatik vites, gazdayken hep neredeyse aynı devirde büyütür ve frende her vitesi
    aynı devirde küçültür; devir sınırına da dayanmaz. Manuelde bu devirler değişir
    ve devir sınırı bayrağı yanar."""
    g, rpm, thr = lap.get("gear"), lap.get("rpm"), lap.get("throttle")
    lim = lap.get("revlim") or []
    if not g or not rpm or not thr:
        return None
    if sum(1 for v in lim if v) / 60.0 > 1.0:
        return "manuel"
    yukari, asagi = [], {}
    for i in range(1, len(g)):
        a, b = g[i - 1], g[i]
        if not (1 <= a <= 9 and 1 <= b <= 9):
            continue
        if b == a + 1 and max(thr[max(0, i - 15):i]) > 80:   # vites atarken GT7 gazı keser
            yukari.append(rpm[i - 1])
        elif b == a - 1:
            asagi.setdefault(a, []).append(rpm[i - 1])
    if len(yukari) < 3:
        return None
    y = _yayilim(yukari)
    a_list = [v for v in (_yayilim(x) for x in asagi.values()) if v is not None]
    a_ort = sum(a_list) / len(a_list) if a_list else None
    if y < 0.03 and (a_ort is None or a_ort < 0.03):
        return "otomatik"
    return "manuel"


# ---------------- Uyarı cümleleri ----------------
SESLI_ESIK_S = 0.15   # virajda bundan az zaman kaybı varsa sesli uyarı yapılmaz (eşik verilmezse)
# Hassasiyet: viraj, en iyi geçişinden YÜZDE kaç yavaşsa konuşulur.
# Saniye yerine yüzde: 2 sn'lik bir şikanda 0,1 sn büyük hata, 8 sn'lik uzun virajda küçük.
HASSASIYET = {"baslangic": 0.10, "orta": 0.05, "ileri": 0.03, "uzman": 0.02, "uzayli": 0.01}
ESKI_HASSASIYET = {"rahat": "orta", "normal": "ileri", "siki": "uzman"}
EN_AZ_S = 0.05        # yüzde ne derse desin bundan küçük kayıp ölçüm gürültüsü sayılır
CIKIS_ORAN = 2 / 3    # çıkış yorumu (düzeldi / sürüyor) eşiği, viraj öncesi eşiğin bu kadarı


def esikler(ayar):
    """Hassasiyet ayarının yüzdesi (0,03 = %3)."""
    return HASSASIYET.get((ayar or {}).get("hassasiyet"), HASSASIYET["ileri"])


FREN_KODLARI = ("fren_erken", "fren_gec")
# Ne zaman konuşulur:
# sabit "turda N viraj" ya da "N saniyede bir" yok. Koç cümlenin kaç saniye süreceğini tahmin eder; cümle
# sıradaki fren noktasına kadar sakin bir boşluğa SIĞIYORSA söyler, sığmıyorsa hiç söylemez (yarım cümle yok).
# İki mesaj arasında kısa bir nefes payı bırakılır; art arda virajlarda ikincisi bu yüzden söylenmeyebilir.
NEFES_S = 3.0         # bir mesaj bittikten sonra bir sonrakine kadar en az bu kadar sessizlik
HARF_SN = 14.0        # Türkçe ses yaklaşık bu kadar harf / saniye okur (Ahmet, normal hız; tahmini)
TEKRAR_SINIRI = 2     # aynı virajda aynı tavsiye üst üste bu kadar tur söylendiyse bir tur dinlenir
BUYUK_KAT = 3         # tavsiye verilmemiş virajda çıkış yorumu ancak çıkış eşiğinin bu kadar katı farkta
ILK_TUR_KAT = 3       # ilk tur (henüz karşılaştırma yok): sadece en belirgin hatalar, eşiğin 3 katı
# Sakin an: koç viraj içinde / frende konuşmaz, düzlükte gaz açıkken konuşur.
SAKIN_GAZ = 80        # çıkış yorumu için: gaz en az bu kadar açık, fren yok
UYARI_GAZ = 50        # viraj öncesi tavsiye: frende ya da gaz bunun altındayken söylenmez, sakin an beklenir
# Aynı virajda birden fazla sorun: viraj öncesi tavsiyede ikisi tek cümlede (sığarsa). Birbirine çok benzeyen
# tavsiyeler birlikte söylenmez (aynı grup).
GRUP = {"fren_erken": "fren", "fren_gec": "fren", "fren_bas": "fren", "kilit": "fren", "gaz_gec": "cikis",
        "cikis_yavas": "cikis", "bosta": "cikis", "pompa": "cikis"}


def konusma_suresi(metin):
    """Cümlenin sesli okunması yaklaşık kaç saniye sürer (harf sayısından)."""
    return 0.4 + len(metin or "") / HARF_SN


def ikinci_sorun(r, ilk, manuel, fren_bipi=False):
    """Aynı virajda söylenebilecek ikinci sorun (ilkiyle aynı grupta olmayan) ya da None."""
    for i in (r or {}).get("issues", []):
        k = i["kod"]
        if k == ilk["kod"] or k == "duzluk" or (k == "vites" and not manuel) or (fren_bipi and k in FREN_KODLARI):
            continue
        if GRUP.get(k) and GRUP.get(k) == GRUP.get(ilk["kod"]):
            continue
        return i
    return None


def kisa_ses(i, n=0):
    """Bir sorunun virajdan önce söylenecek kısa tavsiyesi (ör. 'frene biraz daha geç bas')."""
    return tavsiye(i, n)


def _sorunlar(r, manuel, fren_bipi=False, esik=SESLI_ESIK_S):
    """Bir virajın son turdaki sorunları (öncelik sırasıyla). Otomatik viteste vites,
    fren bipi açıkken fren zamanlaması (bip zaten söylüyor) hariç."""
    if not r or r["delta"] <= esik:
        return []
    return [i for i in r["issues"] if (manuel or i["kod"] != "vites")
            and not (fren_bipi and i["kod"] in FREN_KODLARI)]


CIKIS_ESIK_S = 0.10   # bundan küçük kazanç/kayıpta çıkış yorumu yapılmaz (Normal hassasiyet)


def cikis_sebepleri(me, rs, line_m, exit_diff, kayip, kayma=0.0):
    """Bu geçişin sebepleri (compare ile aynı eşikler), öncelik sırasıyla: [(kod, yan)].
    yan sadece çizgi sorununda dolu: tepe noktasında fazla kalınan taraf ("sağ"/"sol").
    kayma: fren noktası referanstan kaç m öne alındı (o noktada frenlemek "erken" sayılmaz)."""
    bd = brake_point_delta(me, rs)
    if bd is not None:
        bd += kayma
    sd = min_speed_delta(me, rs)
    td = (me.throttle_on - rs.throttle_on if me and rs and me.throttle_on is not None
          and rs.throttle_on is not None else None)
    out = []
    if kayip:
        if bd is not None and bd < -15:
            out.append(("fren_erken", None))
        if bd is not None and bd > 15:
            out.append(("fren_gec", None))
        if (me and rs and me.trail_m is not None and rs.trail_m is not None
                and rs.trail_m >= TRAIL_MIN_M and rs.trail_m - me.trail_m > TRAIL_MIN_M):
            out.append(("iz_freni", None))
        if line_m is not None and abs(line_m) >= 1.5 * LINE_MIN_M:
            out.append(("cizgi", "sağ" if line_m > 0 else "sol"))
        if sd is not None and sd < -3:
            out.append(("orta_yavas", None))
        if td is not None and td > 15:
            out.append(("gaz_gec", None))
        co_me, co_rs = coast_m(me), coast_m(rs)
        if co_me is not None and co_rs is not None and co_me - co_rs > COAST_MIN_M:
            out.append(("bosta", None))
        if exit_diff is not None and exit_diff < -EXIT_MIN_KMH:
            out.append(("cikis_yavas", None))
        return out
    if bd is not None and bd > 10:
        out.append(("fren_gec_k", None))
    if sd is not None and sd > 3:
        out.append(("orta_hizli", None))
    if td is not None and td < -10:
        out.append(("gaz_erken", None))
    if exit_diff is not None and exit_diff > EXIT_MIN_KMH:
        out.append(("cikis_hizli", None))
    return out


def kayip_cumlesi(no, sebepler):
    """"Viraj 3'te frene erken bastın, bir dahakine daha geç bas." Sebep bilinmiyorsa None
    (tavsiyesiz 'zaman kaybettin' demek sürücüye bir şey kazandırmıyor)."""
    for kod, yan in sebepler:
        ne, yap = hata_ve_tavsiye(kod, "tepe", yan)
        if ne:
            return f"Viraj {de(no)} {ne}" + (f", {yap}." if yap else ".")
    return None


def kazanc_cumlesi(no, sebepler, n=0):
    """"Viraj 3'te çıkışın çok iyiydi, böyle devam et." """
    for kod, _ in sebepler:
        if kod in IYI:
            return f"Viraj {de(no)} {IYI[kod]}, {sec(OVGU, n)}."
    return f"Viraj {no} çok iyiydi, {sec(OVGU, n)}."


def takip_cumlesi(no, onceki, sebepler, delta, esik, n=0):
    """Geçen sefer söylenen sorunla bu geçişi karşılaştırır.
    onceki: {"kod", "delta"} (geçen geçişin en iyiye göre kaybı); sebepler: bu geçişte görülen
    sorunlar [(kod, yan)]. Döner: (metin, düzeldi mi) ya da (None, False)."""
    if not onceki:
        return None, False
    kazanc = onceki["delta"] - delta
    kod = onceki["kod"]
    kodlar = {k for k, _ in sebepler}
    hala = kod in kodlar
    olculur = kod in YINE   # vites gibi sorunlar viraj çıkışında ölçülmez
    if olculur and not hala and kazanc >= esik:
        ne = DUZELDI.get(kod, "düzelttin")
        return (f"Güzel, Viraj {de(no)} {ne}." if n % 2 == 0
                else f"Viraj {de(no)} {ne}, {sec(OVGU, n)}."), True
    if olculur and hala and delta >= esik:
        yan = next((y for k, y in sebepler if k == kod), None)
        yap = hata_ve_tavsiye(kod, "tepe", yan)[1]
        return f"Viraj {de(no)} {sec(YINE[kod], n)}" + (f", {yap}." if yap else "."), False
    if -kazanc >= esik:           # başka bir şey bozuldu: sebebi biliniyorsa onu söyle
        return kayip_cumlesi(no, sebepler), False
    return None, False


def viraj_sorunu(r, manuel, fren_bipi=False, esik=SESLI_ESIK_S):
    """Tek viraj için söylenecek sorun (ilk sorun) ya da None."""
    sorun = _sorunlar(r, manuel, fren_bipi, esik)
    return sorun[0] if sorun else None


# ---------------- Önemli virajlar (14 Kasım 2026) ----------------
# Kullanıcı: "tur sonunda öneri veriyor ama unutuluyor; o viraja yaklaşırken kısaca hatırlatsın,
# ama her virajda değil, önemli olanlarda". Tur sonu sesi ve viraj öncesi hatırlatma AYNI sıralamayı
# kullanır, böylece tur sonunda söylenen viraj bir sonraki turda o viraja gelirken hatırlatılır.
GECMIS_TUR = 3        # puan için son kaç tura bakılır
TEKRAR_CARPAN = 0.25  # aynı sorun her fazladan turda tekrar ettiyse puan bu kadar artar


def onemli_virajlar(cmp_res, gecmis=(), manuel=False, esik=0.05):
    """Virajları önem sırasına koyar: [{"no", "delta", "skor", "sorun", "tekrar"}], en önemli önce.
    Sadece bu turda esik'ten fazla kaybettiren ve sebebi bilinen virajlar.
    gecmis: önceki turlar [{viraj no: [delta, sorun kodu]}] (en eskisi önce; bu tur hariç).
    Puan = (bu turdaki kayıp + son turların ortalama kaybı) / 2
           × (1 + 0,25 × (aynı sorunun son 3 turda fazladan tekrar sayısı)).
    Yani tek turluk bir hatadan çok, her tur aynı yerde aynı hatayla kaybettiren viraj öne çıkar."""
    out = []
    onceki = list(gecmis)[-(GECMIS_TUR - 1):]
    for r in cmp_res or []:
        if r["delta"] <= esik:
            continue
        sorun = next((i for i in r["issues"] if manuel or i["kod"] != "vites"), None)
        if not sorun:
            continue
        no = r["no"]
        deltalar = [r["delta"]] + [max(0.0, g[no][0]) for g in onceki if no in g]
        tekrar = 1 + sum(1 for g in onceki if no in g and g[no][1] == sorun["kod"] and g[no][0] > esik)
        skor = (r["delta"] + sum(deltalar) / len(deltalar)) / 2 * (1 + TEKRAR_CARPAN * (tekrar - 1))
        out.append({"no": no, "delta": r["delta"], "skor": round(skor, 3), "sorun": sorun, "tekrar": tekrar})
    out.sort(key=lambda o: -o["skor"])
    return out


def gecmise_ekle(gecmis, cmp_res, manuel=False):
    """Bu turun viraj sonuçlarını puan geçmişine ekler (son GECMIS_TUR tur tutulur)."""
    tur = {}
    for r in cmp_res or []:
        if r.get("kaza"):      # kaza / pistten çıkma virajın ortalamasını bozmasın
            continue
        sorun = next((i for i in r["issues"] if manuel or i["kod"] != "vites"), None)
        tur[r["no"]] = [round(r["delta"], 3), sorun["kod"] if sorun else None]
    gecmis.append(tur)
    del gecmis[:-GECMIS_TUR]
    return gecmis


class CanliKoc:
    """Referans tur üzerinde aracı takip eder, virajlardan önce uyarı üretir."""

    def __init__(self):
        self.ready = False
        self.tracker = None
        self.siradaki = None   # arayüz: {"no", "m", "fren", "kayip"}
        self.odak = None       # odak virajı: çıkış yorumu sadece o virajda
        self.fren_kayma = {}   # viraj no -> fren noktası kaç m öne alındı (rekor turunda güvenlik payı / fren gücü)
        self.yuzde = HASSASIYET["ileri"]
        self.sure_by = {}      # viraj no -> referans turda virajın kendi süresi (fren noktası -> çıkış, sn)
        self.soylenen = {}
        self.duzeltilen = []
        self.tur_say = 0       # kaç tur karşılaştırıldı (cümle çeşitlemesi için)
        self.tekrar = {}       # viraj no -> [kod, üst üste kaç tur söylendi]
        self.dinlenen = set()  # bu tur tavsiyesi söylenmeyecek virajlar (çok tekrar edildi)
        self._son_cmp = None

    def _tekrar_guncelle(self, adaylar):
        """Yeni tur: aynı virajda aynı tavsiye üst üste TEKRAR_SINIRI tur söylendiyse bu tur dinlenir."""
        self.tur_say += 1
        self.dinlenen = set()
        yeni = {}
        for no, kod in adaylar.items():
            onceki = self.tekrar.get(no)
            kac = onceki[1] + 1 if onceki and onceki[0] == kod else 1
            if kac > TEKRAR_SINIRI:
                self.dinlenen.add(no)
                kac = 0
            yeni[no] = [kod, kac]
        self.tekrar = yeni

    def esik(self, no, cikis=False):
        """Bu virajda konuşmak için gereken kayıp (sn): viraj süresinin hassasiyet yüzdesi."""
        sure = self.sure_by.get(no, SESLI_ESIK_S / HASSASIYET["ileri"])
        e = max(EN_AZ_S, self.yuzde * sure)
        return e * CIKIS_ORAN if cikis else e

    def hazirla(self, track, car, cmp_res, manuel, sadece_sorunlu, fren_bipi=False,
                esik=HASSASIYET["ileri"], eski=None, onemli=None, hatirlat=(), ref_tur=None):
        """Tur sonunda (ya da pist seçilince) çağrılır: en iyi temiz tur referans olur.
        esik: hassasiyet yüzdesi (0,03 = viraj en iyi geçişinden %3 yavaşsa konuşulur).
        eski: önceki seanstan söylenen sorunlar {viraj no (str): {"kod", "parca", "delta"}};
        bu seansta henüz karşılaştırma yoksa onlar hatırlatılır.
        onemli: onemli_virajlar() sıralaması (yoksa bu turdan hesaplanır).
        hatirlat: tur sonu sesinde söylenen virajlar: sıradan bağımsız mutlaka hatırlatılır.
        ref_tur: verilirse referans bu turdur (replay'den kaydedilen rekor turu), kendi en iyi turun değil."""
        self.ready = False
        self.yuzde = esik
        self.ilk_tur = cmp_res is None   # bu seansta henüz karşılaştırma yok: sadece en belirgin hatalar
        self.soylenen = {}     # viraj no -> {"kod", "parca", "delta"}: bu tur takip edilecek sorunlar
        laps = (track or {}).get("laps", {}).get(str(car)) or []
        corners = (track or {}).get("corners") or []
        if not (laps or ref_tur) or not corners:
            return
        best = ref_tur or laps[0]
        ref = to_samples(best)
        try:
            self.path = ReferencePath(ref)
            wins = place_corners(corners, ref)
            ms = measure(LapTrace(ref), wins)
        except Exception:
            return
        self.ref = ref
        self.length = ref["dist"][-1]
        self.wins, self.ref_m = wins, ms
        self.kayip_by = {r["no"]: round(r["delta"], 2) for r in (cmp_res or [])}
        self.bounds = section_bounds(wins, self.length)
        # Yüzdenin tabanı virajın KENDİ süresi (fren noktası ya da giriş -> çıkış), düzlük hariç: bölüm
        # süresi düzlüğü de içerdiği için uzun düzlükten önceki virajda eşik çok büyüyordu (Tokyo V1: 27 sn
        # bölüm, 5 sn viraj; 0,77 sn kayıp %3 eşiğinin altında kalıp söylenmiyordu)
        self.sure_by = {}
        for w in wins:
            m = ms.get(w.n)
            bas = min(m.brake_on, w.entry) if m and m.brake_on is not None else w.entry
            try:
                self.sure_by[w.n] = section_time(ref, bas, w.exit)
            except Exception:
                pass

        # Önce adaylar: önem sırasına göre her virajın söylenecek sorunu
        if onemli is None:
            onemli = onemli_virajlar(cmp_res, (), manuel, EN_AZ_S)
        hatirlat = {int(n) for n in hatirlat or ()}
        cmp_by = {r["no"]: r for r in (cmp_res or [])}
        aday = {}
        for o in onemli:
            if o["no"] not in {w.n for w in wins} or (o["delta"] < self.esik(o["no"]) and o["no"] not in hatirlat):
                continue
            sorun = o["sorun"]
            parca = tavsiye(sorun, self.tur_say + o["no"])
            if fren_bipi and sorun["kod"] in FREN_KODLARI:
                parca = sec(BIP_TAVSIYE[sorun["kod"]], self.tur_say + o["no"])   # bip zaten fren anını söylüyor
            ek = ikinci_sorun(cmp_by.get(o["no"]), sorun, manuel, fren_bipi)
            aday[o["no"]] = {"kod": sorun["kod"], "parca": parca, "delta": round(o["delta"], 3),
                             "skor": o["skor"], "etiket": "tur",
                             "ek": tavsiye(ek, self.tur_say + o["no"]) if ek else None}
        if cmp_res is None and eski:
            for no_s, e in eski.items():
                # Yeni seans, henüz karşılaştırma yok: geçen seansın sorununu hatırlat
                no = int(no_s)
                if no in {w.n for w in wins}:
                    aday[no] = {"kod": e["kod"], "parca": kod_tavsiye(e["kod"], no, e.get("parca")),
                                "delta": e.get("delta") or 0.0, "skor": e.get("delta") or 0.0, "etiket": "seans"}
        if cmp_res is not None and cmp_res is not self._son_cmp:
            self._son_cmp = cmp_res
            self._tekrar_guncelle({n: a["kod"] for n, a in aday.items()})
        # Tetik noktaları: fren noktasından max(120 m, 3,5 sn) önce; t_ref = referans turda o anın saniyesi
        plan = {}
        for w in wins:
            m = ms.get(w.n)
            nokta = m.brake_on - self.fren_kayma.get(w.n, 0.0) if m and m.brake_on is not None else w.entry
            v = max(10.0, _interp(ref["dist"], ref["speed"], nokta) / 3.6)
            once = max(LEAD_MIN_M, v * LEAD_S)
            t = (nokta - once) % self.length
            plan[w.n] = (nokta, v, once, t, _interp(ref["dist"], ref["t"], t))
        # Çok konuşmasın: önce tur sonunda söylenenler (hatırlatma), sonra puanı en yüksekler. Bir tavsiye,
        # daha önemli bir tavsiyeyle üst üste biniyorsa (önceki cümle + nefes payı bitmeden tetikleniyorsa) seçilmez.
        tur_s = ref["t"][-1] if ref["t"] else 0.0

        def sure_n(n):
            return konusma_suresi(f"Viraj {n}: {aday[n]['parca']}.")
        zorunlu = sorted((n for n in aday if n in hatirlat), key=lambda n: -aday[n]["skor"])
        for n in zorunlu:
            aday[n]["etiket"] = "hatirlat"
            self.dinlenen.discard(n)     # tur sonunda yine söylendiyse dinlendirme
        digerleri = sorted((n for n in aday if n not in hatirlat and n not in self.dinlenen),
                           key=lambda n: -aday[n]["skor"])
        if sadece_sorunlu:
            secilen = []
            for n in zorunlu + digerleri:
                tn = plan[n][4]
                uzak = all(((tn - plan[s][4]) % tur_s if tur_s else 0) >= sure_n(s) + NEFES_S
                           and ((plan[s][4] - tn) % tur_s if tur_s else 0) >= sure_n(n) + NEFES_S
                           for s in secilen)
                if n in zorunlu or uzak:
                    secilen.append(n)
            secilen = set(secilen)
        else:
            secilen = set(zorunlu + digerleri)
        tetikler = []
        for w in wins:
            m = ms.get(w.n)
            nokta, v, once, t, _ = plan[w.n]
            a = aday.get(w.n)
            parca = kalip = ek = None
            if a and (w.n in secilen or w.n in self.dinlenen):
                self.soylenen[w.n] = {"kod": a["kod"], "parca": a["parca"], "delta": a["delta"]}
                if w.n in self.dinlenen:
                    self.soylenen[w.n]["sessiz"] = True   # bu tur söylenmez, düzelirse yine övülür
                    continue
                parca, ek = a["parca"], a.get("ek")
                if a["etiket"] == "seans":
                    parca = "geçen seanstan hatırlatma, " + parca
                elif a["etiket"] == "hatirlat":
                    kalip = sec(HATIRLATMA, self.tur_say + w.n)
            if parca is None:
                if sadece_sorunlu:
                    continue
                # "Her viraj" ayarı: sorunsuz virajda kısa hatırlatma
                parca = "gazı kesmeden geç" if m and m.flat else "çizgin iyi, aynı şekilde geç"
            tetikler.append({"d": t, "v": v, "no": [w.n], "parca": [parca], "ek": [ek], "nokta": nokta,
                             "kalip": [kalip]})
        tetikler.sort(key=lambda x: x["d"])
        # Birbirine çok yakın virajları birleştir (konuşmalar üst üste binmesin)
        birlesik = []
        for t in tetikler:
            if birlesik and t["d"] - birlesik[-1]["d"] < MERGE_S * birlesik[-1]["v"]:
                birlesik[-1]["no"] += t["no"]
                birlesik[-1]["parca"] += t["parca"]
                birlesik[-1]["ek"] += t["ek"]
                birlesik[-1]["kalip"] += t["kalip"]
            else:
                birlesik.append(t)
        def cumle(no, parca, kalip):
            # Kısa ve tavsiye: "Viraj 7: frene biraz daha geç bas."
            # Tur sonunda söylenen viraj: daha doğal hatırlatma ("Viraj 5 geliyor, frene biraz daha geç bas.")
            return " ".join((k.replace("{no}'de", de(n)).format(no=n, t=p) if k else f"Viraj {n}: {p}.")
                            for n, p, k in zip(no, parca, kalip))

        for t in birlesik:
            no, parca, kalip = t["no"][:2], t["parca"][:2], t["kalip"][:2]   # en fazla 2 viraj tek uyarıda
            t["kisa"] = cumle(no, parca, kalip)
            # Aynı virajın ikinci sorunu da tek cümlede ("frene biraz erken bas, çıkışta gazı erken aç");
            # sadece tek virajlık uyarıda. Sığmazsa adim() kısa hâlini söyler.
            if len(no) == 1 and t["ek"][0]:
                t["metin"] = cumle(no, [f"{parca[0]}, {t['ek'][0]}"], kalip)
            else:
                t["metin"] = t["kisa"]
        self.tetikler = birlesik
        # Fren noktaları (frensiz virajda giriş): "sakin an" hesabı için
        self.noktalar = sorted((ms[w.n].brake_on - self.fren_kayma.get(w.n, 0.0)
                                if ms.get(w.n) and ms[w.n].brake_on is not None else w.entry)
                               for w in wins)
        self.tracker = PathTracker(self.path)
        self.reset()
        self.ready = True

    def reset(self):
        """Yeni tur başladı."""
        if self.tracker:
            self.tracker.reset()
        self.idx = 0
        self.son_s = None
        self.fark = None
        self.cidx = 0          # sıradaki çıkış değerlendirmesi yapılacak viraj
        self.buf = {k: [] for k in ("dist", "t", "speed", "brake", "throttle", "x", "z", "loose")}
        self.kaza = []         # bu turda kaza / pistten çıkma yüzünden yorum yapılmayan virajlar
        self.cikis = None      # çıkış yorumu (alınınca None olur)
        self.bek_cikis = None  # sakin an bekleyen çıkış yorumu {"metin", "son"}
        self.bek_uyari = None  # sakin an bekleyen viraj öncesi tavsiye (tetik)
        self.t = 0.0           # tur saati (sn)
        self.bitis = -NEFES_S  # koçun son cümlesinin bittiği an (tur saati)
        self.duzeltilen = []   # bu turda söylenen sorununu düzelttiğin virajlar

    def _cikis_degerlendir(self, s, v_ms):
        """Bölüm sonunu geçen virajlar için kazanç/kayıp ve sebep."""
        b = self.buf
        while self.cidx < len(self.wins) and s >= self.bounds[self.cidx][1]:
            i = self.cidx
            self.cidx += 1
            w, (a, e) = self.wins[i], self.bounds[i]
            if self.odak and w.n != self.odak:
                continue
            if not b["dist"] or b["dist"][0] > a + 30 or s - e > STALE_M:
                continue  # virajın başını görmedik (tur ortasında başladı) ya da çok geride kaldı
            try:
                delta = section_time(b, a, e) - section_time(self.ref, a, e)
                onceki = self.soylenen.get(w.n)
                rs = self.ref_m.get(w.n)
                # Kaza / pistten çıkma / dönme: teknik değil kaza; ne düzeltme ne övgü. Söylenen sorun
                # (hata takibi) da bu tur sayılmaz, sonraki turda yine bakılır
                if kaza_mi(b, self.ref, a, e, rs, delta):
                    self.kaza.append(w.n)
                    continue
                if abs(delta) < self.esik(w.n, True) and not onceki:
                    continue
                me = measure(LapTrace(b), [w]).get(w.n)
                x, z = _interp(b["dist"], b["x"], w.apex), _interp(b["dist"], b["z"], w.apex)
                line_m = side_offset(self.ref, w.apex, x, z)
                exit_diff = _interp(b["dist"], b["speed"], w.exit) - _interp(self.ref["dist"], self.ref["speed"], w.exit)
                ky = self.fren_kayma.get(w.n, 0.0)
                sebepler = cikis_sebepleri(me, rs, line_m, exit_diff, delta > 0, ky)
                # Söylenen sorun hâlâ var mı? (kazançlı geçişte de kayıp ölçütleriyle bakılır)
                tum = cikis_sebepleri(me, rs, line_m, exit_diff, True, ky)
            except Exception:
                continue
            n = self.tur_say + w.n
            takip, duzeldi = takip_cumlesi(w.n, onceki, tum, delta, self.esik(w.n, True), n)
            if duzeldi:
                self.duzeltilen.append(w.n)
            if onceki and onceki.get("sessiz") and not duzeldi:
                continue          # bu tur dinlenen viraj: sadece düzelirse övülür
            if takip is None:
                # Tavsiye verilmemiş viraj: sadece belirgin kazanç/kayıpta konuş (çok konuşmasın)
                kat = ILK_TUR_KAT * self.esik(w.n) if self.ilk_tur else BUYUK_KAT * self.esik(w.n, True)
                if abs(delta) < kat:
                    continue
                takip = kayip_cumlesi(w.n, sebepler) if delta > 0 else kazanc_cumlesi(w.n, sebepler, n)
                ek = True
            else:
                ek = False
            if takip is None:
                continue
            # Hemen söylenmez: sakin an beklenir (düzlük, gaz açık); sıradaki fren noktasına kadar gelmezse düşer
            self.bek_cikis = {"metin": takip, "son": self._siradaki_nokta(e), "ek": ek}

    def _siradaki_nokta(self, s):
        """s'den sonraki ilk fren noktası (tur sonundaysa sıradaki turun ilki)."""
        for d in self.noktalar:
            if d > s:
                return d
        return self.length + (self.noktalar[0] if self.noktalar else 0.0)

    def _sigar(self, metin, kalan_s):
        """Cümle (ve önceki cümleden sonra nefes payı) kalan süreye sığıyor mu?"""
        return self.t >= self.bitis + NEFES_S and konusma_suresi(metin) <= kalan_s

    def _soyledi(self, metin):
        self.bitis = self.t + konusma_suresi(metin)

    def _sakin_cikis(self, s, v_ms, brake, throttle):
        """Bekleyen çıkış yorumu şimdi söylenebilir mi? Söylenecekse self.cikis'e yazar."""
        b = self.bek_cikis
        if not b:
            return
        if s >= b["son"]:
            self.bek_cikis = None      # sıradaki viraja gelindi: geç kaldı, söylenmez
            return
        v = max(v_ms, 10)
        if (brake or 0) > 0 or (throttle is not None and throttle < SAKIN_GAZ):
            return
        # Cümle + nefes payı, sıradaki fren noktasından ve sıradaki viraj tavsiyesinden önce bitmeli
        kalan = (b["son"] - s) / v
        if self.bek_uyari:
            return
        if self.idx < len(self.tetikler):
            kalan = min(kalan, (self.tetikler[self.idx]["d"] - s) / v)
        if not self._sigar(b["metin"], kalan - NEFES_S):
            if konusma_suresi(b["metin"]) + NEFES_S > (b["son"] - s) / v:
                self.bek_cikis = None   # artık hiç sığmaz: söylenmez (yarım cümle yok)
            return
        self.cikis, self.bek_cikis = b["metin"], None
        self._soyledi(self.cikis)

    def adim(self, x, z, own_dist, t, speed=None, brake=None, throttle=None, zemin=None):
        """Her pakette: (uyarı metni ya da None, canlı fark sn ya da None, referans mesafesi).
        Viraj çıkış yorumu oluşursa self.cikis'e yazılır. zemin: gevşek zemindeki (çim/kum) teker sayısı."""
        if not self.ready:
            return None, None, None
        found = self.tracker.locate(x, z, own_dist)
        if found is None:
            return None, None, None
        s, off = found
        # Başlangıç çizgisi referansın hem başı hem sonu: tur başında "sonda" görünürse başa al
        if own_dist < 500 and s > self.length / 2:
            s -= self.length
        if off > OFF_PATH_M:
            return None, None, s
        self.t = t
        fark = t - _interp(self.ref["dist"], self.ref["t"], max(0.0, s))
        self.fark = fark if self.fark is None else 0.8 * self.fark + 0.2 * fark
        if speed is not None and s >= 0:
            b = self.buf
            if not b["dist"] or s > b["dist"][-1]:
                for k, val in (("dist", s), ("t", t), ("speed", speed), ("brake", brake),
                               ("throttle", throttle), ("x", x), ("z", z), ("loose", zemin)):
                    b[k].append(val)
            self._cikis_degerlendir(s, speed / 3.6)
            self._sakin_cikis(s, speed / 3.6, brake, throttle)
        uyari = None
        if self.son_s is not None and abs(s - self.son_s) > 300:
            # Konum sıçradı (geri sarma, pit): kaçırılan uyarıları söyleme, sıradakine geç
            while self.idx < len(self.tetikler) and self.tetikler[self.idx]["d"] <= s:
                self.idx += 1
            # Çıkış yorumu için tutulan veriyi de at, sıradaki virajdan devam et
            self.buf = {k: [] for k in self.buf}
            self.bek_cikis = self.bek_uyari = None
            while self.cidx < len(self.wins) and self.bounds[self.cidx][1] <= s:
                self.cidx += 1
        while self.idx < len(self.tetikler) and s >= self.tetikler[self.idx]["d"]:
            tt = self.tetikler[self.idx]
            self.idx += 1
            if s - tt["d"] <= STALE_M:
                self.bek_uyari = tt
        # Tavsiye frende / viraj içinde söylenmez: gaz açılana kadar bekler. Fren noktasına kadar cümlenin
        # tamamı sığmıyorsa kısa hâli (tek sorun) denenir, o da sığmıyorsa hiç söylenmez.
        if self.bek_uyari:
            bu = self.bek_uyari
            rem = (bu["nokta"] - s) % self.length      # tur başını geçen virajlar için
            kalan = rem / max(speed / 3.6 if speed else 10.0, 10.0)
            if rem > self.length / 2 or konusma_suresi(bu["kisa"]) > kalan:
                self.bek_uyari = None
            elif not (brake or 0) > 0 and (throttle is None or throttle >= UYARI_GAZ):
                for m in (bu["metin"], bu["kisa"]):
                    if self._sigar(m, kalan):
                        uyari, self.bek_uyari = m, None
                        self._soyledi(m)
                        break
        self.son_s = s
        # Arayüz için sıradaki viraj: fren noktasına (frensizse girişe) kalan mesafe
        self.siradaki = None
        for w in self.wins:
            m = self.ref_m.get(w.n)
            nokta = m.brake_on - self.fren_kayma.get(w.n, 0.0) if m and m.brake_on is not None else w.entry
            if w.apex > s:
                self.siradaki = {"no": w.n, "m": round(max(0.0, nokta - s)),
                                 "fren": bool(m and m.brake_on is not None),
                                 "kayip": self.kayip_by.get(w.n)}
                break
        if self.siradaki is None and self.wins:   # son virajdan sonra: sıradaki turun ilk virajı
            w = self.wins[0]
            m = self.ref_m.get(w.n)
            nokta = m.brake_on - self.fren_kayma.get(w.n, 0.0) if m and m.brake_on is not None else w.entry
            self.siradaki = {"no": w.n, "m": round(max(0.0, self.length - s + nokta)),
                             "fren": bool(m and m.brake_on is not None), "kayip": self.kayip_by.get(w.n)}
        return uyari, self.fark, s
