# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Discord: koçun sesi PS5 kulaklığına
Koç, kullanıcının kendi Discord sunucusunda bir bot olarak sesli kanala girer; kullanıcı PS5'ten
aynı sesli kanala katılır ve koçu (konuşma + fren / vites bipleri) kulaklıktan duyar.
- Bot anahtarı (token) EXE'nin yanında discord_token.txt'de durur (ayarlar.json'a yazılmaz).
- Kanal: ayarlardaki kanal ya da "otomatik" (sunucuda insanların olduğu sesli kanala girer, onları izler).
- Ses: gt7_ses (Microsoft Ahmet/Emel) MP3 -> miniaudio ile çözülür -> (istenirse telsiz efekti) ->
  48 kHz stereo; bipler aynı karıştırıcıda konuşmanın üstüne binebilir (konuşmayı kesmez).
- Hangi mesajın okunacağı Ayarlar > Ses'teki seçimlere göre (sessiz, ses_viraj, ses_tur, ses_muhendis)
  sunucu tarafında karar verilir (okunacak); böylece telefon da açıksa ses iki kez gitmez.
Paketler (EXE'ye gömülü): discord.py (MIT), PyNaCl (Apache-2.0), davey (MIT, Discord'un uçtan uca
ses şifrelemesi DAVE), miniaudio (MIT). Yoksa koç Discord'suz çalışır.
"""
import array
import math
import os
import random
import re
import threading
import time
from collections import deque

from gt7_yol import USER_DIR
from gt7_canli import ses_duzeyi

TOKEN_FILE = os.path.join(USER_DIR, "discord_token.txt")
HZ = 48000
KARE = 960                # 20 ms (Discord'un kare boyu), mono örnek sayısı
KARE_BAYT = KARE * 2 * 2  # stereo, 16 bit
SES_SEVIYE = 0.9
TELSIZ_HZ = 24000
TEKRAR_S = 15             # bağlantı kurulamazsa bu kadar sn sonra yeniden denenir         # telsiz efekti bu örnekleme hızında hesaplanır (hızlı olsun diye), sonra 48 kHz

try:
    import discord
    import miniaudio
    HAZIR, EKSIK = True, None
    import logging

    class _Gunluk(logging.Handler):
        """discord.py'nin uyarı ve hataları da koc_gunluk.txt'ye düşsün (yoksa hiçbir yerde görünmüyor)."""
        def emit(self, kayit):
            try:
                print("Discord kütüphanesi:", self.format(kayit)[:600])
            except Exception:
                pass
    _g = logging.getLogger("discord")
    if not any(isinstance(h, _Gunluk) for h in _g.handlers):
        _g.addHandler(_Gunluk(level=logging.WARNING))
        _g.setLevel(logging.INFO)
except Exception as e:  # paket yoksa (Python ile geliştirirken) koç Discord'suz çalışır
    discord = miniaudio = None
    HAZIR, EKSIK = False, f"{type(e).__name__}: {e}"


# ---------------- Okunuş (arayuz.html'deki okunur() ile aynı) ----------------
def okunur(t):
    t = re.sub(r"(\d+):(\d\d)\.(\d)\d\d", lambda m: f"{m.group(1)} dakika {int(m.group(2))} virgül {m.group(3)} saniye", t)
    t = re.sub(r"\+(\d)", r"artı \1", t)
    t = re.sub(r"(^|\s)[-−](\d)", r"\1eksi \2", t)
    t = re.sub(r"(\d+)\.(\d+)", r"\1 virgül \2", t)
    t = t.replace("km/s", "kilometre")
    t = re.sub(r"(\d)\s?sn(?![^\W\d_])", r"\1 saniye", t)
    t = re.sub(r"(\d)\s?m(?![^\W\d_]|/)", r"\1 metre", t)
    t = t.replace("->", ",")
    return re.sub(r"[*()]", " ", t)


def okunacak(kind, baslik, ses, ayar):
    """Bu mesaj sesli okunur mu, okunursa (metin, öncelikli mi). Tek kural burada: arayüz de
    (mesajın "oku" alanı) Discord da buna uyar. Ayarlar > Ses: sessiz, ses_viraj, ses_tur, ses_muhendis."""
    if ayar.get("sessiz") == "acik":
        return None
    acik = lambda ad: ayar.get(ad, "acik") == "acik"   # noqa: E731
    if kind in ("anlik", "sonra"):
        return (ses or baslik, kind == "anlik") if acik("ses_viraj") else None
    if kind == "tur":
        return (ses, False) if acik("ses_tur") and ses else None
    if kind in ("uyari", "muhendis"):
        return (baslik, False) if acik("ses_muhendis") else None
    return None


# ---------------- Ses işleme (saf Python, ek paket yok) ----------------
def _biquad(x, tur, f, q, hz, kazanc_db=0.0):
    """RBJ süzgeci (alçak/yüksek geçiren, bant, tepe) — telsiz efekti için."""
    w = 2 * math.pi * f / hz
    cw, sw = math.cos(w), math.sin(w)
    a = sw / (2 * q)
    if tur == "lp":
        b0, b1, b2, a0, a1, a2 = (1 - cw) / 2, 1 - cw, (1 - cw) / 2, 1 + a, -2 * cw, 1 - a
    elif tur == "hp":
        b0, b1, b2, a0, a1, a2 = (1 + cw) / 2, -(1 + cw), (1 + cw) / 2, 1 + a, -2 * cw, 1 - a
    elif tur == "bp":
        b0, b1, b2, a0, a1, a2 = a, 0.0, -a, 1 + a, -2 * cw, 1 - a
    else:  # tepe (peaking)
        A = 10 ** (kazanc_db / 40)
        b0, b1, b2, a0, a1, a2 = 1 + a * A, -2 * cw, 1 - a * A, 1 + a / A, -2 * cw, 1 - a / A
    b0, b1, b2, a1, a2 = b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0
    y, x1, x2, y1, y2 = [0.0] * len(x), 0.0, 0.0, 0.0, 0.0
    for i, v in enumerate(x):
        o = b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, v, y1, o
        y[i] = o
    return y


# arayuz.html'deki TELSIZ ile aynı değerler
TELSIZ = {"hafif": dict(alt=320, ust=3300, tepe=4, surme=6, surus=1.2, cizirti=0.004, bas=0.05, kuyruk=0.09, kuyruk_ses=0.05),
          "guclu": dict(alt=550, ust=2500, tepe=8, surme=28, surus=1.8, cizirti=0.014, bas=0.08, kuyruk=0.20, kuyruk_ses=0.12)}


def telsiz(x, seviye, hz=TELSIZ_HZ):
    """x: -1..1 mono örnekler. Döner: telsiz efektli örnekler (başta "kşş", sonda kuyruk dahil)."""
    p = TELSIZ.get(seviye) or TELSIZ["hafif"]
    y = [v * p["surus"] for v in x]
    for tur, f in (("hp", p["alt"]), ("hp", p["alt"]), ("lp", p["ust"]), ("lp", p["ust"])):
        y = _biquad(y, tur, f, 0.8, hz)
    y = _biquad(y, "pk", 1700, 0.9, hz, p["tepe"])
    k = p["surme"]
    y = [(1 + k) * v / (1 + k * abs(v)) for v in y]
    tepe = max((abs(v) for v in y), default=0) or 1.0
    y = [v * 0.8 / tepe for v in y]                     # sıkıştırıcı yerine düz seviye
    bas, kuyruk = int(p["bas"] * hz), int(p["kuyruk"] * hz)
    n = bas + len(y) + kuyruk
    rnd = random.Random(7)
    g = _biquad([rnd.uniform(-1, 1) for _ in range(n)], "bp", 1900, 0.7, hz)
    out = [0.0] * n
    for i in range(n):
        if i < bas:
            seviye_g = 0.10 * min(1.0, i / (0.01 * hz))
        elif i < bas + len(y):
            seviye_g = p["cizirti"]
        else:
            seviye_g = p["kuyruk_ses"] * (1 - (i - bas - len(y)) / max(1, kuyruk))
        v = g[i] * seviye_g * 3
        if bas <= i < bas + len(y):
            v += y[i - bas]
        out[i] = v
    return out


def _stereo48(mono16, hz):
    """16 bit mono (array 'h') -> 48 kHz stereo bayt. 24 kHz'ten çıkarken her örnek iki kez."""
    if hz != HZ:
        kat = HZ // hz
        m = array.array("h", bytes(len(mono16) * kat * 2))
        for k in range(kat):
            m[k::kat] = mono16
        mono16 = m
    st = array.array("h", bytes(len(mono16) * 4))
    st[0::2] = mono16
    st[1::2] = mono16
    return st.tobytes()


def _float16(x):
    return array.array("h", (max(-32767, min(32767, int(v * 32767 * SES_SEVIYE))) for v in x))


def mp3_pcm(mp3, efekt="kapali", duzey=1.0):
    """MP3 (gt7_ses) -> Discord'a gidecek 48 kHz stereo 16 bit bayt. duzey: ses düzeyi 0–1 (Ayarlar > Ses)."""
    if efekt and efekt != "kapali":
        d = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=TELSIZ_HZ)
        x = [v / 32768 for v in d.samples]
        return _stereo48(_float16([v * duzey for v in telsiz(x, efekt)]), TELSIZ_HZ)
    d = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=HZ)
    kat = SES_SEVIYE * duzey
    m = d.samples if kat == 1 else array.array("h", (int(v * kat) for v in d.samples))
    return _stereo48(m, HZ)


