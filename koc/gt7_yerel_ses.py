# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Ses çıkış cihazı seçimi.
Ayarlar > Ses > "Ses cihazı": boşsa koçun sesi arayüzden (Windows'un varsayılan cihazı) çıkar, eskisi gibi.
Bir cihaz seçilirse (ör. kulaklık) konuşma ve fren uyarısı bu modülden, o cihazdan çalar:
gt7_ses (MP3) -> miniaudio ile çözülür -> (istenirse telsiz efekti) -> Discord'daki karıştırıcı -> cihaz.
Discord ile aynı parçalar kullanılır (gt7_discord.mp3_pcm, bip_pcm, Karistirici). miniaudio (MIT) EXE'de
zaten var (Discord için); yoksa ayar listesi boş görünür ve ses arayüzden çıkar.
"""
import threading
from collections import deque

try:
    import miniaudio
    HAZIR = True
except Exception:  # paket yok
    miniaudio = None
    HAZIR = False

import gt7_discord
from gt7_canli import ses_duzeyi

if HAZIR and getattr(gt7_discord, "miniaudio", None) is None:
    gt7_discord.miniaudio = miniaudio      # discord paketi olmadan da MP3 çözülebilsin

KARE_BAYT = gt7_discord.KARE_BAYT


def cihazlar():
    """Bilgisayardaki ses çıkış cihazlarının adları (miniaudio yoksa boş liste)."""
    if not HAZIR:
        return []
    try:
        return [d["name"] for d in miniaudio.Devices().get_playbacks()]
    except Exception:
        return []


class YerelSes:
    """Seçilen ses cihazına çalan koç sesi: konuşma sırası + üstüne binen fren uyarısı sesleri."""

    def __init__(self, ayar_al, sentez):
        self.ayar_al = ayar_al
        self.sentez = sentez
        self.k = gt7_discord.Karistirici()
        self.cihaz = None           # şu an açık cihazın adı
        self.dev = None
        self.hata = None
        self.sira = deque()
        self.olay = threading.Event()
        self.bip_sesleri = {}
        self.kilit = threading.Lock()
        threading.Thread(target=self._isci, daemon=True).start()

    @property
    def acik(self):
        return self.dev is not None

    def ayarla(self, ad):
        """Ayar değişince: ad boşsa kapanır, değilse o adlı cihaz açılır. Döner: açık mı."""
        with self.kilit:
            if ad == self.cihaz and (self.dev or not ad):
                return self.acik
            self._kapat()
            self.cihaz = ad or None
            if not ad or not HAZIR:
                return False
            try:
                kimlik = next((d["id"] for d in miniaudio.Devices().get_playbacks() if d["name"] == ad), None)
                if kimlik is None:
                    self.hata = "seçilen ses cihazı bulunamadı (çıkarılmış olabilir)"
                    return False
                dev = miniaudio.PlaybackDevice(output_format=miniaudio.SampleFormat.SIGNED16, nchannels=2,
                                               sample_rate=gt7_discord.HZ, buffersize_msec=60, device_id=kimlik,
                                               app_name="GT7 Koç")
                gen = self._akis()
                next(gen)
                dev.start(gen)
                self.dev, self.hata = dev, None
                return True
            except Exception as e:
                self.hata = f"{type(e).__name__}: {e}"[:160]
                print("Ses cihazı açılamadı:", repr(e))
                return False

    def _kapat(self):
        if self.dev:
            try:
                self.dev.close()
            except Exception:
                pass
        self.dev = None
        self.k.temizle()

    def _akis(self):
        """miniaudio'nun istediği kadar kareyi karıştırıcıdan verir (20 ms'lik parçalarla)."""
        artik = b""
        istenen = yield b""
        while True:
            gerek = istenen * 4           # stereo, 16 bit
            while len(artik) < gerek:
                artik += self.k.read()
            parca, artik = artik[:gerek], artik[gerek:]
            istenen = yield parca

    def soyle(self, metin, oncelikli=False):
        if not metin or not self.acik:
            return False
        if oncelikli:
            self.sira.clear()
            self.k.temizle()
            self.sira.appendleft(metin)
        else:
            self.sira.append(metin)
        self.olay.set()
        return True

    def bip(self, k, tones):
        if not self.acik:
            return
        if k not in self.bip_sesleri:
            self.bip_sesleri[k] = gt7_discord.bip_pcm(*tones[k])
        self.k.bip(self.bip_sesleri[k])

    def _isci(self):
        while True:
            self.olay.wait()
            try:
                metin = self.sira.popleft()
            except IndexError:
                self.olay.clear()
                continue
            try:
                mp3 = self.sentez(gt7_discord.okunur(metin))
                if mp3 and self.acik:
                    a = self.ayar_al()
                    self.k.ekle(gt7_discord.mp3_pcm(mp3, a.get("telsiz", "kapali"), ses_duzeyi(a)))
            except Exception as e:
                self.hata = f"{type(e).__name__}: {e}"[:160]
                print("Koçun sesi cihaza gönderilemedi:", repr(e))
