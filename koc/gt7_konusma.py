# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Koçun sesli cümleleri
Kullanıcı gerçek oyunda denedi: "koç çok konuşuyor, ne yaptığımı özetlemesi bir anlam ifade etmiyor;
doğru ve yanlış yaptığımı söyleyip tavsiye versin, daha insancıl konuşsun, aynı şeyi tekrarlamasın."
Bu yüzden:
- Her cümle bir TAVSİYE taşır ("frene biraz daha geç bas"), ölçüm jargonu yok ("ortada hızı taşıdın" gibi).
- Aynı şey için birkaç farklı söyleyiş var; sırayla kullanılır (hep aynı cümle duyulmaz).
- Kısaltma yok (TCS -> çekiş kontrolü): ses motoru kısaltmaları harf harf okuyordu.
Kodlar gt7_kopru.compare ve gt7_ipucu'ndaki sorun kodlarıdır.
"""
import re

# Virajdan ÖNCE söylenen tavsiye (emir kipi, kısa)
TAVSIYE = {
    "fren_erken": ("frene biraz daha geç bas", "bu sefer frene daha geç bas", "freni biraz geciktir"),
    "fren_gec": ("frene biraz daha erken bas", "bu sefer frene erken bas"),
    "iz_freni": ("freni birden bırakma, dönerken yavaşça bırak", "freni dönerken yavaş yavaş bırak"),
    "orta_yavas": ("virajın içinde bu kadar yavaşlama", "viraj içinde hızını koru"),
    "bosta": ("frenden kalkınca hemen gaza bas", "frenle gaz arasında bekleme"),
    "gaz_gec": ("çıkışta gaza daha erken bas", "virajdan çıkarken gaza erken dön"),
    "cikis_yavas": ("çıkışta gazı daha erken aç", "virajdan daha hızlı çık, gazı erken aç"),
    "pompa": ("çıkışta gazı tek seferde aç",),
    "fren_bas": ("frene ilk anda sert bas",),
    "duzluk": ("düzlükte gazı kesme",),
    "direksiyon": ("viraja biraz yavaş gir, direksiyonu az çevir",),
    "direksiyon_gec": ("dönüşe biraz daha erken başla", "direksiyonu biraz daha erken çevir"),
    # Teker kilitlenmesi
    "kilit": ("frene biraz daha yumuşak bas", "freni bu kadar sert basma, tekerler kilitleniyor",
              "frene yumuşak bas, sonra yavaş yavaş bırak"),
}
# Fren bipi açıkken fren zamanlaması: bip zaten en iyi fren anında çalıyor
BIP_TAVSIYE = {
    "fren_erken": ("üçüncü sesi bekle, erken basma", "frene basmak için üçüncü sesi bekle"),
    "fren_gec": ("üçüncü seste hemen frene bas", "üçüncü seste gecikme, hemen bas"),
}
# Tur sonunda söylenen virajın hatırlatması. "Unutma / hatırla" denmez: bir mühendisin telsizde diyeceği gibi, virajın adıyla başlayan kısa cümle.
# {no} viraj numarası, {t} tavsiye ("frene biraz daha geç bas").
HATIRLATMA = (
    "Viraj {no} geliyor, {t}.",
    "Şimdi Viraj {no}: {t}.",
    "Viraj {no} yaklaşıyor, {t}.",
    "Sıra Viraj {no}'de, {t}.",
    "Viraj {no} için konuşmuştuk, {t}.",
)
# Virajdan SONRA: ne yaptın (geçmiş zaman, kısa) + bir dahaki sefer ne yap
HATA = {
    "fren_erken": "frene erken bastın", "fren_gec": "frene geç kaldın",
    "iz_freni": "freni birden bıraktın", "orta_yavas": "virajın içinde fazla yavaşladın",
    "bosta": "frenle gaz arasında bekledin", "gaz_gec": "gaza geç bastın",
    "cikis_yavas": "virajdan yavaş çıktın", "kilit": "tekerleri kilitledin",
}
DUZELT = {
    "fren_erken": "bir dahakine daha geç bas", "fren_gec": "bir dahakine daha erken bas",
    "iz_freni": "dönerken yavaşça bırak", "orta_yavas": "hızını biraz daha koru",
    "bosta": "frenden kalkınca hemen gaza geç", "gaz_gec": "bir dahakine daha erken bas",
    "cikis_yavas": "gazı daha erken aç", "kilit": "frene daha yumuşak bas",
}
# Söylenen sorun hâlâ sürüyor
YINE = {
    "fren_erken": ("fren hâlâ erken", "yine erken fren yaptın"),
    "fren_gec": ("fren hâlâ geç", "yine frene geç kaldın"),
    "iz_freni": ("freni yine birden bıraktın",),
    "cizgi": ("çizgin yine kaydı",),
    "orta_yavas": ("viraj içinde yine fazla yavaşladın", "viraj içinde hâlâ yavaşsın"),
    "bosta": ("yine frenle gaz arasında bekledin",),
    "gaz_gec": ("gaza yine geç bastın", "gaz hâlâ geç"),
    "cikis_yavas": ("çıkışın hâlâ yavaş", "virajdan yine yavaş çıktın"),
}
# Söylenen sorun düzeldi (övgü)
DUZELDI = {
    "fren_erken": "fren noktan şimdi iyi", "fren_gec": "fren noktan şimdi iyi",
    "iz_freni": "freni güzel bıraktın", "cizgi": "çizgin şimdi iyi",
    "orta_yavas": "viraj içi hızın şimdi iyi", "bosta": "gaza geçişin iyiydi",
    "gaz_gec": "gaza tam zamanında bastın", "cikis_yavas": "çıkışın düzeldi",
    "vites": "vites şimdi doğru",
}
OVGU = ("böyle devam et", "aynen böyle", "bunu koru")
# İnceleme ekranı (16 Kasım 2026): sorun neden zaman kaybettirdi (tam cümle) ve hangi tekniğe girer
NEDEN = {
    "fren_erken": "Viraja gereğinden yavaş girdin; düzlüğün sonunu boşa harcadın.",
    "fren_gec": "Viraja fazla hızlı girdin; virajın içinde hız kaybettin ve çıkış gecikti.",
    "iz_freni": "Frenin erken bitince araba dönüşe hazır olmadı; virajın ortasında hız kaybettin.",
    "kilit": "Kilitlenen teker yolu tutmaz; fren mesafesi uzar ve araba dışarı kayar.",
    "fren_bas": "Frenin başında yeterince sert basmadın; yavaşlaman uzun sürdü.",
    "cizgi": "Çizgin kaydı; virajı daha dar bir yayla dönmek zorunda kaldın.",
    "orta_yavas": "Virajın en yavaş noktasında gereğinden fazla yavaşladın.",
    "bosta": "Frenle gaz arasında boşta kaldın; araba bu sürede hızlanmadı.",
    "gaz_gec": "Gaza geç bastın; çıkış hızın düştü ve düzlük boyunca bu fark sürdü.",
    "cikis_yavas": "Virajdan yavaş çıktın; sonraki düzlüğün tamamında zaman kaybettin.",
    "pompa": "Gazı açıp kapadın; araba dengesini kaybetti ve çekiş azaldı.",
    "duzluk": "Düzlükte gazı kestin; burada tam gazda kalmak gerekiyordu.",
    "direksiyon": "Direksiyonu fazla çevirdin; ön tekerler kaydı ve araba yavaşladı.",
    "direksiyon_gec": "Direksiyonun en çok çevrildiği ana geç ulaştın; dönüş ve gaza geçiş gecikti.",
    "vites": "Bu virajda farklı viteste kaldın; motor en verimli devrinde değildi.",
}
TEKNIK = {"fren_erken": "fren", "fren_gec": "fren", "iz_freni": "fren", "kilit": "fren", "fren_bas": "fren",
          "cizgi": "cizgi", "orta_yavas": "cizgi", "bosta": "gaz", "gaz_gec": "gaz", "cikis_yavas": "gaz",
          "pompa": "gaz", "duzluk": "gaz", "direksiyon": "direksiyon", "direksiyon_gec": "direksiyon"}
TEKNIK_ADI = {"fren": "Fren", "cizgi": "Çizgi", "gaz": "Gaz", "direksiyon": "Direksiyon", "diger": "Diğer"}
# Söylenmemiş bir virajı belirgin iyi geçtin: neden iyiydi
IYI = {
    "fren_gec_k": "geç fren çok iyiydi", "orta_hizli": "viraj içi hızın çok iyiydi",
    "gaz_erken": "gaza erken bastın, çok iyi", "cikis_hizli": "çıkışın çok iyiydi",
}
YAN_EKLERI = {"sol": ("soldan", "solda"), "sağ": ("sağdan", "sağda")}
YERDE = {"giris": "girişte", "tepe": "tepe noktasında", "cikis": "çıkışta"}


def sec(liste, n=0):
    """Aynı anlamdaki söyleyişlerden sıradakini seçer (hep aynı cümle duyulmasın)."""
    return liste[n % len(liste)]


def _karsi(yan):
    return "sol" if yan == "sağ" else "sağ"


def cizgi_tavsiye(nokta, yan):
    """yan: sürücünün fazla kaldığı taraf ("sağ"/"sol"), nokta: giris/tepe/cikis."""
    dan, da = YAN_EKLERI[_karsi(yan)]
    if nokta == "giris":
        return f"viraja biraz daha {dan} gir"
    if nokta == "cikis":
        return f"çıkışta biraz daha {da} kal"
    return f"tepe noktasında biraz daha {dan} geç"


def cizgi_hata(nokta, yan):
    return f"{YERDE.get(nokta, 'tepe noktasında')} fazla {YAN_EKLERI[yan][1]}ydın"


def tavsiye(i, n=0):
    """Bir sorunun (compare'deki issue) virajdan önce söylenecek kısa tavsiyesi."""
    kod = i["kod"]
    if kod in TAVSIYE:
        return sec(TAVSIYE[kod], n)
    if kod == "cizgi" and i.get("yan"):
        return cizgi_tavsiye(i.get("nokta"), i["yan"])
    return i.get("ses") or i.get("parca") or ""      # vites: "üçüncü vitese düş"


def kod_tavsiye(kod, n=0, yedek=None):
    """Sadece kodu bilinen sorun (geçen seanstan saklanan) için tavsiye."""
    return sec(TAVSIYE[kod], n) if kod in TAVSIYE else yedek


def hata_ve_tavsiye(kod, nokta=None, yan=None):
    """Viraj çıkışında: (ne yaptın, bir dahakine ne yap). Bilinmeyen kodda (None, None)."""
    if kod == "cizgi" and yan:
        return cizgi_hata(nokta, yan), f"biraz daha {YAN_EKLERI[_karsi(yan)][1]} kal"
    return HATA.get(kod), DUZELT.get(kod)


def parantezsiz(metin):
    """Ekran notunu sese uygun kısaltır: parantez içleri (ayrıntı sayıları) okunmaz."""
    return re.sub(r"\s*\([^)]*\)", "", metin or "").strip()


# Ses motoru kısaltmaları harf harf okuyor ("te ce se"): okunmadan önce açılır.
_KISALTMA = (
    (r"\bTCS'(?:y[iı]|yi)", "çekiş kontrolünü"), (r"\bTCS\b", "çekiş kontrolü"),
    (r"\bLSD\b", "diferansiyel"), (r"\bASM\b", "denge kontrolü"), (r"\bABS\b", "a be se"),
    (r"°C", " derece"), (r"%(\d)", r"yüzde \1"), ("→", ","),
    # Cümle sonundaki "al." ses motorunca harf harf okunuyordu (gerçek oyunda duyuldu)
    (r"\bal([.!])", r"almalısın\1"),
)


def acik_yaz(metin):
    """Sesli okunacak metindeki kısaltmaları ve işaretleri açar (ekran metnine dokunulmaz)."""
    if not metin:
        return metin
    for kalip, yerine in _KISALTMA:
        metin = re.sub(kalip, yerine, metin)
    return metin
