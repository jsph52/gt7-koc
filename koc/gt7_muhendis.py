# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Yarış mühendisi (sürerken kısa telsiz anonsları)
Cümleler gt7-datalogger'ın sesli uyarılarının Türkçesinden, eşikler gt7-datalogger
belgesinden ("Sesli uyarı ilkeleri"): kalıcılık + histerezis + bekleme süresi.
- Motor: su sıcaklığı (110/106, kritik 120/116 °C), yağ sıcaklığı (130/126, kritik 140/136 °C),
  yağ basıncı (< 2,0 bar, 2000 devir üstü, 1,5 sn; 2,4'te temizlenir)
- Lastik: herhangi biri 110 °C (104'te temizlenir); ön/arka ya da sol/sağ farkı 15 °C (10'da temizlenir)
  Lastiklerin ısındığı ya da soğuduğu söylenmez: telemetride lastik türü ve ideal sıcaklık yok.
- Yarış: liderliğe geçince / ilk üçe girince (3 sn sabit kalınca), yarının yarısı, son tur. Diğer sıra
  değişimleri sürerken söylenmez; tur sonu sesinde sıra değiştiyse söylenir (`sira_degisimi`).
Zamanlar paket saatiyle ölçülür (duraklatma süre saymaz). Pistte değilken ya da duraklatılmışken susar.
"""

BEKLEME_S = 600        # aynı konu (aynı şiddette) bu kadar saniye tekrar söylenmez
SICAKLIK_KALICI_S = 5.0
YAG_BASINC_KALICI_S = 1.5
DENGE_KALICI_S = 10.0
SIRA_SABIT_S = 3.0     # sıra bu kadar saniye değişmeden kalınca söylenir
SIRA_ARA_S = 60.0      # iki sıra anonsu ("Lidersin!", "İlk üçtesin.") arasında en az bu kadar saniye

# (anahtar, tetik, temizlenme, şiddet, cümle)
SU = [("su_kritik", 120, 116, "kritik", "Su sıcaklığı kritik!"),
      ("su_yuksek", 110, 106, "yuksek", "Su sıcaklığı yüksek.")]
YAG = [("yag_kritik", 140, 136, "kritik", "Yağ sıcaklığı kritik!"),
       ("yag_yuksek", 130, 126, "yuksek", "Yağ sıcaklığı yüksek.")]
LASTIK_YUKSEK = (110, 104)
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
        self.sira_tur = None            # tur sonu sesinde karşılaştırılan sıra (başlangıç ya da önceki tur sonu)

    def sira_degisimi(self, sira):
        """Tur sonunda: önceki tur sonundan (ya da başlangıçtan) bu yana sıra farkı (+ kazanılan), sonra günceller."""
        onceki, self.sira_tur = self.sira_tur, sira
        if onceki is None or not sira or sira < 1:
            return 0
        return onceki - sira

    def _soyle(self, out, t, anahtar, metin, kritik=False):
        son = self.son_soylenen.get(anahtar)
        if son is not None and t - son < BEKLEME_S:
            return False
        self.son_soylenen[anahtar] = t
        out.append((metin, kritik))
        return True

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
        on, arka = (fl + fr) / 2, (rl + rr) / 2
        sol, sag = (fl + rl) / 2, (fr + rr) / 2
        farklar = {"arka": (arka - on, "Arka lastikler öndekilerden {} derece daha sıcak."),
                   "on": (on - arka, "Ön lastikler arkadakilerden {} derece daha sıcak."),
                   "sol": (sol - sag, "Sol lastikler sağdakilerden {} derece daha sıcak."),
                   "sag": (sag - sol, "Sağ lastikler soldakilerden {} derece daha sıcak.")}
        for y, (fark, metin) in farklar.items():
            if self.denge[y].guncelle(t, fark):
                self._soyle(out, t, "denge_" + y, metin.format(round(fark)))

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
            if self.sira_tur is None:
                self.sira_tur = sira    # başlangıç sırası: ilk tur sonunda buna göre
            return
        if sira != self.sira_aday:
            self.sira_aday, self.sira_aday_t = sira, t
            return
        if sira != self.sira_duyurulan and t - self.sira_aday_t >= SIRA_SABIT_S:
            # Her sıra değişimi söylenmez (çok konuşuyordu): sadece liderliğe geçince ve ilk üçe girince
            onceki, self.sira_duyurulan = self.sira_duyurulan, sira
            if t - self.sira_son_t < SIRA_ARA_S:
                return
            if sira == 1:
                out.append(("Lidersin!", False))
            elif sira <= 3 < onceki and arac >= 4:
                out.append(("İlk üçtesin.", False))
            else:
                return
            self.sira_son_t = t
