# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Arayüz (koç ekranı)
- Bilgisayarda küçük bir web sunucusu açar; koç ekranı kendi Windows penceresinde açılır
  (pywebview + Windows'un hazır WebView2'si).
- pywebview yoksa ya da pencere açılamazsa eskisi gibi tarayıcıda açılır.
- Aynı ev ağındaki telefondan da açılabilir (adres günlükte ve ekranda yazar).
"""
import json
import os
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from gt7_yol import DATA_DIR, USER_DIR
import gt7_koc
from gt7_pistler import describe, load_catalog, read_last, search, write_last
from gt7_canli import ayar_oku, ayar_yaz, gecerli
from gt7_veri import araba_adi
import gt7_tt
import gt7_ses
import gt7_hedef
import gt7_rapor
from gt7_viraj_adlari import okunus_uygula
import gt7_discord
import gt7_konusma
import gt7_kopru
import gt7_yerel_ses
import gt7_fren_sesi

PORT = 8765
PAGE_FILE = os.path.join(DATA_DIR, "arayuz.html")
MAX_MESSAGES = 200


GECMIS_DOSYA = os.path.join(USER_DIR, "antrenmanlar.json")
GECMIS_EN_COK = 300
_gecmis_kilit = threading.Lock()


def gecmis_oku():
    """Geçmiş antrenmanlar, en yenisi önce."""
    try:
        with open(GECMIS_DOSYA, encoding="utf-8") as f:
            g = json.load(f)
        return g if isinstance(g, list) else []
    except (OSError, ValueError):
        return []


def gecmis_yaz(kayit):
    """Bir antrenman kaydını ekler ya da (aynı kimlikle) günceller."""
    with _gecmis_kilit:
        g = [x for x in gecmis_oku() if x.get("id") != kayit["id"]]
        g.insert(0, kayit)
        g.sort(key=lambda x: -(x.get("ts") or 0))
        try:
            with open(GECMIS_DOSYA, "w", encoding="utf-8") as f:
                json.dump(g[:GECMIS_EN_COK], f, ensure_ascii=False)
        except OSError:
            pass


class App:
    def __init__(self):
        self.catalog = load_catalog()
        self.by_id = {t["id"]: t for t in self.catalog}
        self.koc = None
        self.messages = []
        self.msg_id = 0
        self.lock = threading.Lock()
        self.tel = phone_url()
        gt7_koc.LISTENERS.append(self.on_message)
        gt7_tt.guncelle()   # haftalık time trial raporu (arka planda)
        # Discord: koçun sesi PS5 kulaklığına (bot anahtarı kayıtlıysa açılışta bağlanır)
        self.discord = gt7_discord.DiscordKoc(self.ayar, self.sentez)
        # Seçilen ses cihazı (Ayarlar > Ses): boşsa ses arayüzden (Windows varsayılanı) çıkar
        self.yerel = gt7_yerel_ses.YerelSes(self.ayar, self.sentez)
        self.yerel.ayarla(self.ayar().get("ses_cihazi"))
        self.ses_yonlendir()
        if gt7_discord.token_oku():
            self.discord.baslat()
        # Antrenman: önce ana ekran, sonra "Serbest antrenman" ya da "Time Trial". Koç telemetriyi hep dinler; antrenman sadece ekranı ve geçmiş kaydını belirler.
        self.antrenman = None        # {"mod": "serbest"/"tt", "etkinlik", "bas_t", "kayit", "state_id", ...}
        self._engel = False          # "Antrenmanı bitir"den sonra: pistten çıkılana kadar otomatik başlama
        threading.Thread(target=self._izleyici, daemon=True).start()

    # ---------------- Antrenman ----------------
    def koc_baslat(self):
        """Koçu pist seçmeden başlatır (açılışta): pisti konumdan kendisi bulur."""
        if self.koc is None:
            self.choose(None, sessiz=True)

    def antrenman_baslat(self, mod="serbest", etkinlik=None, pist_id=None, otomatik=False):
        """Serbest antrenman ya da Time Trial başlatır. Time Trial'da etkinliğin pisti seçilir."""
        e = gt7_tt.bul(self.catalog, etkinlik) if mod == "tt" and etkinlik is not None else None
        if mod == "tt" and not e:
            mod = "serbest"
        hedef_pist = (e or {}).get("pist_id") or pist_id
        if hedef_pist and hedef_pist in self.by_id:
            if not (self.koc and self.koc.sel and self.koc.sel["id"] == hedef_pist):
                self.choose(hedef_pist, sessiz=True)
        else:
            self.koc_baslat()
        with self.lock:
            self.antrenman = {"mod": mod, "etkinlik": e["id"] if e else None, "bas_t": time.time(),
                              "otomatik": otomatik, "kayit": None, "state_id": None, "duyuruldu": False}
        ad = "Time Trial: " + e["pist"] if e else "Serbest antrenman"
        self.on_message(f"{ad} başladı." + (" Piste çıktığın için kendiliğinden başlatıldı." if otomatik else ""),
                        [], "bilgi")
        return self.antrenman

    def antrenman_bitir(self):
        with self.lock:
            a, self.antrenman = self.antrenman, None
        if a:
            if self.koc:
                self.koc.odak_ayarla(None)
            self._kaydi_guncelle(a, son=True)
            live = self.koc.live if self.koc else {}
            self._engel = bool(live.get("connected") and live.get("on_track"))
            self.on_message("Antrenman bitti.", [], "bilgi")

    def _izleyici(self):
        while True:
            time.sleep(1.0)
            try:
                self._izle()
            except Exception as e:  # izleyici hatası koçu durdurmasın
                print(f"(Antrenman izleyici: {e!r})")

    def _izle(self):
        k = self.koc
        if not k:
            return
        live = k.live
        bagli = bool(live.get("connected"))    # bağlantı kesilince son paketin "pistte" bilgisi eskir
        pistte = bagli and bool(live.get("on_track")) and not live.get("paused") and (live.get("hiz") or 0) > 5
        if not (bagli and live.get("on_track")):
            self._engel = False
        a = self.antrenman
        if a is None:
            if pistte and not self._engel:
                self.antrenman_baslat("serbest", otomatik=True)
            return
        self._kaydi_guncelle(a)
        # Time Trial: hedef seçiliyse piste çıkınca bir kez söyle ("Fuji Time Trial, hedef altın.")
        if a["mod"] == "tt" and pistte and not a["duyuruldu"]:
            a["duyuruldu"] = True
            e = gt7_tt.bul(self.catalog, a["etkinlik"])
            th = gt7_koc.tt_hedefi(k.state.get("track"))
            if e and th:
                ad = gt7_tt.HEDEF_ADLARI.get(th.get("etiket"), "").lower()
                self.on_message(f"{e['pist']} Time Trial, hedef {ad} {gt7_koc.sure(th['ms'])}.", [], "tur",
                                ses=f"Time Trial, hedef {ad}.")

    def _kaydi_guncelle(self, a, son=False):
        """Bu antrenmanın geçmiş kaydı (antrenmanlar.json): pist, araba, tur sayısı, en iyi tur, hedef, rapor.
        Pist değişirse (koç konumdan buldu) o ana kadarki kısım ayrı kayıt olur."""
        k = self.koc
        st = k.state
        if a["state_id"] not in (None, id(st)) and a["kayit"] and a["kayit"]["tur"]:
            a["kayit"] = None
            a["bas_t"] = time.time()
        a["state_id"] = id(st)
        turlar = [t for t in st.get("turlar", []) if t.get("t", 0) >= a["bas_t"]]
        if not turlar:
            return
        tr = st.get("track") or {}
        temiz = [t["ms"] for t in turlar if not t.get("ref_disi")]
        h = st.get("hedef") or {}
        kayit = a["kayit"] or {"id": time.strftime("%Y%m%d_%H%M%S", time.localtime(a["bas_t"])),
                               "mod": a["mod"], "etkinlik": a["etkinlik"], "ts": a["bas_t"],
                               "tarih": time.strftime("%d.%m.%Y %H:%M", time.localtime(a["bas_t"]))}
        en = min(temiz) if temiz else None
        kayit.update({"pist": gt7_koc.pist_adi(tr), "pist_id": tr.get("official_id"),
                      "araba": turlar[-1].get("araba"), "tur": len(turlar), "en_iyi_ms": en,
                      "en_iyi": gt7_koc.sure(en) if en else None,
                      "hedef_ms": h.get("hedef_ms"), "hedef": h.get("hedef"),
                      "rapor": gt7_rapor.dosya_adi(st, gt7_koc.pist_adi(tr)), "bitis_ts": time.time()})
        if son or kayit != a.get("_yazilan"):
            a["kayit"] = kayit
            a["_yazilan"] = dict(kayit)
            gecmis_yaz(kayit)

    def antrenman_bilgi(self):
        """Arayüz için: süren antrenman (ya da None)."""
        a = self.antrenman
        if not a:
            return None
        k = self.koc
        live = k.live if k else {}
        out = {"mod": a["mod"], "etkinlik": a["etkinlik"], "otomatik": a["otomatik"]}
        if a["mod"] == "tt":
            e = gt7_tt.bul(self.catalog, a["etkinlik"]) or {}
            th = gt7_koc.tt_hedefi(k.state.get("track")) if k else None
            car = k.car if k else None
            rek = ((k.state.get("track") or {}).get("rekor") or {}).get(str(car)) if k and car is not None else None
            secili = gt7_koc.secili_rekor(k.state.get("track"), car) if k else None
            ht = ((k.state.get("track") or {}).get("hedef_tur") or {}) if k else {}
            out.update({"pist": e.get("pist"), "pist_dogru": bool(live.get("pist_dogru")),
                        "araba": araba_adi(car) if car is not None else None,
                        "rekor_turu": bool(secili), "rekor_kendi_araba": bool(secili and rek and secili is rek),
                        "hedef_etiket": (th or {}).get("etiket"), "hedef_tip": ht.get("tip")})
        return out

    def ayar(self):
        return self.koc.ayar if self.koc else ayar_oku()

    def sentez(self, metin):
        a = self.ayar()
        return gt7_ses.sentez(okunus_uygula(metin), a.get("ses"), a.get("ses_hizi"))

    def ses_yonlendir(self):
        """Bipler: bilgisayar / Discord / ikisi (ayar ses_cikisi); bilgisayarda seçilen ses cihazı varsa oradan."""
        cikis = self.ayar().get("ses_cikisi", "bilgisayar")
        discorda = cikis in ("discord", "ikisi")
        cihaza = cikis != "discord" and self.yerel.acik
        gt7_fren_sesi.YEREL = cikis != "discord" and not cihaza

        def calici(k):
            if discorda:
                self.discord.bip(k, gt7_fren_sesi.TONES)
            if cihaza:
                self.yerel.bip(k, gt7_fren_sesi.TONES)
        gt7_fren_sesi.EK_CALICI = calici if (discorda or cihaza) else None

    def on_message(self, title, lines, kind, ses=None):
        # Sesli okunacak mı: tek kural (gt7_discord.okunacak); arayüz "oku" alanına bakar, Discord aynı metni okur
        a = self.ayar()
        r = gt7_discord.okunacak(kind, title, ses, a)
        with self.lock:
            self.msg_id += 1
            self.messages.append({"id": self.msg_id, "saat": time.strftime("%H:%M:%S"),
                                  "baslik": title, "satirlar": lines, "tur": kind, "ses": ses,
                                  "oku": list(r) if r else None})
            del self.messages[:-MAX_MESSAGES]
        if r and a.get("ses_cikisi") in ("discord", "ikisi"):
            self.discord.soyle(*r)
        if r and a.get("ses_cikisi") != "discord" and self.yerel.acik:
            self.yerel.soyle(*r)

    def choose(self, track_id, sessiz=False):
        sel = self.by_id.get(track_id) if track_id else None
        if sel:
            write_last(sel)
        if self.koc is None:
            self.koc = gt7_koc.Koc(sel, self.catalog)
            threading.Thread(target=self.koc.run, daemon=True).start()
            if not sessiz:
                self.on_message("Koç başladı. Pist: " + (sel["name"] if sel else "seçilmedi (otomatik tanıma)"),
                                [describe(sel)] if sel else [], "bilgi")
        else:
            self.koc.set_track(sel)
        return sel

    def status(self, since):
        k = self.koc
        with self.lock:
            msgs = [m for m in self.messages if m["id"] > since]
        out = {"basladi": k is not None, "mesajlar": msgs, "telefon": self.tel,
               "antrenman": self.antrenman_bilgi(), "yerel_ses": self.yerel.acik,
               "ayar": k.ayar if k else ayar_oku(), "kayit_klasoru": USER_DIR,
               "ses_hata": gt7_ses.hata}
        last = read_last(self.catalog)
        out["son_pist"] = {"id": last["id"], "ad": last["name"]} if last else None
        if k:
            st = k.state
            live = dict(k.live)
            if live.get("connected") is False and time.time() - k.started > 15:
                live["uzun_bekleme"] = True
            out.update({
                "hata": k.error,
                "canli": live,
                "pist": {"id": k.sel["id"], "ad": k.sel["name"]} if k.sel else None,
                "harita_surum": f"{id(st)}-{st.get('map_ver', 0)}",
                "oneriler": st.get("oneriler", []),
                "odak": k.odak,
                "virajlar": [c["no"] for c in ((st.get("track") or {}).get("corners") or [])],
                "inceleme_surum": (st.get("inceleme") or {}).get("id"),
            })
        return out

    def pist_kaydi(self, pist_id):
        """Bu pistin kayıtlı hafızası (turlar, rekor turları, hedefler) ya da None."""
        k = self.koc
        tr = k.state.get("track") if k else None
        if tr and tr.get("official_id") == pist_id:
            return tr
        try:
            with open(os.path.join(gt7_koc.REF_DIR, f"pist_{pist_id}.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def en_iyi(self, pist_id, kod=None):
        """Bu pistteki en iyi temiz turun: (ms, araba kodu) ya da (None, None). kod verilirse sadece o araba."""
        tr = self.pist_kaydi(pist_id) or {}
        en = (None, None)
        for c, laps in (tr.get("laps") or {}).items():
            if kod is not None and str(c) != str(kod):
                continue
            for L in laps:
                if en[0] is None or L["lap_ms"] < en[0]:
                    en = (L["lap_ms"], int(c) if str(c).isdigit() else c)
        return en

    def hedef_oku(self, pist_id):
        """Bu pistte Time Trial'dan seçilen hedef: (ms, etiket) ya da (None, None)."""
        h = gt7_koc.tt_hedefi(self.pist_kaydi(pist_id)) if pist_id else None
        return (h["ms"], h["etiket"]) if h else (None, None)

    def time_trial(self):
        """Time Trial sekmesi: süren etkinlikler, altın hedefi, rekor turu."""
        gt7_tt.guncelle()
        k = self.koc
        car = k.car if k else None
        olaylar = gt7_tt.etkinlikler(self.catalog, self.en_iyi)
        for e in olaylar:
            e["hedef_ms"], e["hedef_etiket"] = self.hedef_oku(e["pist_id"])
        return {"etkinlikler": olaylar, "durum": gt7_tt.durum(),
                "rekor_modu": bool(k and k.rekor_modu), "rekorlar": k.rekor_bilgi() if k else [],
                "rekor_cmp": k.state.get("rekor_cmp") if k else None,
                "pist": {"id": k.sel["id"], "ad": k.sel["name"]} if k and k.sel else None,
                "araba": araba_adi(car) if car is not None else None, "araba_kod": car}

    def inceleme(self):
        """İnceleme ekranı (oyun duraklatılınca): bu antrenmanın turları, viraj farkları ve sorunları.
        Toplama (ortalama, sıklık, gidişat, dağılım) arayüzde yapılır; "geçersiz / kaza turları" seçenekleri anında."""
        k = self.koc
        if not k:
            return {"turlar": []}
        st = k.state
        a = self.antrenman
        turlar = [t for t in st.get("inceleme_turlar") or [] if not a or t.get("t", 0) >= a["bas_t"] - 1]
        h = st.get("hedef") or {}
        tavsiye = {kod: gt7_kopru.buyuk_harf(v[0]) + "." for kod, v in gt7_konusma.TAVSIYE.items()}
        tavsiye["cizgi"] = "Çizgini en iyi geçişindeki çizgiye yaklaştır."
        tavsiye["vites"] = "En iyi geçişindeki vitesi kullan."
        return {"turlar": turlar, "ref": st.get("inceleme_ref") or {}, "harita": st.get("inceleme_harita"),
                "ideal": st.get("inceleme_ideal"), "hedef": h.get("hedef"), "hedef_ms": h.get("hedef_ms"),
                "hedef_kaynak": h.get("kaynak"), "hedef_etiket": h.get("etiket"),
                "pist": gt7_koc.pist_adi(st.get("track")), "araba": araba_adi(k.car) if k.car is not None else None,
                "rekor_ref": bool(st.get("rekor_ref")), "neden": gt7_konusma.NEDEN, "teknik": gt7_konusma.TEKNIK,
                "teknik_adi": gt7_konusma.TEKNIK_ADI, "tavsiye": tavsiye}

    def pist_cizgi(self, pist_id, en_cok=90):
        """Ana ekrandaki küçük pist çizimi için seyreltilmiş çizgi [[x, z], ...] (yoksa None)."""
        t = self.by_id.get(pist_id)
        yol = (t or {}).get("path") or []
        if len(yol) < 3:
            return None
        adim = max(1, len(yol) // en_cok)
        return [[round(p[0]), round(p[1])] for p in yol[::adim]]

    def ana(self):
        """Ana ekran: süren antrenman, son antrenman, bu haftanın Time Trial'ları, geçmiş antrenmanlar."""
        gt7_tt.guncelle()
        k = self.koc
        live = k.live if k else {}
        gecmis = gecmis_oku()
        for g in gecmis[:6]:
            g["cizgi"] = self.pist_cizgi(g.get("pist_id"))
        tt = gt7_tt.etkinlikler(self.catalog, self.en_iyi)
        for e in tt:
            e["hedef_ms"], e["hedef_etiket"] = self.hedef_oku(e["pist_id"])
            e["cizgi"] = self.pist_cizgi(e["pist_id"])
        return {"antrenman": self.antrenman_bilgi(), "son": gecmis[0] if gecmis else None,
                "gecmis": gecmis[:6], "gecmis_sayi": len(gecmis), "tt": tt, "tt_durum": gt7_tt.durum(),
                "baglanti": {"bagli": bool(live.get("connected")), "adres": live.get("target")}}

    def tt_hazirlik(self, etkinlik):
        """Time Trial hazırlık ekranı: etkinlik, pist çizgisi + virajlar, bu pistteki rekor turları."""
        e = gt7_tt.bul(self.catalog, etkinlik, self.en_iyi)
        if not e:
            return {"etkinlik": None}
        e["hedef_ms"], e["hedef_etiket"] = self.hedef_oku(e["pist_id"])
        t = self.by_id.get(e["pist_id"]) or {}
        tr = self.pist_kaydi(e["pist_id"]) or {}
        k = self.koc
        car = k.car if k else None
        ht = tr.get("hedef_tur") if "hedef_tur" in tr else (
            {"tip": "rekor", "araba": str(car)} if car is not None and str(car) in (tr.get("rekor") or {}) else None)
        en, en_kod = self.en_iyi(e["pist_id"], car) if car is not None else (None, None)
        return {"etkinlik": e, "cizgi": t.get("path"), "virajlar": t.get("corner_xy"),
                "rekorlar": [{"araba": araba_adi(int(c) if str(c).isdigit() else c), "kod": str(c),
                              "ms": r["lap_ms"], "sure": gt7_koc.sure(r["lap_ms"])}
                             for c, r in sorted((tr.get("rekor") or {}).items(), key=lambda x: x[1]["lap_ms"])],
                "en_iyi_ms": en, "en_iyi": gt7_koc.sure(en) if en else None,
                "hedef_tur": ht, "fren_ayar": tr.get("fren_ayar") or {"nokta": "rekor", "pay": "yok"},
                "araba": araba_adi(car) if car is not None else None, "araba_kod": car,
                "rekor_modu": bool(k and k.rekor_modu), "antrenman": self.antrenman_bilgi()}

    def track_shape(self):
        """Seçilen pistin hazır çizgisi ve viraj noktaları (henüz tur yokken gösterilir)."""
        k = self.koc
        if not k or not k.sel:
            return {}
        return {"cizgi": k.sel["path"] or [], "virajlar": k.sel["corner_xy"] or [],
                "ad": k.sel["name"]}


def phone_url():
    """Aynı ağdaki telefonun açabileceği adres."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))   # veri gönderilmez, sadece hangi ağda olduğumuz öğrenilir
        ip = s.getsockname()[0]
        s.close()
        return f"http://{ip}:{PORT}"
    except OSError:
        return None


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # her isteği konsola yazma

        def send(self, code, body, ctype, onbellek=False):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=86400" if onbellek else "no-store")
            self.end_headers()
            self.wfile.write(data)

        def json(self, obj, code=200):
            self.send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path in ("/", "/index.html"):
                with open(PAGE_FILE, "rb") as f:
                    self.send(200, f.read(), "text/html; charset=utf-8")
            elif u.path in ("/simge.svg", "/simge.png", "/favicon.ico"):
                # Uygulama simgesi (karbon GT takometre): sekme ve telefon ana ekranı için
                ad = "simge.ico" if u.path == "/favicon.ico" else u.path[1:]
                tur = {"svg": "image/svg+xml", "png": "image/png", "ico": "image/x-icon"}[ad.rsplit(".", 1)[1]]
                try:
                    with open(os.path.join(DATA_DIR, "simge", ad), "rb") as f:
                        self.send(200, f.read(), tur)
                except OSError:
                    self.send(404, "", "text/plain")
            elif u.path.startswith("/yazitipi/"):
                # Temaların yazı tipleri (Barlow Condensed, OFL): EXE'ye gömülü, internet gerekmez
                ad = os.path.basename(u.path)
                try:
                    if not ad.endswith(".woff2"):
                        raise OSError
                    with open(os.path.join(DATA_DIR, "yazitipi", ad), "rb") as f:
                        self.send(200, f.read(), "font/woff2", onbellek=True)
                except OSError:
                    self.send(404, "", "text/plain")
            elif u.path == "/api/ana":
                self.json(app.ana())
            elif u.path == "/api/seans_inceleme":
                self.json(app.inceleme())
            elif u.path == "/api/ses_cihazlari":
                self.json({"cihazlar": gt7_yerel_ses.cihazlar(), "acik": app.yerel.acik, "hata": app.yerel.hata,
                           "secili": app.ayar().get("ses_cihazi", "")})
            elif u.path == "/api/gecmis":
                g = gecmis_oku()
                for x in g:
                    x["cizgi"] = app.pist_cizgi(x.get("pist_id"), 40)
                self.json(g)
            elif u.path == "/api/tt_hazirlik":
                try:
                    self.json(app.tt_hazirlik(int((q.get("id") or ["0"])[0])))
                except ValueError:
                    self.json({"etkinlik": None})
            elif u.path == "/rapor" and q.get("dosya"):
                # Geçmiş antrenmanın kayıtlı raporu (raporlar/ klasöründen; sadece dosya adı)
                ad = os.path.basename((q.get("dosya") or [""])[0])
                yol = os.path.join(gt7_rapor.RAPOR_DIR, ad)
                if ad.startswith("seans_") and ad.endswith(".html") and os.path.isfile(yol):
                    with open(yol, "rb") as f:
                        self.send(200, f.read(), "text/html; charset=utf-8")
                else:
                    self.send(404, "Bu antrenmanın raporu bulunamadı.", "text/plain; charset=utf-8")
            elif u.path == "/rapor":
                # Seans raporu (tek sayfa; telefondan da açılır)
                k = app.koc
                self.send(200, gt7_rapor.rapor_html(k.state if k else {}, gt7_koc.pist_adi(k.state.get("track"))
                                                    if k else "Pist", gt7_koc.viraj_adi), "text/html; charset=utf-8")
            elif u.path == "/api/durum":
                since = int((q.get("son") or ["0"])[0] or 0)
                self.json(app.status(since))
            elif u.path == "/api/pistler":
                found = search(app.catalog, (q.get("q") or [""])[0])[:40]
                self.json([{"id": t["id"], "ad": t["name"], "uzunluk": t["length"],
                            "viraj": len(t["corner_xy"] or []), "kisa": describe(t)} for t in found])
            elif u.path == "/api/ses":
                # Koçun sesi (herkeste aynı: Microsoft Ahmet); olmazsa 503 → arayüz o cümleyi okumaz
                veri = app.sentez((q.get("t") or [""])[0])
                if veri:
                    self.send(200, veri, "audio/mpeg")
                else:
                    self.send(503, gt7_ses.hata or "Ses yok", "text/plain; charset=utf-8")
            elif u.path == "/api/discord":
                self.json(app.discord.bilgi())
            elif u.path == "/api/tt":
                self.json(app.time_trial())
            elif u.path == "/api/karsilastir":
                # İki turu üst üste koyma: ?a=eniyi&b=t5 (parametresiz: sadece seçenekler)
                if not app.koc:
                    self.json({"secenekler": []})
                else:
                    try:
                        self.json(app.koc.karsilastirma((q.get("a") or [None])[0], (q.get("b") or [None])[0]))
                    except Exception as e:
                        self.json({"secenekler": [], "hata": repr(e)})
            elif u.path == "/api/inceleme":
                self.json((app.koc.state.get("inceleme") if app.koc else None) or {})
            elif u.path == "/api/harita":
                k = app.koc
                tt = k.tt_hedef(k.state, k.car) if k else None
                self.json({"html": k.state.get("map_html", "") if k else "",
                           "harita": k.state.get("harita") if k else None,
                           "hedef": k.state.get("hedef") if k else None,
                           "adlar": k.state.get("adlar", {}) if k else {},
                           "altin": {"sure": tt["altin"], "ms": tt["altin_ms"], "id": tt["id"]} if tt else None,
                           "rekor": k.rekor_sure() if k else None,
                           "turlar": (k.state.get("turlar") or [])[::-1] if k else [],
                           "pist": app.track_shape()})
            else:
                self.send(404, "Bulunamadı", "text/plain; charset=utf-8")

        def do_POST(self):
            u = urlparse(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                body = {}
            if u.path == "/api/sec":
                sel = app.choose(body.get("id"))
                self.json({"tamam": True, "pist": sel["name"] if sel else None})
            elif u.path == "/api/ayar":
                eski_kanal = app.ayar().get("discord_kanal")
                ayar = ayar_yaz(**{k: v for k, v in body.items() if isinstance(v, str) and gecerli(k, v)})
                if app.koc:
                    app.koc.set_ayar(ayar)
                app.yerel.ayarla(ayar.get("ses_cihazi"))
                app.ses_yonlendir()
                if ayar.get("discord_kanal") != eski_kanal:
                    app.discord.kanal_degisti()
                self.json(ayar)
            elif u.path == "/api/dagilim":
                # 4 çekerde güç dağıtıcının ön payı, araba başına ({"araba": 1470, "on": 40}; on null = takılı değil)
                gd = dict(ayar_oku().get("guc_dagilimi", {}))
                araba, on = str(body.get("araba") or ""), body.get("on")
                if araba:
                    if isinstance(on, int) and not isinstance(on, bool) and 0 <= on <= 100:
                        gd[araba] = on
                    else:
                        gd.pop(araba, None)
                ayar = ayar_yaz(guc_dagilimi=gd)
                if app.koc:
                    app.koc.set_ayar(ayar)
                self.json(ayar)
            elif u.path == "/api/vites":
                # Koç ekranı: bu arabanın vites türü ({"araba": 1470, "tur": "manuel"/"otomatik"/null = algıla})
                va = dict(ayar_oku().get("vites_araba", {}))
                araba = str(body.get("araba") or "")
                if araba:
                    if body.get("tur") in ("manuel", "otomatik"):
                        va[araba] = body["tur"]
                    else:
                        va.pop(araba, None)
                ayar = ayar_yaz(vites_araba=va)
                if app.koc:
                    app.koc.set_ayar(ayar)
                self.json(ayar)
            elif u.path == "/api/bip":
                if app.koc:
                    app.koc.bip_dene()
                self.json({"tamam": bool(app.koc)})
            elif u.path == "/api/kalibrasyon":
                if app.koc:
                    app.koc.kalibrasyon_baslat()
                self.json({"tamam": bool(app.koc)})
            elif u.path == "/api/sayma":
                if app.koc and body.get("id"):
                    app.koc.tur_sayma(body["id"])
                self.json({"tamam": bool(app.koc)})
            elif u.path == "/api/rekor":
                if app.koc:
                    if body.get("sil"):
                        app.koc.rekor_sil()
                    else:
                        app.koc.rekor_ayarla(bool(body.get("acik")))
                self.json({"tamam": bool(app.koc)})
            elif u.path == "/api/klasor_ac":
                # Kayıt klasörünü bilgisayarda Windows Gezgini ile açar
                tamam = False
                try:
                    os.makedirs(USER_DIR, exist_ok=True)
                    if hasattr(os, "startfile"):
                        os.startfile(USER_DIR)
                        tamam = True
                except OSError:
                    pass
                self.json({"tamam": tamam, "klasor": USER_DIR})
            elif u.path == "/api/ses_dene":
                # "Sesi dene": ses seçilen cihazdan çıkıyorsa koç orada okur
                self.json({"tamam": app.yerel.soyle(str(body.get("metin") or "")[:200], True)})
            elif u.path == "/api/antrenman":
                # {"basla": "serbest"/"tt", "etkinlik": kimlik, "pist_id": ...} ya da {"bitir": true}
                if body.get("bitir"):
                    app.antrenman_bitir()
                else:
                    app.antrenman_baslat("tt" if body.get("basla") == "tt" else "serbest",
                                         body.get("etkinlik"), body.get("pist_id"))
                self.json({"antrenman": app.antrenman_bilgi()})
            elif u.path == "/api/odak":
                # Koç ekranı: odak virajı ({"no": 5} ya da {"no": null})
                no = body.get("no")
                if app.koc:
                    app.koc.odak_ayarla(no if isinstance(no, int) and not isinstance(no, bool) and no > 0 else None)
                self.json({"tamam": bool(app.koc)})
            elif u.path == "/api/hedef_tur":
                # Time Trial hazırlık: {"tip": "rekor", "araba": kod} / {"tip": "eniyi"} / {} (seçim yok)
                if app.koc:
                    app.koc.hedef_tur_ayarla({"tip": body.get("tip"), "araba": str(body.get("araba") or "")}
                                             if body.get("tip") in ("rekor", "eniyi") else {})
                self.json({"tamam": bool(app.koc)})
            elif u.path == "/api/fren_ayar":
                # Rekor turu seçiliyken fren noktası: {"nokta": "rekor"/"benim", "pay": "yok"/"az"/"orta"/"cok"}
                ok = body.get("nokta") in ("rekor", "benim") and body.get("pay") in ("yok", "az", "orta", "cok")
                if app.koc and ok:
                    app.koc.fren_ayar_ayarla({"nokta": body["nokta"], "pay": body["pay"]})
                self.json({"tamam": bool(app.koc and ok)})
            elif u.path == "/api/hedef":
                # {"sure": "1:52.000"} / {"ms": 112000}: bu arabanın hedefi; {"sil": true}
                # Time Trial'dan: {"ms", "etiket": "altin"/"gumus"/"bronz"/"rekor", "etkinlik": kimlik} (pist için)
                #                 {"sil": true, "tt": true}: Time Trial hedefini sil
                if not app.koc:
                    self.json({"tamam": False, "hata": "Önce antrenmanı başlat."})
                elif body.get("sil"):
                    app.koc.hedef_ayarla(None, {} if body.get("tt") else None)
                    self.json({"tamam": True})
                else:
                    ms = body.get("ms") if isinstance(body.get("ms"), int) else gt7_hedef.sure_oku(body.get("sure"))
                    tt = None
                    if body.get("etiket") in gt7_tt.HEDEF_ADLARI:
                        e = gt7_tt.bul(app.catalog, body.get("etkinlik")) if body.get("etkinlik") is not None else None
                        tt = {"etiket": body["etiket"], "etkinlik": body.get("etkinlik"),
                              "bitis": e.get("bitis") if e else None}
                    if ms:
                        app.koc.hedef_ayarla(ms, tt)
                    self.json({"tamam": bool(ms), "hata": None if ms else "Süreyi 1:52.000 gibi yaz."})
            elif u.path == "/api/discord":
                # {"token": "..."} kaydet + bağlan, {"baglan": true}, {"kes": true}, {"dene": true}
                d = app.discord
                if isinstance(body.get("token"), str) and body["token"].strip():
                    d.baslat(body["token"])
                elif body.get("baglan"):
                    d.baslat()
                elif body.get("kes"):
                    d.durdur()
                elif body.get("dene"):
                    if d.bagli:
                        d.soyle("Telsiz denemesi, mühendis hatta.", True)
                        threading.Timer(3.2, lambda: [d.bip(k, gt7_fren_sesi.TONES) or time.sleep(gt7_fren_sesi.BEEP_GAP)
                                                      for k in range(3)]).start()
                        threading.Timer(6.5, lambda: print("Discord denemesi, tanı:", d.tani())).start()
                self.json(d.bilgi())
            elif u.path == "/api/tt_yenile":
                gt7_tt.guncelle(zorla=True)
                self.json({"tamam": True})
            elif u.path == "/api/bul":
                if app.koc:
                    app.koc.ps5_bul()
                self.json({"tamam": bool(app.koc)})
            elif u.path == "/api/ip":
                ip = str(body.get("ip", "")).strip()
                if app.koc and ip:
                    app.koc.set_ip(ip)
                    app.on_message(f"PlayStation adresi deneniyor: {ip}", [], "bilgi")
                self.json({"tamam": bool(app.koc and ip)})
            else:
                self.send(404, "Bulunamadı", "text/plain; charset=utf-8")

    return Handler


BASLIK = "GT7 Türkçe Koç"


def gunluk_ac():
    """EXE konsolsuz çalışır: yazılanlar koc_gunluk.txt'ye gider (sorun olursa bakmak için)."""
    if getattr(sys, "frozen", False) or sys.stdout is None:
        try:
            f = open(os.path.join(USER_DIR, "koc_gunluk.txt"), "w", encoding="utf-8", buffering=1)
            sys.stdout = sys.stderr = f
        except OSError:
            pass


def mesaj_kutusu(metin):
    """Windows'ta küçük bir bilgi kutusu (pencere açılamadığında). Tamam'a basılınca döner."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, metin, BASLIK, 0x40)
        return True
    except Exception:
        return False


def pencere_ac(url):
    """Koç ekranını kendi penceresinde açar; pencere kapanınca döner. Açılamazsa False."""
    try:
        import webview
    except ImportError:
        print("Pencere için pywebview yok, tarayıcı kullanılacak.")
        return False
    # Ses için tıklama beklemesin (WebView2 tarayıcı ayarı)
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--autoplay-policy=no-user-gesture-required")
    try:
        webview.create_window(BASLIK, url, width=1600, height=900, maximized=True,
                              min_size=(900, 600), background_color="#0a0c10")
        print("Pencere açılıyor (WebView2).")
        # Ayarlar (sekme, ses kutuları) kapanınca kaybolmasın: kalıcı depo, EXE'nin yanında
        webview.start(gui="edgechromium" if sys.platform == "win32" else None,
                      private_mode=False, storage_path=os.path.join(USER_DIR, "pencere_verisi"))
        print("Pencere kapandı.")
        return True
    except Exception as e:
        print(f"Pencere açılamadı: {type(e).__name__}: {e}")
        return False


def tarayicida_ac(url, sunucu_bu_surecte):
    webbrowser.open(url)
    if not sunucu_bu_surecte:
        return
    if not mesaj_kutusu("Koç ekranı tarayıcıda açıldı.\n\nKoç arka planda çalışıyor. Kapatmak için Tamam'a bas."):
        # Windows dışı (geliştirme): Ctrl+C ile kapanır
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass


def main():
    gunluk_ac()
    print("=" * 60)
    print("  GT7 Türkçe Koç")
    print("=" * 60)
    url = f"http://localhost:{PORT}"
    try:
        server = ThreadingHTTPServer(("0.0.0.0", PORT), None)
    except OSError:
        # Büyük ihtimalle koç zaten açık: ekranını bir daha aç
        print("Koç zaten açık görünüyor, ekranı açılıyor.")
        if not pencere_ac(url):
            tarayicida_ac(url, False)
        return
    app = App()
    app.koc_baslat()            # koç hep dinler: ana ekrandayken piste çıkınca antrenman kendiliğinden başlar
    server.RequestHandlerClass = make_handler(app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Koç ekranı: {url}")
    tel = phone_url()
    if tel:
        print(f"Aynı Wi-Fi'daki telefondan açmak için: {tel}")
    print(f"Kayıtlar bu klasöre yazılır: {USER_DIR}")
    print("-" * 60)
    if "--tarayici" in sys.argv or not pencere_ac(url):
        tarayicida_ac(url, True)
    # Pencere (ya da bilgi kutusu) kapandı: koç da kapanır
    server.shutdown()
    os._exit(0)


if __name__ == "__main__":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    main()
