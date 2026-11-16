# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Yarış mühendisi (sürerken kısa telsiz anonsları)
Cümleler gt7-datalogger'ın sesli uyarılarının Türkçesinden, eşikler gt7-datalogger
belgesinden ("Sesli uyarı ilkeleri"): kalıcılık + histerezis + bekleme süresi.
- Motor: su sıcaklığı (110/106, kritik 120/116 °C), yağ sıcaklığı (130/126, kritik 140/136 °C),
  yağ basıncı (< 2,0 bar, 2000 devir üstü, 1,5 sn; 2,4'te temizlenir)
- Lastik: herhangi biri 110 °C (104'te temizlenir); ön/arka ya da sol/sağ farkı 15 °C (10'da temizlenir)
- Lastik (9 Kasım 2026): soğuk lastik (ortalama ≤ 55 °C, 40 km/s üstünde 8 sn; 65'te temizlenir),
  lastikler hızla soğuyor = pist ıslanıyor olabilir (80 km/s üstünde son ~20 sn'nin ortalaması son ~3 dk'nınkinden
  10 °C düşük, 10 sn; 4'te temizlenir; 2 dk hızlı sürüş görülmeden ve lastikler 60 °C'yi bulmadan karar yok).
  Telemetride hava / yağmur bilgisi yok: bu bir tahmin. Eşikler tahmini, gerçek oyunda denenmedi.
- Yarış: sıra değişimi (3 sn sabit kalınca), yarının yarısı, son tur
Zamanlar paket saatiyle ölçülür (duraklatma süre saymaz). Pistte değilken ya da duraklatılmışken susar.
"""

BEKLEME_S = 600        # aynı konu (aynı şiddette) bu kadar saniye tekrar söylenmez
SICAKLIK_KALICI_S = 5.0
YAG_BASINC_KALICI_S = 1.5
DENGE_KALICI_S = 10.0
SIRA_SABIT_S = 3.0     # sıra bu kadar saniye değişmeden kalınca söylenir
SIRA_ARA_S = 8.0       # iki sıra anonsu arasında en az bu kadar saniye

# (anahtar, tetik, temizlenme, şiddet, cümle)
SU = [("su_kritik", 120, 116, "kritik", "Su sıcaklığı kritik!"),
      ("su_yuksek", 110, 106, "yuksek", "Su sıcaklığı yüksek.")]
YAG = [("yag_kritik", 140, 136, "kritik", "Yağ sıcaklığı kritik!"),
       ("yag_yuksek", 130, 126, "yuksek", "Yağ sıcaklığı yüksek.")]
LASTIK_YUKSEK = (110, 104)
LASTIK_SOGUK = (55, 65)        # 4 lastiğin ortalaması (°C): tetik, temizlenme
SOGUK_KALICI_S = 8.0
# Lastikler ısındı: soğuk başlayan lastikler ısınınca bir kez söylenir
ISINDI_SOGUK = 60              # ortalama bunun altında görüldüyse "soğuk başladı" sayılır (°C)
ISINDI_SICAK = 70              # ...sonra bu kadarı (ideal aralığın altı) üst üste ISINDI_KALICI_S görülünce
ISINDI_KALICI_S = 5.0
SOGUK_MIN_KMH = 40
ISLAK_FARK = (10, 4)           # uzun ortalama − kısa ortalama (°C): tetik, temizlenme
ISLAK_KALICI_S = 10.0
ISLAK_MIN_KMH = 80             # sadece hızlı sürüşte ölçülür (pit, savrulma, yavaş tur karışmasın)
ISLAK_HAZIR_S = 120            # bu kadar saniye hızlı sürüş görülmeden karar verilmez
ISLAK_MIN_SICAK = 60           # uzun ortalama bunun altındaysa (lastikler zaten soğuk) karar verilmez
TAU_KISA, TAU_UZUN = 20.0, 180.0
DURMA_KMH, DURMA_S = 30, 10.0  # bu kadar süre bu hızın altında kalınca (pit, durma) ortalamalar sıfırlanır
TASMA_SUSMA_S = 60.0           # teker çime/kuma taşınca bu kadar saniye ıslak kararı verilmez (ortalamalar baştan)
GEVSEK = frozenset("DGSs")     # toprak, çim, kum, kar (C biçimi teker zemini)
ISLAK_CUMLE = "Lastikler soğuyor, pist ıslanıyor olabilir. Fren noktalarını erkene al."
DENGE = (15, 10)
YAG_BASINC = (2.0, 2.4, 2000)   # (tetik bar, temizlenme bar, en az devir)


class _Esik:
    """Kalıcılık + histerezis: değer `sure` boyunca tetik eşiğinin ötesinde kalınca bir kez True döner;
    temizlenme eşiğine dönünce yeniden kurulur."""

    def __init__(self, tetik, temiz, sure, yukari=True):
        self.tetik, self.temiz, self.sure, self.yukari = tetik, temiz, sure, yukari
        self.aktif = False
        self.bas = None

    def guncelle(self, t, v):
        if v is None:
            self.bas = None
            return False
        ustunde = v >= self.tetik if self.yukari else v <= self.tetik
        temiz = v < self.temiz if self.yukari else v > self.temiz
        if self.aktif:
            if temiz:
                self.aktif = False
            return False
        if not ustunde:
            self.bas = None
            return False
        if self.bas is None:
            self.bas = t
        if t - self.bas >= self.sure:
            self.aktif = True
            return True
        return False


class Muhendis:
    """Her pakette çağrılır; söylenecek anonsları [(metin, kritik mi)] olarak döndürür."""

    def __init__(self):
        self.su = [(_Esik(a, b, SICAKLIK_KALICI_S), k, s, m) for k, a, b, s, m in SU]
        self.yag = [(_Esik(a, b, SICAKLIK_KALICI_S), k, s, m) for k, a, b, s, m in YAG]
        self.basinc = _Esik(YAG_BASINC[0], YAG_BASINC[1], YAG_BASINC_KALICI_S, yukari=False)
        self.basinc_gecerli = False     # bazı arabalar basınç göndermiyor: önce normal değer görülmeli
        self.lastik = _Esik(*LASTIK_YUKSEK, SICAKLIK_KALICI_S)
        self.denge = {y: _Esik(*DENGE, DENGE_KALICI_S) for y in ("on", "arka", "sol", "sag")}
        self.soguk = _Esik(*LASTIK_SOGUK, SOGUK_KALICI_S, yukari=False)
        self.soguktu = False            # lastikler bu sürüşte soğuk görüldü (ısınınca bir kez söylenir)
        self.isindi_bas = None
        self.islak = _Esik(*ISLAK_FARK, ISLAK_KALICI_S)
        self._ort_sifirla()
        self.yavas_bas = None
        self.tasma_t = None             # son kez teker çime/kuma taştığı an (paket saati)
        self.islak_olay = False         # ıslak pist şüphesi söylendi (koç okur ve sıfırlar)
        self.son_soylenen = {}          # anahtar -> paket saati
        self._yaris_sifirla(None)

    def _yaris_sifirla(self, toplam):
        self.toplam = toplam
        self.son_tur_dedi = False
        self.yari_dedi = False
        self.onceki_tur = 0
        self.sira_duyurulan = None
        self.sira_aday = None
        self.sira_aday_t = 0.0
        self.sira_son_t = -1e9

    def _soyle(self, out, t, anahtar, metin, kritik=False):
        son = self.son_soylenen.get(anahtar)
        if son is not None and t - son < BEKLEME_S:
            return False
        self.son_soylenen[anahtar] = t
        out.append((metin, kritik))
        return True

    def _ort_sifirla(self):
        self.ort_kisa = self.ort_uzun = self.ort_t = None
        self.ort_sure = 0.0

    def guncelle(self, t, pkt, on_track, paused):
        out = []
        if not on_track or paused:
            return out
        self._motor(t, pkt, out)
        self._lastikler(t, pkt, out)
        self._yaris(t, pkt, out)
        return out

    # ---------------- Motor ----------------
    def _sicaklik(self, t, v, liste, out):
        v = v if v and v > 0 else None
        for esik, anahtar, siddet, metin in liste:   # kritik önce: yüksek ile aynı anda gelirse sadece kritik
            if esik.guncelle(t, v):
                self._soyle(out, t, anahtar, metin, siddet == "kritik")
                if siddet == "kritik":
                    for e, *_ in liste:
                        e.aktif = True               # "yüksek" ayrıca söylenmesin
                break

    def _motor(self, t, pkt, out):
        self._sicaklik(t, pkt.water_temp, self.su, out)
        self._sicaklik(t, pkt.oil_temp, self.yag, out)
        p = pkt.oil_pressure
        if p and p >= YAG_BASINC[1]:
            self.basinc_gecerli = True
        if self.basinc_gecerli and p is not None:
            if pkt.engine_rpm > YAG_BASINC[2]:
                if self.basinc.guncelle(t, p):
                    self._soyle(out, t, "yag_basinci", "Yağ basıncı düşük!", True)
            elif not self.basinc.aktif:
                self.basinc.bas = None

    # ---------------- Lastikler ----------------
    def _lastikler(self, t, pkt, out):
        fl, fr, rl, rr = pkt.tire_temp_fl, pkt.tire_temp_fr, pkt.tire_temp_rl, pkt.tire_temp_rr
        if min(fl, fr, rl, rr) <= 0:
            return
        if self.lastik.guncelle(t, max(fl, fr, rl, rr)):
            self._soyle(out, t, "lastik_yuksek", "Lastik sıcaklıkları yüksek.")
        self._soguk_islak(t, pkt, (fl + fr + rl + rr) / 4, out)
        on, arka = (fl + fr) / 2, (rl + rr) / 2
        sol, sag = (fl + rl) / 2, (fr + rr) / 2
        farklar = {"arka": (arka - on, "Arka lastikler öndekilerden {} derece daha sıcak."),
                   "on": (on - arka, "Ön lastikler arkadakilerden {} derece daha sıcak."),
                   "sol": (sol - sag, "Sol lastikler sağdakilerden {} derece daha sıcak."),
                   "sag": (sag - sol, "Sağ lastikler soldakilerden {} derece daha sıcak.")}
        for y, (fark, metin) in farklar.items():
            if self.denge[y].guncelle(t, fark):
                self._soyle(out, t, "denge_" + y, metin.format(round(fark)))

    def _soguk_islak(self, t, pkt, ort, out):
        kmh = (getattr(pkt, "speed_mps", 0) or 0) * 3.6
        # Soğuk lastik (seans başı, pitten çıkış)
        if kmh >= SOGUK_MIN_KMH:
            if self.soguk.guncelle(t, ort):
                self._soyle(out, t, "lastik_soguk", "Lastikler soğuk. İlk virajlarda frene erken bas.")
            if ort < ISINDI_SOGUK:
                self.soguktu, self.isindi_bas = True, None
            elif self.soguktu and ort >= ISINDI_SICAK:
                if self.isindi_bas is None:
                    self.isindi_bas = t
                elif t - self.isindi_bas >= ISINDI_KALICI_S:
                    self.soguktu, self.isindi_bas = False, None
                    self._soyle(out, t, "lastik_isindi", "Lastikler ısındı, artık araca güvenebilirsin.")
            else:
                self.isindi_bas = None
        elif not self.soguk.aktif:
            self.soguk.bas = None
        # Durunca (pit, savrulma) ortalamalar baştan: yeni lastik soğuk gelir, ıslak sanılmasın
        if kmh < DURMA_KMH:
            if self.yavas_bas is None:
                self.yavas_bas = t
            elif t - self.yavas_bas >= DURMA_S:
                self._ort_sifirla()
        else:
            self.yavas_bas = None
        # Teker çime/kuma taştı (14 Kasım 2026: 2 teker çime çıkınca "pist ıslanıyor" denmişti): lastik
        # sıcaklığı bu yüzden düşer, yağmurla karışmasın. Ortalamalar baştan, bir süre karar verilmez.
        zemin = getattr(pkt, "surface_types", None) or ""
        if any(ch in GEVSEK for ch in zemin):
            self.tasma_t = t
        if self.tasma_t is not None and t - self.tasma_t < TASMA_SUSMA_S:
            self._ort_sifirla()
            if not self.islak.aktif:
                self.islak.bas = None
            return
        if kmh < ISLAK_MIN_KMH:
            self.ort_t = None
            if not self.islak.aktif:
                self.islak.bas = None
            return
        dt = 0.0 if self.ort_t is None else max(0.0, min(0.5, t - self.ort_t))
        self.ort_t = t
        if self.ort_kisa is None:
            self.ort_kisa = self.ort_uzun = ort
            return
        self.ort_kisa += (ort - self.ort_kisa) * min(1.0, dt / TAU_KISA)
        self.ort_uzun += (ort - self.ort_uzun) * min(1.0, dt / TAU_UZUN)
        self.ort_sure += dt
        if self.ort_sure < ISLAK_HAZIR_S or self.ort_uzun < ISLAK_MIN_SICAK:
            return
        if self.islak.guncelle(t, self.ort_uzun - self.ort_kisa):
            if self._soyle(out, t, "islak", ISLAK_CUMLE):
                self.islak_olay = True

    # ---------------- Yarış ----------------
    def _yaris(self, t, pkt, out):
        toplam, tur = pkt.total_laps, pkt.current_lap
        if toplam <= 0:
            if self.toplam:
                self._yaris_sifirla(None)
            return
        if toplam != self.toplam or tur < self.onceki_tur:   # yeni yarış
            self._yaris_sifirla(toplam)
        self.onceki_tur = tur
        if tur >= 1:
            if toplam >= 2 and tur == toplam and not self.son_tur_dedi:
                self.son_tur_dedi = True
                out.append(("Son tur!", False))
            elif toplam >= 4 and tur < toplam and (tur - 1) * 2 >= toplam and not self.yari_dedi:
                self.yari_dedi = True
                out.append(("Yarışın yarısı geride kaldı.", False))
        sira, arac = pkt.race_position, pkt.total_positions
        if arac < 2 or sira < 1:
            return
        if self.sira_duyurulan is None:
            self.sira_duyurulan = sira
            self.sira_aday = sira
            return
        if sira != self.sira_aday:
            self.sira_aday, self.sira_aday_t = sira, t
            return
        if sira != self.sira_duyurulan and t - self.sira_aday_t >= SIRA_SABIT_S \
                and t - self.sira_son_t >= SIRA_ARA_S:
            fark = self.sira_duyurulan - sira
            kac = "Bir sıra" if abs(fark) == 1 else f"{abs(fark)} sıra"
            fiil = "yükseldin" if fark > 0 else "kaybettin"
            out.append((f"{kac} {fiil}. Şimdi {sira}. sıradasın.", False))
            self.sira_duyurulan = sira
            self.sira_son_t = t