def bip_pcm(freq, ms, ses=0.35):
    """gt7_fren_sesi.soft_wav ile aynı yumuşak bip, 48 kHz stereo."""
    n = int(HZ * ms / 1000)
    atak = max(1, int(HZ * 0.010))
    m = array.array("h", (int(32767 * ses * min(1.0, i / atak) * (1 - i / n) ** 1.5
                              * math.sin(2 * math.pi * freq * i / HZ)) for i in range(n)))
    return _stereo48(m, HZ)


class Karistirici:
    """Discord'a 20 ms'lik kareler veren ses kaynağı: sıradaki konuşma + üstüne binen bipler.
    Hep çalar (boşken sessizlik): her an aynı gecikme, bipler beklemeden çıkar."""

    def __init__(self):
        self.kilit = threading.Lock()
        self.konusma = deque()      # bayt parçaları (sırayla)
        self.poz = 0
        self.bipler = []            # [bayt, poz]
        self.okunan = 0             # Discord çalıcısının istediği kare sayısı (tanı: çalıcı çalışıyor mu)

    def temizle(self):
        with self.kilit:
            self.konusma.clear()
            self.poz = 0

    def ekle(self, pcm):
        with self.kilit:
            self.konusma.append(pcm)

    def bip(self, pcm):
        with self.kilit:
            self.bipler.append([pcm, 0])

    @property
    def mesgul(self):
        return bool(self.konusma)

    def read(self):
        with self.kilit:
            self.okunan += 1
            kare = b""
            while self.konusma and len(kare) < KARE_BAYT:
                parca = self.konusma[0]
                al = parca[self.poz:self.poz + KARE_BAYT - len(kare)]
                kare += al
                self.poz += len(al)
                if self.poz >= len(parca):
                    self.konusma.popleft()
                    self.poz = 0
            kare = kare.ljust(KARE_BAYT, b"\0")
            if not self.bipler:
                return kare
            a = array.array("h", kare)
            for b in self.bipler:
                parca = array.array("h", b[0][b[1]:b[1] + KARE_BAYT])
                for i, v in enumerate(parca):
                    s = a[i] + v
                    a[i] = 32767 if s > 32767 else -32768 if s < -32768 else s
                b[1] += KARE_BAYT
            self.bipler = [b for b in self.bipler if b[1] < len(b[0])]
            return a.tobytes()

    def is_opus(self):
        return False

    def cleanup(self):
        pass


