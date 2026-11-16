# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Otomatik pist tanıma
Telemetride pist bilgisi yok. Araba sürerken konumu (x, z) pist kütüphanesindeki
çizgilerle karşılaştırılır:
- çizgiden uzak kalan nokta sayısı artan pist elenir,
- ters yönde gidilen pist elenir (ileri / ters düzen ayrılır),
- tek pist kalınca o pist seçilir,
- kısa düzen uzun düzenin içindeyse (ör. Brands Hatch Indy / GP): bir tur sürülünce
  çizgisinin tamamı üzerinden geçilmiş olan düzenler kalır (gerekirse 2 tur beklenir),
- bunlar aynı şekildeyse (ör. şikanlı / şikansız) çizgiye ortalama en yakın olan seçilir.
Fikir: vthinsel/GT7Tracks (konumdan pist tahmini). Oradaki yapay zekâ modeli yerine
ek paket gerektirmeyen basit bir mesafe hesabı kullanılır.
"""
import math

ADIM_M = 20          # bu kadar metrede bir nokta alınır (pist çizgilerinin nokta aralığı)
YAKIN_M = 50         # çizgiye bundan yakınsa pistin üzerinde sayılır
EN_AZ_M = 800        # bu kadar sürmeden karar verilmez
ISINMA = 5           # her pist için bu kadar uzak nokta her zaman hoş görülür (pit çıkışı vb.)
UZAK_ORAN = 0.15     # noktaların bundan fazlası çizgiden uzaksa pist elenir
TERS_ORAN = 0.30     # noktaların bundan fazlasında ters yöndeysen pist elenir
KAPSAM = 0.9         # bir tur sonunda çizginin bu kadarından geçildiyse o düzen sürülmüş sayılır
SICRAMA_M = 300      # iki nokta arası bundan uzaksa (menü / yeni seans) baştan başlanır


class Aday:
    def __init__(self, t):
        self.t = t
        self.path = t["path"]
        xs = [p[0] for p in self.path]
        zs = [p[1] for p in self.path]
        self.kutu = (min(xs) - YAKIN_M, max(xs) + YAKIN_M, min(zs) - YAKIN_M, max(zs) + YAKIN_M)
        self.sifirla()

    def sifirla(self):
        self.uzak = 0
        self.ters = 0
        self.yonlu = 0
        self.toplam = 0
        self.mesafe = 0.0
        self.gorulen = set()    # üzerinden geçilen çizgi noktaları

    def kapsam(self):
        return len(self.gorulen) / len(self.path)

    def ekle(self, x, z, yon):
        """Bir nokta ekler; elenmesi gerekiyorsa False döndürür."""
        self.toplam += 1
        x0, x1, z0, z1 = self.kutu
        if not (x0 <= x <= x1 and z0 <= z <= z1):
            d, i = YAKIN_M + 1, None
        else:
            i = min(range(len(self.path)),
                    key=lambda k: (self.path[k][0] - x) ** 2 + (self.path[k][1] - z) ** 2)
            d = math.hypot(self.path[i][0] - x, self.path[i][1] - z)
        if d > YAKIN_M:
            self.uzak += 1
            self.mesafe += YAKIN_M
        else:
            self.mesafe += d
            n = len(self.path)
            self.gorulen.update(((i - 1) % n, i, (i + 1) % n))
            if yon is not None:
                a, b = self.path[i], self.path[(i + 1) % len(self.path)]
                px, pz = b[0] - a[0], b[1] - a[1]
                if px or pz:
                    self.yonlu += 1
                    if px * yon[0] + pz * yon[1] < 0:
                        self.ters += 1
        if self.uzak > ISINMA + UZAK_ORAN * self.toplam:
            return False
        if self.ters > ISINMA + TERS_ORAN * self.yonlu:
            return False
        return True

    def ortalama(self):
        return self.mesafe / max(1, self.toplam)


class PistTanima:
    """ekle(x, z) her pakette çağrılabilir; pist bulununca o pisti (katalog kaydı) döndürür."""

    def __init__(self, catalog):
        # Kısmi çizgilerin sonu eksik: orada sürünce yanlışlıkla elenir, bu yüzden katılmaz
        self.hepsi = [Aday(t) for t in catalog if t.get("path") and not t.get("partial")]
        self.sifirla()

    def sifirla(self):
        for a in self.hepsi:
            a.sifirla()
        self.adaylar = list(self.hepsi)
        self.son = None
        self.yol = 0.0

    def ekle(self, x, z):
        if self.son is not None:
            d = math.hypot(x - self.son[0], z - self.son[1])
            if d > SICRAMA_M:
                self.sifirla()
            elif d < ADIM_M:
                return None
        yon = None
        if self.son is not None:
            yon = (x - self.son[0], z - self.son[1])
            self.yol += math.hypot(*yon)
        self.son = (x, z)
        self.adaylar = [a for a in self.adaylar if a.ekle(x, z, yon)]
        if not self.adaylar:          # hiçbiri uymadı (kütüphanede olmayan pist ya da menü): baştan
            self.sifirla()
            return None
        return self.karar()

    def karar(self):
        if self.yol < EN_AZ_M:
            return None
        if len(self.adaylar) == 1:
            return self.adaylar[0].t
        # Bir pist daha kaldıysa: en az bir tur sür, çizgisinin tamamından geçilenler kalsın
        if self.yol < 1.05 * min(a.t["length"] for a in self.adaylar):
            return None
        tam = [a for a in self.adaylar if a.kapsam() >= KAPSAM]
        if not tam or self.yol < 1.05 * max(a.t["length"] for a in tam):
            return None
        # Daha uzun bir düzen hâlâ olabilir (kısa düzen onun içinde): ya onun da bir turu
        # sürülsün ya da kısa düzen iki kez dönülsün
        if self.yol < min(1.05 * max(a.t["length"] for a in self.adaylar),
                          2.1 * max(a.t["length"] for a in tam)):
            return None
        # Aynı şekilli düzenler: çizgiye ortalama en yakın olan
        return min(tam, key=lambda a: a.ortalama()).t
