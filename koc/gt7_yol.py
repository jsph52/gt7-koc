# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Klasör yolları
- Python ile çalışırken: her şey bu dosyanın klasöründe.
- EXE olarak çalışırken: kayıtlar (turlar, referanslar, ayarlar) Belgeler\\GT7 Koc
  klasörüne yazılır; EXE nerede durursa dursun kayıtlar aynı yerde kalır.
  EXE'nin yanında eski sürümden kalan kayıtlar varsa ilk açılışta oraya taşınır.
  Belgeler klasörüne yazılamazsa kayıtlar eskisi gibi EXE'nin yanına yazılır.
  Hazır veriler (pistler, arayüz) EXE'nin içinden okunur.
- GT7_KOC_KAYIT ortam değişkeni varsa kayıtlar oraya yazılır (sadece testler için).
"""
import os
import shutil
import sys

KLASOR_ADI = "GT7 Koc"

# Koçun kayıt klasörüne yazdığı dosya ve klasörler (eski sürümden taşınacaklar).
# EXE'nin yanındaki başka dosyalara dokunulmaz.
KAYITLAR = (
    "ayarlar.json", "antrenmanlar.json", "cekis.json", "kalibrasyon.json",
    "tt_rapor.json", "ps_ip.txt", "son_pist.txt", "discord_token.txt",
    "koc_gunluk.txt", "turlar", "referanslar", "raporlar", "pencere_verisi",
)


def _belgeler():
    """Windows'un Belgeler klasörü (OneDrive'a taşınmışsa oradaki)."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            yol = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            # CSIDL_PERSONAL = 5 (Belgeler)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, yol) == 0 and yol.value:
                return yol.value
        except Exception:
            pass
    ev = os.path.expanduser("~")
    for ad in ("Documents", "Belgeler"):
        if os.path.isdir(os.path.join(ev, ad)):
            return os.path.join(ev, ad)
    return None


def _yazilabilir(klasor):
    try:
        os.makedirs(klasor, exist_ok=True)
        deneme = os.path.join(klasor, ".yazma_denemesi")
        with open(deneme, "w") as f:
            f.write("1")
        os.remove(deneme)
        return True
    except Exception:
        return False


def _tasi(eski, yeni):
    """Eski klasördeki koç kayıtlarını yeni klasöre taşır (yenide olanlara dokunmaz)."""
    if os.path.normcase(os.path.abspath(eski)) == os.path.normcase(os.path.abspath(yeni)):
        return
    for ad in KAYITLAR:
        kaynak = os.path.join(eski, ad)
        hedef = os.path.join(yeni, ad)
        if not os.path.exists(kaynak) or os.path.exists(hedef):
            continue
        try:
            shutil.move(kaynak, hedef)
        except Exception:
            # Taşınamazsa (dosya açık vb.) kopyalanır; eski hâli yerinde kalır.
            try:
                if os.path.isdir(kaynak):
                    shutil.copytree(kaynak, hedef)
                else:
                    shutil.copy2(kaynak, hedef)
            except Exception:
                pass


def kayit_klasoru(exe_klasoru):
    belgeler = _belgeler()
    if belgeler:
        klasor = os.path.join(belgeler, KLASOR_ADI)
        if _yazilabilir(klasor):
            _tasi(exe_klasoru, klasor)
            return klasor
    return exe_klasoru


if getattr(sys, "frozen", False):
    _EXE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    DATA_DIR = getattr(sys, "_MEIPASS", _EXE_DIR)
    USER_DIR = None if os.environ.get("GT7_KOC_KAYIT") else kayit_klasoru(_EXE_DIR)
else:
    USER_DIR = DATA_DIR = os.path.dirname(os.path.abspath(__file__))
# Testler kayıtları geçici bir klasöre yazdırabilsin diye (test_sahte_ps5.py)
USER_DIR = os.environ.get("GT7_KOC_KAYIT") or USER_DIR
