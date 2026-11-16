# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Araç ayarı önerileri
Turdaki kilitlenme, patinaj ve gövde kaymasından (önden / arkadan kayma), son vitesin
uzunluğundan (devir sınırı / hiç çıkılmayan vites) ve yerden yükseklikten (dibe oturma) desen çıkarır.
Son 3 turun en az 2'sinde tekrar eden desen için öneri verir:
- Sürerken hemen yapılabilenler (GT7'de yarış içi menü: TCS, fren dengesi): tur sonunda sesli söylenir.
- Garaj ayarları (LSD, denge çubukları, yaylar...): arayüzdeki "Öneriler" bölümünde birikir.
Eşikler tahminidir; gerçek sürüş verisiyle ayarlanacak.
"""
from gt7_cekis import ADLAR, dagilim_cumlesi
from gt7_kopru import de, detect_events, place_corners, to_samples, turn_side

PENCERE = 3           # son kaç tura bakılır
TEKRAR = 2            # desen bu kadar turda görülürse öneri olur
KAYMA_DERECE = 6.0    # gövde kayması (burun viraja doğru) bunu geçerse "arkadan kayma" (tahmini)
KAYMA_ORNEK = 12      # ... en az bu kadar örnek (0,2 sn) sürmeli
ONDEN_ORAN = 0.85     # viraj, aracın bu turdaki normal dönüşünün (viraj oranlarının ortancası) bu kadarının
                      # altında dönüyorsa "önden kayma" (sadece C biçimi). Mutlak oran gerçek veride her virajda
                      # 0,8'in altında çıktı (4 Kasım 2026, yanlış alarm), bu yüzden araç kendisiyle karşılaştırılır.
ONDEN_MIN_HIZ = 60    # km/s
EVENT_CORNER_M = 150
SON_VITES_SINIR_S = 1.0   # son viteste devir sınırında bu kadar saniyeden fazla = son vites kısa
UZUN_VITES_HIZ = 150      # km/s: turda bu hızı geçip son vitese hiç çıkılmadıysa = son vites uzun
DIP_ORAN = 0.35           # yerden yükseklik turun ortancasının bu oranının altına inerse "dibe oturma"
DIP_ORNEK = 3             # ... en az bu kadar örnek sürerse bir olay
DIP_OLAY = 2              # turda bu kadar olay olursa desen

# kod: (başlık, sürerken yapılacak ayar ya da None, garaj ayarı ya da None, sürüş tavsiyesi)
KURALLAR = {
    "on_kilit": ("Frende ön tekerler kilitleniyor",
                 "Fren dengesini bir kademe arkaya al (eksi yönüne).",
                 None,
                 "Frene ilk basışı biraz yumuşat, viraja yaklaştıkça freni azalt."),
    "arka_kilit": ("Frende arka tekerler kilitleniyor",
                   "Fren dengesini bir kademe öne al (artı yönüne).",
                   "LSD fren (yavaşlama) değerini biraz artır.",
                   "Vitesi çok erken küçültme, frende arabayı düz tut."),
    "arka_patinaj": ("Çıkışta arka tekerler patinaj yapıyor",
                     "TCS'yi bir kademe artır.",
                     "LSD hızlanma değerini biraz azalt; arka yayları ya da arka denge çubuğunu biraz yumuşat.",
                     "Çıkışta gazı daha kademeli aç, direksiyon düzelirken tam gaza geç."),
    "on_patinaj": ("Çıkışta ön tekerler patinaj yapıyor",
                   "TCS'yi bir kademe artır.",
                   "LSD hızlanma değerini biraz azalt; ön denge çubuğunu ya da ön yayları biraz yumuşat.",
                   "Çıkışta gazı daha kademeli aç, direksiyon düzelirken tam gaza geç."),
    "dort_patinaj": ("Çıkışta dört teker birden patinaj yapıyor",
                     "TCS'yi bir kademe artır.",
                     "Ön ve arka LSD hızlanma değerlerini biraz azalt.",
                     "Çıkışta gazı daha kademeli aç; gerekiyorsa bir üst vitesle çık."),
    "giris_arka": ("Frende / girişte arka kayıyor (arkadan kayma)",
                   "Fren dengesini bir kademe öne al (artı yönüne).",
                   "LSD fren (yavaşlama) değerini artır; arka denge çubuğunu biraz yumuşat.",
                   "Fren bitmeden direksiyonu sert çevirme, freni daha erken bitir."),
    "orta_arka": ("Viraj ortasında arka kayıyor (arkadan kayma)",
                  None,
                  "Arka denge çubuğunu yumuşat ya da ön denge çubuğunu sertleştir; arka kanat/aero varsa biraz artır.",
                  "Viraj ortasında gazı ve direksiyonu ani değiştirme."),
    "cikis_arka": ("Çıkışta gazla arka kayıyor (arkadan kayma)",
                   "TCS'yi bir kademe artır.",
                   "LSD hızlanma değerini azalt; arka yayları biraz yumuşat.",
                   "Gazı direksiyonu açarken kademeli aç."),
    "son_vites_kisa": ("Son vites kısa: düzlükte devir sınırına dayanıyorsun",
                       None,
                       "Şanzımanda en yüksek hızı (son vitesi) biraz uzat.",
                       "Draft (öndeki aracın arkasında) varsa bu normal olabilir."),
    "son_vites_uzun": ("Son vites uzun: en yüksek vitese hiç çıkmıyorsun",
                       None,
                       "Şanzımanda en yüksek hızı biraz kısalt; ara vitesler sıklaşır, çıkışlar güçlenir.",
                       "Manuel vitesteysen en uzun düzlükte vitesi sonuna kadar büyüt."),
    "dibe_oturma": ("Araç yere vuruyor (süspansiyon dibe oturuyor)",
                    None,
                    "Yerden yüksekliği biraz artır ya da yayları biraz sertleştir.",
                    "Kerblere ve tümseklere sert girme."),
    "onden": ("Viraj ortasında burun dışarı kaçıyor (önden kayma)",
              None,
              "Ön denge çubuğunu yumuşat ya da arkayı sertleştir; ön aero varsa biraz artır.",
              "Viraja biraz daha yavaş gir, gazı tepe noktasından sonra aç."),
}
CANLI_KISA = {  # tur sonunda sesli söylenecek kısa hâli (kısaltmasız: ses motoru "TCS"yi harf harf okuyordu)
    "on_kilit": "Ön tekerler frende kilitleniyor. Fren dengesini bir kademe arkaya almalısın.",
    "arka_kilit": "Arka tekerler frende kilitleniyor. Fren dengesini bir kademe öne almalısın.",
    "arka_patinaj": "Çıkışta arka tekerler patinaj yapıyor. Çekiş kontrolünü bir kademe yükselt.",
    "on_patinaj": "Çıkışta ön tekerler patinaj yapıyor. Çekiş kontrolünü bir kademe yükselt.",
    "dort_patinaj": "Çıkışta dört teker patinaj yapıyor. Çekiş kontrolünü bir kademe yükselt.",
    "giris_arka": "Viraja girerken arka kayıyor. Fren dengesini bir kademe öne almalısın.",
    "cikis_arka": "Çıkışta arka kayıyor. Çekiş kontrolünü bir kademe yükselt.",
}
NOT = "Ayar ancak araçta o parça ayarlanabiliyorsa yapılabilir (fren dengesi için fren dengesi kontrolcüsü gerekir)."


# 4 çekerde güç dağılımı (ön:arka) yönü: hangi desende gücü nereye kaydırmalı
DAGILIM_YON = {"on_patinaj": "arkaya", "onden": "arkaya", "arka_patinaj": "one", "cikis_arka": "one"}


def kural_metni(kod, cekis=None, dagilim=None):
    """(başlık, sürerken, garaj, sürüş): çekiş türüne ve güç dağılımına göre uyarlanmış.
    cekis: "arka"/"on"/"4x4"/None, dagilim: 4 çekerde ön payı (ör. 40) ya da None."""
    baslik, canli, garaj, surus = KURALLAR[kod]
    yon = DAGILIM_YON.get(kod)
    if cekis == "4x4" and yon:
        garaj = dagilim_cumlesi(dagilim, yon) + (" Ya da: " + garaj if garaj else "")
    return baslik, canli, garaj, surus


def _yakin_viraj(wins, total, d):
    w = min(wins, key=lambda w: abs(w.apex - d), default=None)
    return w.n if w and abs(w.apex - d) <= EVENT_CORNER_M else None


def tur_desenleri(lap, corners):
    """Bir turdaki desenler: {(kod, viraj_no)}. Viraj bulunamazsa viraj None."""
    s = to_samples(lap)
    out = set()
    if not corners or not s.get("dist"):
        return out
    wins = place_corners(corners, s)
    total = s["dist"][-1]
    # Teker olayları: kilit (fren) ve patinaj (gaz)
    if s.get("slip_fl"):
        for e in detect_events(s):
            if e["type"] not in ("lockup", "wheelspin"):
                continue
            w = set(e["wheels"])
            no = _yakin_viraj(wins, total, (e["start_dist"] + e["end_dist"]) / 2)
            on, arka = bool(w & {"fl", "fr"}), bool(w & {"rl", "rr"})
            if e["type"] == "lockup":
                if on and not arka:
                    out.add(("on_kilit", no))
                elif arka and not on:
                    out.add(("arka_kilit", no))
            elif on and arka:
                out.add(("dort_patinaj", no))
            elif arka:
                out.add(("arka_patinaj", no))
            elif on:
                out.add(("on_patinaj", no))
    # Gövde kayması: burun gidişe göre viraja doğru fazla dönmüşse arka kayıyordur
    slip = s.get("slip_body")
    d, br, th, sp = s["dist"], s.get("brake"), s.get("throttle"), s.get("speed")
    if slip and len(slip) == len(d):
        for w in wins:
            into = 1.0 if turn_side(s, w) == "sag" else -1.0
            faz = {"giris_arka": [], "orta_arka": [], "cikis_arka": []}
            for i in range(len(d)):
                if not (w.entry <= d[i] <= w.exit) or slip[i] is None:
                    continue
                v = slip[i] * into
                if v < KAYMA_DERECE:
                    continue
                if br and br[i] > 10 and d[i] <= w.apex:
                    faz["giris_arka"].append(i)
                elif th and th[i] > 50 and d[i] > w.apex:
                    faz["cikis_arka"].append(i)
                else:
                    faz["orta_arka"].append(i)
            for kod, idx in faz.items():
                if len(idx) >= KAYMA_ORNEK:
                    out.add((kod, w.n))
    # Son vites: devir sınırına dayanma ya da hiç çıkılmayan vites
    top = lap.get("vites_sayisi")
    gear, rev = lap.get("gear"), lap.get("revlim")
    if top and gear and sp:
        if rev and len(rev) == len(gear):
            sinir = sum(1 for g, r in zip(gear, rev) if r and g == top) / 60.0
            if sinir > SON_VITES_SINIR_S:
                out.add(("son_vites_kisa", None))
        if top >= 4 and max(sp) > UZUN_VITES_HIZ and max(g for g in gear if g != 15) < top:
            out.add(("son_vites_uzun", None))
    # Dibe oturma: yerden yükseklik birden çok kez çok düşüyor (tahmini eşik)
    bh = lap.get("body_h")
    if bh and len(bh) == len(d):
        dolu = sorted(v for v in bh if v and v > 0)
        if dolu:
            orta = dolu[len(dolu) // 2]
            olay, run, yer = 0, 0, []
            for i, v in enumerate(bh):
                run = run + 1 if v is not None and 0 < v < DIP_ORAN * orta else 0
                if run == DIP_ORNEK:
                    olay += 1
                    yer.append(_yakin_viraj(wins, total, d[i]))
            if olay >= DIP_OLAY:
                for no in set(yer) or {None}:
                    out.add(("dibe_oturma", no))
    # Önden kayma: sadece C biçiminde (teker açısı ve dingil mesafesi var)
    wa, yaw, wb = s.get("wheel_angle"), s.get("yaw"), lap.get("wheelbase")
    if wa and yaw and wb and sp and None not in wa:
        oranlar = {}
        for w in wins:
            ist, ol = 0.0, 0.0
            for i in range(len(d)):
                if abs(d[i] - w.apex) <= 30 and sp[i] >= ONDEN_MIN_HIZ:
                    k = abs(sp[i] / 3.6 * wa[i] / wb)
                    if k > 0.05:
                        ist += k
                        ol += abs(yaw[i])
            if ist > 1.0:
                oranlar[w.n] = ol / ist
        if len(oranlar) >= 3:
            normal = sorted(oranlar.values())[len(oranlar) // 2]
            dusuk = [n for n, o in oranlar.items() if o < ONDEN_ORAN * normal]
            if len(dusuk) <= len(oranlar) // 2:   # yarısından fazlasıysa ölçüm sorunu, yazma
                for n in dusuk:
                    out.add(("onden", n))
    return out


class AyarKocu:
    """Turlar boyunca desenleri biriktirir, önerileri üretir."""

    def __init__(self):
        self.turlar = []          # her tur için desen kümesi
        self.soylenen = set()     # sesli söylenmiş canlı öneriler (kod)
        self.aktif = set()        # şu an geçerli desenler
        self.oneriler = {}        # kod -> öneri (arayüzdeki "Öneriler" bölümü)

    def tur_ekle(self, desenler, cekis=None, dagilim=None):
        """Turun desenlerini ekler. Döndürür: (ekran satırları, sesli söylenecek kısa cümle ya da None).
        cekis / dagilim: arabanın çekiş türü ve (4 çekerde) güç dağılımı ön payı; öneri metnini uyarlar."""
        self.turlar.append(desenler)
        son = self.turlar[-PENCERE:]
        satirlar, ses = [], None
        aktif = set()
        for kod in KURALLAR:
            kac = sum(1 for t in son if any(k == kod for k, _ in t))
            if kac < TEKRAR:
                continue
            aktif.add(kod)
            virajlar = sorted({v for t in son for k, v in t if k == kod and v is not None})
            baslik, canli, garaj, surus = kural_metni(kod, cekis, dagilim)
            yer = ("Viraj " + ", ".join(str(v) for v in virajlar)) if virajlar else "pistte"
            neden = f"{yer} — son {len(son)} turun {kac}'inde görüldü."
            if cekis in ADLAR and kod.endswith("patinaj"):
                neden += f" Araç {ADLAR[cekis]}."
            self.oneriler[kod] = {"kod": kod, "baslik": baslik, "neden": neden, "surus": surus,
                                  "canli": canli, "garaj": garaj, "tur": len(self.turlar)}
            if kod not in self.aktif:  # ekranda sadece yeni çıkan öneri yazılır, hepsi "Öneriler"de
                satirlar.append(f"Ayar önerisi: {baslik} ({yer}). "
                                + (f"Sürerken: {canli} " if canli else "")
                                + (f"Garajda: {garaj}" if garaj else ""))
            # Aynı ayar (ör. TCS) başka bir desenle zaten söylendiyse tekrar söylenmez
            ayni = any(KURALLAR[k][1] == canli for k in self.soylenen)
            if canli and kod not in self.soylenen and not ayni and ses is None:
                ses = CANLI_KISA.get(kod)
                self.soylenen.add(kod)
            elif kod == "dibe_oturma" and kod not in self.soylenen and ses is None:
                # Garaj ayarı sürerken yapılamaz ama mühendis haber verir (bir kez)
                ses = ("Araba Viraj " + ", ".join(str(v) for v in virajlar[:-1])
                       + (" ve " if len(virajlar) > 1 else "") + de(virajlar[-1]) + " yere sürtüyor."
                       if virajlar else "Araba fren bölgelerinde yere sürtüyor.")
                self.soylenen.add(kod)
        # Desen kaybolduysa (ör. ayar değiştirildi), tekrar ederse yeniden söylenebilir
        self.soylenen &= aktif
        self.aktif = aktif
        return satirlar, ses

    def liste(self):
        """Arayüz için: en yeni önce."""
        return sorted(self.oneriler.values(), key=lambda o: -o["tur"])
