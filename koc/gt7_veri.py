# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Hazır oyun bilgileri (veri/ klasörü)
Kaynak: ddm999/gt7info (MIT No Attribution).
- arabalar.json: araba kodu -> "Marka Model" (telemetri arabayı sadece numarayla gönderir)
- pist_bilgi.json: bizim pist kimliğimiz -> resmi viraj sayısı, en uzun düzlük, yükseklik farkı,
  pit yolu kaybı (sn), yağmur olabilir mi. Eşleştirme: uzunluk (%1,5) + ad + ters yön.
Dosya yoksa ya da bozuksa koç bunlarsız çalışır.
"""
import json
import os

from gt7_yol import DATA_DIR

VERI_DIR = os.path.join(DATA_DIR, "veri")
_cache = {}


def _oku(ad):
    if ad not in _cache:
        try:
            with open(os.path.join(VERI_DIR, ad), encoding="utf-8") as f:
                _cache[ad] = json.load(f)
        except (OSError, ValueError):
            _cache[ad] = {}
    return _cache[ad]


def araba_adi(kod):
    """Araba kodunun adı; bilinmiyorsa "araba 1234"."""
    if kod is None:
        return "araba ?"
    return _oku("arabalar.json").get(str(kod)) or f"araba {kod}"


def pist_bilgi(pist_id):
    """Pistin resmi bilgileri (yoksa boş sözlük)."""
    return _oku("pist_bilgi.json").get(str(pist_id or ""), {})


def pist_bilgi_satiri(pist_id):
    """Pist özeti için tek satır (bilgi yoksa None)."""
    b = pist_bilgi(pist_id)
    if not b:
        return None
    parca = [f"resmi {b['viraj']} viraj"]
    if b.get("en_uzun_duzluk_m"):
        parca.append(f"en uzun düzlük {b['en_uzun_duzluk_m'] / 1000:.2f} km")
    if b.get("yukseklik_farki_m") is not None:
        parca.append(f"yükseklik farkı {b['yukseklik_farki_m']:.0f} m")
    if b.get("pit_kaybi_sn"):
        parca.append(f"pite girmek ~{b['pit_kaybi_sn']:.0f} sn kaybettirir")
    parca.append("yağmur yağabilir" if b.get("yagmur") else "yağmur yağmaz")
    return "  Oyun bilgisi: " + ", ".join(parca) + "."
