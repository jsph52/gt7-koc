# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Tur sonu sesli özeti
Kısa tutulur (en fazla 2 cümle): tur süresi + kritik bir uyarı (yakıt / lastik / teker)
ya da yoksa bir sonraki tur için tek odak.
Ekrandaki ayrıntılı notlar ayrıca gt7_koc.lap_end içinde yazılır.
"""
import re

from gt7_paket import sure
from gt7_kopru import buyuk_harf, de, den, ye
from gt7_canli import kisa_ses, onemli_virajlar
from gt7_konusma import parantezsiz

LASTIK_SICAK = 100     # °C, ortalama lastik sıcaklığı bunu aşarsa uyarılır (tahmini eşik, gerçek veriyle ayarlanacak)
YAKIT_AZ_TUR = 3       # yakıt bundan az tura yetiyorsa uyarılır
YAKIT_KRITIK_TUR = 1.5  # bundan azsa "kritik" denir (gt7-datalogger: 3 / 1,5 tur)
REVLIM_SN = 2.0        # manuelde devir sınırında bu kadar saniyeden fazla kalınırsa uyarılır


def kisa_sorun(problem):
    return problem.split(" (")[0].replace("en iyi turundan %7'den fazla yavaş", "rekorundan çok yavaş")


def sure_yorumu(lap_ms, best_before, problem):
    """Kısa ve insanca: "Tur 1:53.230. En iyinden 0.4 saniye yavaş." """
    t = sure(lap_ms)
    if problem:
        return f"Tur {t}. Bu turu saymadım: {kisa_sorun(problem)}."
    if best_before is None:
        return f"Tur {t}. İlk temiz turun, bundan sonrakileri bununla karşılaştıracağım."
    fark = (lap_ms - best_before) / 1000
    if fark <= -0.05:
        return f"Yeni en iyi tur, {t}! {-fark:.1f} saniye daha hızlısın."
    if fark < 0:
        return f"Yeni en iyi tur, {t}!"
    if fark < 0.05:
        return f"Tur {t}. En iyi turunla neredeyse aynı."
    return f"Tur {t}. En iyinden {fark:.1f} saniye yavaş."


def egilim(gecmis):
    """gecmis: bu seanstaki temiz tur süreleri (ms), son eleman bu tur."""
    if len(gecmis) >= 3 and gecmis[-3] > gecmis[-2] > gecmis[-1]:
        return "Üç turdur hızlanıyorsun, böyle devam."
    if len(gecmis) >= 3 and gecmis[-3] < gecmis[-2] < gecmis[-1]:
        return "Son turlarda yavaşlıyorsun, acele etme, ritmini koru."
    if len(gecmis) >= 4 and max(gecmis[-4:]) - min(gecmis[-4:]) < 400:
        return "Turların çok tutarlı."
    return None


def kritikler(yakit_tur, kalan_tur, lastik, teker_tekrar, revlim_s, manuel, pit_sn=None, strateji_ses=None,
              hava_ses=None):
    """Duruma göre öne çıkan uyarılar (en önemliden başlayarak).
    strateji_ses: yarışta pit planı cümlesi (gt7_strateji.sesli); varsa yakıt uyarısının yerine geçer."""
    out = []
    if strateji_ses:
        out.append(strateji_ses)
    elif yakit_tur is not None and (yakit_tur < YAKIT_AZ_TUR or (kalan_tur and yakit_tur < kalan_tur)):
        if yakit_tur < YAKIT_KRITIK_TUR:
            cumle = f"Yakıt kritik! {yakit_tur:.1f} turluk kaldı."
        else:
            cumle = f"Yakıt azaldı, {yakit_tur:.1f} turluk kaldı."
        if kalan_tur and yakit_tur < kalan_tur:
            cumle += f" Yakıt yetmeyecek, {kalan_tur - yakit_tur:.1f} tur eksik." + (
                f" Pit yaklaşık {pit_sn:.0f} saniye kaybettirir." if pit_sn else "")
        out.append(cumle)
    if hava_ses:            # ıslak pist şüphesi (gt7_analiz.islak_tur)
        out.append(hava_ses)
    if lastik:
        on, arka = lastik.get("on"), lastik.get("arka")
        if on and on >= LASTIK_SICAK and (not arka or on >= arka):
            out.append(f"Ön lastik sıcaklıkları yüksek, {on:.0f} derece. Frene ve direksiyona yumuşak davran.")
        elif arka and arka >= LASTIK_SICAK:
            out.append(f"Arka lastik sıcaklıkları yüksek, {arka:.0f} derece. Çıkışta gazı yumuşak aç.")
    for e in teker_tekrar[:1]:
        if e["tip"] == "kilit":
            out.append(f"Viraj {ye(e['viraj'])} girerken {e['teker']} sürekli kilitleniyor. Frene yumuşak bas.")
        else:
            out.append(f"Viraj {den(e['viraj'])} çıkarken {e['teker']} sürekli patinaj yapıyor. Gazı yumuşak aç.")
    if manuel and revlim_s and revlim_s > REVLIM_SN:
        out.append(f"Devir sınırında {revlim_s:.0f} saniye kaldın. Vitesi daha erken at.")
    return out


def _sebep_ve_tavsiye(o, n=0):
    """Önemli virajın sorunu: (ne oldu: ekran notundaki ölçümle, ne yapmalı)."""
    sorun = o["sorun"]
    return parantezsiz(sorun.get("ekran")), kisa_ses(sorun, n)


def odak(cmp_res, manuel, ikinci=True, n=0, onemli=None, soylenen=None, rekor=False):
    """Bir sonraki tur için tavsiye: en önemli viraj (onemli_virajlar sırası: kayıp + tekrar),
    sebebi (Notlar'daki ölçümle) ve ne yapmalı. ikinci=True ise sıradaki viraj da kısaca eklenir.
    soylenen: söylenen viraj numaraları buna eklenir (sonraki turda o viraja gelirken hatırlatılır).
    "En çok Viraj 5'te kaybettin, 0.3 saniye: frene 15 m erken bastın. Frene biraz daha geç bas." """
    if not cmp_res:
        return None
    if onemli is None:
        onemli = onemli_virajlar(cmp_res, (), manuel)
    kayip = [o for o in onemli if o["delta"] > 0.1]
    if not kayip:
        if any(r["delta"] > 0.1 for r in cmp_res):
            return None             # kayıp var ama sebebi bilinmiyor: tavsiyesiz bir şey söyleme
        return ("Virajların hepsi rekor turuna yakın, harika gidiyorsun." if rekor
                else "Virajların hepsi en iyi geçişine yakın, böyle devam et.")
    o = kayip[0]
    ne, yap = _sebep_ve_tavsiye(o, n)
    if o["tekrar"] >= 2:
        metin = f"Viraj {de(o['no'])} {o['tekrar']} turdur zaman kaybediyorsun, bu tur {o['delta']:.1f} saniye"
    else:
        metin = ((f"Rekor turuna göre en çok Viraj {de(o['no'])} kaybediyorsun" if rekor
                  else f"En çok Viraj {de(o['no'])} kaybettin") + f", {o['delta']:.1f} saniye")
    metin += f": {ne}. {buyuk_harf(yap)}."
    if soylenen is not None:
        soylenen.append(o["no"])
    if ikinci and len(kayip) > 1:
        o2 = kayip[1]
        ne2, _ = _sebep_ve_tavsiye(o2, n + 1)
        metin += f" Sonra Viraj {o2['no']}: {ne2}."
        if soylenen is not None:
            soylenen.append(o2["no"])
    return metin


def virajlar_metni(nolar):
    nolar = [str(n) for n in nolar]
    return nolar[0] if len(nolar) == 1 else ", ".join(nolar[:-1]) + " ve " + nolar[-1]


def ses_ozeti(lap_ms, best_before, problem, gecmis, cmp_res, manuel,
              yakit_tur=None, kalan_tur=None, lastik=None, teker_tekrar=(), revlim_s=None, ayar_ses=None,
              duzeltilen=(), sira=None, tempo=None, fren_ses=None, pit_sn=None, strateji_ses=None,
              hava_ses=None, onemli=None, soylenen=None, rekor=False, tavsiye=True):
    """Tur sonunda sesli okunacak metin: süre + (varsa tek önemli uyarı) + tavsiye.
    Tavsiye her zaman vardır (Notlar'daki analiz sesli de söylenir):
    fren alışkanlığı ya da en çok kaybettiren viraj, sebebi ve ne yapmalı.
    duzeltilen: geçen sefer söylenen sorunu bu turda düzeltilen virajlar (kısa övgü).
    sira: yarışta (sıra, araç sayısı); süreden önce söylenir.
    tempo: tempo düşüşü cümlesi; fren_ses: fren alışkanlığı cümlesi (ikisi de odaktan önce gelir)."""
    parcalar = [sure_yorumu(lap_ms, best_before, problem)]
    if sira:
        parcalar.insert(0, f"{sira[0]}. sıradasın.")
    krit = kritikler(yakit_tur, kalan_tur, lastik, list(teker_tekrar), revlim_s, manuel, pit_sn, strateji_ses,
                     hava_ses)
    yaris_kritik = bool(krit and (krit[0].startswith("Yakıt") or krit[0] == strateji_ses))
    ek = None
    if ayar_ses and not yaris_kritik:
        ek = ayar_ses           # sürerken hemen yapılabilecek ayar (çekiş kontrolü, fren dengesi)
    elif krit:
        ek = krit[0]
    elif tempo:
        ek = tempo
    if ek:
        parcalar.append(ek)
    if not problem and not yaris_kritik and tavsiye:     # tavsiye=False: yarışta viraj tavsiyesi okunmaz
        n = len(gecmis or ())
        if fren_ses:      # fren alışkanlığı (iki turdur aynı virajda aynı yönde) önce gelir
            o = fren_ses
            if soylenen is not None:
                soylenen += [int(x) for x in re.findall(r"Viraj (\d+)", fren_ses)[:1]]
        else:
            o = odak(cmp_res, manuel, ikinci=not ek, n=n, onemli=onemli, soylenen=soylenen, rekor=rekor)
        if duzeltilen:
            parcalar.append(f"Viraj {virajlar_metni(list(duzeltilen)[:3])} düzeldi, aferin.")
        if o:
            parcalar.append(o)
    return " ".join(parcalar)