if HAZIR:
    class _Kaynak(discord.AudioSource):
        def __init__(self, k):
            self.k = k

        def read(self):
            return self.k.read()

        def is_opus(self):
            return False


# ---------------- Bot ----------------
def token_oku():
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def token_yaz(token):
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(token.strip())


class DiscordKoc:
    """Arka planda kendi iş parçacığında çalışan Discord botu. Tüm çağrılar her iş parçacığından güvenli."""

    def __init__(self, ayar_al, sentez):
        self.ayar_al = ayar_al            # () -> güncel ayarlar
        self.sentez = sentez              # (metin) -> MP3 ya da None (gt7_ses)
        self.k = Karistirici()
        self.durum = {"durum": "kapali", "mesaj": "Kapalı."}
        self.kanallar = []                # [{"id", "ad", "sunucu", "kisi"}]
        self.client = self.loop = self.vc = None
        self.is_sira = deque()
        self.is_olay = threading.Event()
        self.bip_sesleri = {}
        self._kapat = False
        self.calici_hata = None           # ses çalıcısı hata verip durduysa açıklaması (tanı)
        self.ses_hata = None              # son cümle sese çevrilemediyse nedeni (tanı)
        self._tani_onceki = (0, 0.0)      # (okunan kare, zaman): çalıcı ilerliyor mu
        self.nesil = 0                    # her başlat/durdur'da artar: eski bağlantı iş parçacığı kendini bitirir
        threading.Thread(target=self._isci, daemon=True).start()

    # --- dışarıdan ---
    def bilgi(self):
        out = dict(self.durum)
        out.update(hazir=HAZIR, eksik=EKSIK, token_var=bool(token_oku()), kanallar=list(self.kanallar))
        if HAZIR:
            try:
                discord.opus._load_default()
                out["opus"] = discord.opus.is_loaded()
            except Exception:
                out["opus"] = False
        out["tani"] = self.tani()
        return out

    def tani(self):
        """Ses neden gitmiyor? Tek satırlık durum (Ayarlar > Discord'da ve koc_gunluk.txt'de görünür).
        Discord'a gerçek bağlantı geliştirme makinesinde denenemediği için sorun buradan okunur."""
        vc = self.vc
        if not HAZIR or not vc:
            return ""
        p = []
        try:
            p.append("kanal: bağlı" if vc.is_connected() else "kanal: BAĞLI DEĞİL")
            simdi, okunan = time.time(), self.k.okunan
            o0, t0 = self._tani_onceki
            if simdi - t0 >= 1:
                self._tani_hiz = (okunan - o0) / (simdi - t0) if t0 else None
                self._tani_onceki = (okunan, simdi)
            hiz = getattr(self, "_tani_hiz", None)
            p.append("çalıcı: " + ("çalışıyor" if vc.is_playing() else "DURMUŞ")
                     + (f" ({hiz:.0f} kare/sn)" if hiz is not None else ""))
            b = getattr(vc, "_connection", None)
            if b is not None:
                surum = getattr(b, "dave_protocol_version", None)
                oturum = getattr(b, "dave_session", None)
                try:
                    from importlib.metadata import version
                    dv = " (davey " + version("davey") + ")"
                except Exception:
                    dv = ""
                if oturum is not None and hasattr(oturum, "prepare_transition") and not getattr(oturum, "ready", False):
                    dv += " UYUMSUZ davey sürümü: 0.1.7 olmalı"
                p.append(f"şifreleme: {getattr(vc, 'mode', '?')}, DAVE sürüm {surum}{dv}, "
                         + ("oturum yok" if oturum is None else "hazır" if getattr(oturum, "ready", False) else "HAZIR DEĞİL"))
            try:
                ben = vc.guild.me.voice
                if ben and (ben.mute or ben.suppress):
                    p.append("SUNUCU BOTU SUSTURMUŞ (bota sağ tıkla > Sunucuda sustur'u kaldır)")
                izin = vc.channel.permissions_for(vc.guild.me)
                if not izin.speak:
                    p.append("KONUŞMA İZNİ YOK (kanal izinlerinde bota Konuş izni ver)")
            except Exception:
                pass
            if self.calici_hata:
                p.append("çalıcı hatası: " + self.calici_hata)
            if self.ses_hata:
                p.append("ses hatası: " + self.ses_hata)
        except Exception as e:
            p.append(f"tanı okunamadı: {type(e).__name__}: {e}"[:120])
        return " · ".join(p)

    def baslat(self, token=None):
        if not HAZIR:
            self._d("hata", "Discord paketleri bu sürümde yok: " + (EKSIK or ""))
            return
        if token:
            token_yaz(token)
        token = token_oku()
        if not token:
            self._d("kapali", "Bot anahtarı (token) girilmedi.")
            return
        self.durdur()
        self._kapat = False
        self.nesil += 1
        threading.Thread(target=self._calis, args=(token, self.nesil), daemon=True).start()

    def durdur(self):
        self._kapat = True
        self.nesil += 1
        c, lp = self.client, self.loop
        if c and lp and lp.is_running():
            try:
                import asyncio
                asyncio.run_coroutine_threadsafe(c.close(), lp).result(10)
            except Exception:
                pass
        self.client = self.vc = None
        self._d("kapali", "Kapalı.")

    def kanal_degisti(self):
        """Ayarlardaki kanal değişti: yeniden yerleş."""
        if self.client and self.loop:
            import asyncio
            asyncio.run_coroutine_threadsafe(self._yerles(), self.loop)

    def soyle(self, metin, oncelikli=False):
        """Metni sıraya koyar (öncelikli: çalanı ve sırayı keser)."""
        if not metin or not self.bagli:
            return False
        if oncelikli:
            self.is_sira.clear()
            self.k.temizle()
            self.is_sira.appendleft(metin)
        else:
            self.is_sira.append(metin)
        self.is_olay.set()
        return True

    def bip(self, k, tones):
        if not self.bagli:
            return
        if k not in self.bip_sesleri:
            self.bip_sesleri[k] = bip_pcm(*tones[k])
        self.k.bip(self.bip_sesleri[k])
        self._canlandir()

    def _cal(self):
        """Ses çalıcısını başlatır; hata verip durursa nedeni saklanır ve 2 sn sonra yeniden başlatılır."""
        vc = self.vc
        if not vc or not vc.is_connected() or vc.is_playing():
            return

        def bitti(hata, vc=vc):
            if hata:
                self.calici_hata = f"{type(hata).__name__}: {hata}"[:160]
                print("Discord ses çalıcısı durdu:", repr(hata))
            if self.vc is vc and self.loop and not self._kapat:
                self.loop.call_soon_threadsafe(self.loop.call_later, 2, self._cal)

        try:
            vc.play(_Kaynak(self.k), after=bitti)
        except Exception as e:
            self.calici_hata = f"{type(e).__name__}: {e}"[:160]
            print("Discord ses çalıcısı başlatılamadı:", repr(e))

    def _canlandir(self):
        """Ses gönderilmeden hemen önce: çalıcı durmuşsa başlat, Discord'a "konuşuyorum" bilgisini yenile
        (çalıcı bunu sadece ilk başta yollar; sonradan katılanlar / yeniden bağlanma için zararsız tekrar)."""
        vc, lp = self.vc, self.loop
        if not vc or not lp or not lp.is_running():
            return

        async def yap():
            try:
                self._cal()
                if vc.is_connected():
                    await vc.ws.speak(discord.SpeakingState.voice)
            except Exception as e:
                print("Discord konuşma bilgisi yollanamadı:", repr(e))
        try:
            import asyncio
            asyncio.run_coroutine_threadsafe(yap(), lp)
        except Exception:
            pass

    @property
    def bagli(self):
        return bool(self.vc and self.vc.is_connected())

    # --- iç ---
    def _d(self, durum, mesaj, **ek):
        self.durum = {"durum": durum, "mesaj": mesaj, **ek}
        print("Discord:", mesaj)

    def _isci(self):
        """Sıradaki cümleleri sese çevirir (sırayı korur), karıştırıcıya koyar."""
        while True:
            self.is_olay.wait()
            try:
                metin = self.is_sira.popleft()
            except IndexError:
                self.is_olay.clear()
                continue
            try:
                mp3 = self.sentez(okunur(metin))
                if not mp3:
                    self.ses_hata = "koçun sesi üretilemedi (internet / Microsoft ses servisi)"
                    print("Discord:", self.ses_hata)
                elif self.bagli:
                    a = self.ayar_al()
                    self.k.ekle(mp3_pcm(mp3, a.get("telsiz", "kapali"), ses_duzeyi(a)))
                    self.ses_hata = None
                    self._canlandir()
            except Exception as e:
                self.ses_hata = f"{type(e).__name__}: {e}"[:160]
                print("Discord sesi hazırlanamadı:", repr(e))

    def _calis(self, token, nesil):
        import asyncio
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        while nesil == self.nesil:
            hata = self._bir_kez(token)
            if hata == "anahtar" or nesil != self.nesil:
                break
            self._d("hata", f"Discord'a bağlanılamadı ({hata}). İnterneti kontrol et; {TEKRAR_S} sn sonra yeniden denenecek.")
            for _ in range(TEKRAR_S):
                if nesil != self.nesil:
                    break
                time.sleep(1)

    def _bir_kez(self, token):
        """Bir bağlantı denemesi; bağlantı bitince ya da koparsa döner (hata açıklaması ya da "anahtar")."""
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        c = discord.Client(intents=intents)
        self.client = c

        @c.event
        async def on_ready():
            self._kanal_listesi()
            await self._yerles()

        @c.event
        async def on_voice_state_update(member, before, after):
            if member.id == c.user.id:
                return
            self._kanal_listesi()
            await self._yerles()

        @c.event
        async def on_guild_channel_create(ch):
            self._kanal_listesi()

        @c.event
        async def on_guild_join(g):
            self._kanal_listesi()
            await self._yerles()

        self._d("baglaniyor", "Discord'a bağlanıyor…")
        try:
            self.loop.run_until_complete(c.start(token))
            return "bağlantı kapandı"
        except discord.LoginFailure:
            self._d("hata", "Bot anahtarı (token) geçersiz. Discord geliştirici sayfasında Reset Token ile yenisini al.")
            return "anahtar"
        except Exception as e:
            return f"{type(e).__name__}"[:80]
        finally:
            self.vc = None
            try:
                if not c.is_closed():
                    self.loop.run_until_complete(c.close())
            except Exception:
                pass

    def _kanal_listesi(self):
        c = self.client
        out = []
        for g in c.guilds:
            for ch in g.voice_channels:
                kisi = len([u for u in ch.voice_states if u != c.user.id])
                out.append({"id": str(ch.id), "ad": ch.name, "sunucu": g.name, "kisi": kisi})
        self.kanallar = out

    async def _yerles(self):
        """Ayardaki kanala ya da (otomatik) insanların olduğu sesli kanala gir; kimse yoksa çık."""
        c = self.client
        if not c or not c.is_ready():
            return
        istenen = str(self.ayar_al().get("discord_kanal") or "")
        hedef = None
        if istenen:
            hedef = c.get_channel(int(istenen)) if istenen.isdigit() else None
        else:
            adaylar = [ch for g in c.guilds for ch in g.voice_channels
                       if any(u != c.user.id for u in ch.voice_states)]
            if self.vc and self.vc.channel in adaylar:
                hedef = self.vc.channel              # zaten insanların yanındayız
            elif adaylar:
                hedef = max(adaylar, key=lambda ch: len(ch.voice_states))
        try:
            if hedef is None:
                if self.vc and self.vc.is_connected() and not istenen:
                    await self.vc.disconnect(force=True)
                    self.vc = None
                if not c.guilds:
                    self._d("bagli_kanalsiz", f"Bot ({c.user}) Discord'a bağlandı ama hiçbir sunucuda değil. "
                            "Davet bağlantısıyla sunucuna ekle.")
                else:
                    self._d("bagli_kanalsiz", f"Bot hazır ({c.user}). Sesli kanala katılınca koç da gelir.")
                return
            if self.vc and self.vc.is_connected():
                if self.vc.channel.id != hedef.id:
                    await self.vc.move_to(hedef)
            else:
                self.vc = await hedef.connect(self_deaf=True, timeout=20, reconnect=True)
            self._cal()
            self._d("bagli", f"Koç sesli kanalda: {hedef.guild.name} · {hedef.name}",
                    sunucu=hedef.guild.name, kanal=hedef.name)
        except Exception as e:
            self._d("hata", f"Sesli kanala girilemedi: {type(e).__name__}: {e}"[:200])
