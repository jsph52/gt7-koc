# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Fren bip sesi kalibrasyonu
"Tepki payı": 3. bipi duyduktan sonra frenin gerçekten basılmasına kadar geçen süre
(bilgisayarın sesi geciktirmesi + senin tepkin + pedalın %20'ye inmesi).
Bipler bu kadar erken çalınır ki fren tam fren noktasında başlasın.

İki yolla ölçülür:
1. Tepki testi: araba pistte dururken 5 kez 3 bip çalar, 3. seste frene basarsın.
2. Sürüş içinde otomatik düzeltme: her bip sonrası frene bastığın yer fren noktasıyla
   karşılaştırılır, tur sonunda pay yavaşça düzeltilir (gt7_fren_sesi.py içinde).
Sonuç kalibrasyon.json dosyasına kaydedilir, sonraki açılışlarda kullanılır.
"""
import json
import os
import random
import time

from gt7_yol import USER_DIR

KALIB_FILE = os.path.join(USER_DIR, "kalibrasyon.json")
DEFAULT_DELAY = 0.15   # ölçüm yokken varsayılan tepki payı (saniye)
MIN_DELAY, MAX_DELAY = -0.2, 0.8
BRAKE_ON = 20          # fren bu yüzdeyi geçince "basıldı" sayılır (fren noktasıyla aynı eşik)
BRAKE_OFF = 5          # bunun altı "bırakıldı"
ROUNDS = 5
BEEP_GAP = 0.7          # bipler arası süre (saniye); geri sayım da bunu kullanır


def clamp(v):
    return max(MIN_DELAY, min(MAX_DELAY, v))


def median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def load_delay():
    """Kayıtlı tepki payı (saniye) ve nereden geldiği."""
    try:
        with open(KALIB_FILE, encoding="utf-8") as f:
            k = json.load(f)
        return clamp(float(k["tepki_payi"])), k.get("kaynak", "")
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_DELAY, ""


def save_delay(delay, source):
    try:
        with open(KALIB_FILE, "w", encoding="utf-8") as f:
            json.dump({"tepki_payi": round(clamp(delay), 3), "kaynak": source,
                       "tarih": time.strftime("%Y-%m-%d %H:%M")}, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


class ReactionTest:
    """Araba dururken 3 bip çalar, 3. seste frene basma anını ölçer.
    Ana döngü her pakette update() çağırır. Bitince self.result dolar."""

    def __init__(self, beeper, rounds=ROUNDS, say=print):
        self.beeper = beeper
        self.say = say
        self.rounds = rounds
        self.errs = []
        self.result = None
        self.state = "hazirlik"
        self.still_since = None
        self.prev_brake = 0
        self.told = False
        self.say(f"KALİBRASYON TESTİ: Arabayla pistte dur, frenden ayağını çek. {rounds} kez fren uyarısı "
                 "(3 kısa ses) çalacak. Her seferinde 3. seste (ince ve uzun olan) frene bas, sonra bırak.")

    def update(self, now, speed_kmh, brake, on_track, paused):
        pressed = brake >= BRAKE_ON and self.prev_brake < BRAKE_ON
        self.prev_brake = brake
        ready = on_track and not paused and speed_kmh < 3

        if self.state == "hazirlik":
            if not ready or brake > BRAKE_OFF:
                self.still_since = None
                if not self.told and on_track and not paused and speed_kmh >= 3:
                    self.say("Kalibrasyon: arabayı durdur ve frenden ayağını çek.")
                    self.told = True
                return
            if self.still_since is None:
                self.still_since = now
            if now - self.still_since >= 1.0:
                self.t0 = now + random.uniform(0.8, 2.0)  # ezberlenmesin diye rastgele bekleme
                self.played = 0
                self.state = "bip"
            return

        if self.state == "bip":
            while self.played < 3 and now >= self.t0 + self.played * BEEP_GAP:
                self.beeper.beep(self.played)
                self.played += 1
            t3 = self.t0 + 2 * BEEP_GAP
            if pressed:
                if now < self.t0 + BEEP_GAP:
                    self.say("Çok erken bastın, bu deneme sayılmadı. Frenden ayağını çek, tekrar.")
                else:
                    err = now - t3
                    self.errs.append(err)
                    ne = "geç" if err > 0 else "erken"
                    self.say(f"Deneme {len(self.errs)}/{self.rounds}: 3. sesten {abs(err):.2f} sn {ne}.")
                self.state = "birak"
            elif self.played == 3 and now > t3 + 1.2:
                self.say("Frene basmadın, bu deneme sayılmadı. Tekrar.")
                self.state = "birak"
            return

        if self.state == "birak":
            if brake <= BRAKE_OFF:
                if len(self.errs) >= self.rounds:
                    self._finish()
                else:
                    self.state = "hazirlik"
                    self.still_since = None

    def _finish(self):
        self.result = clamp(median(self.errs))
        self.state = "bitti"
        save_delay(self.result, "tepki testi")
        self.say(f"Kalibrasyon bitti. Tepki payın: {self.result:.2f} sn. "
                 "Fren uyarısı bu kadar erken çalınacak. Sürdükçe kendiliğinden ince ayar yapılır.")
