# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Klasör yolları
- Python ile çalışırken: her şey bu dosyanın klasöründe.
- EXE olarak çalışırken: kayıtlar (turlar, referanslar, ayarlar) EXE'nin yanına yazılır,
  hazır veriler (pistler, arayüz) EXE'nin içinden okunur.
- GT7_KOC_KAYIT ortam değişkeni varsa kayıtlar oraya yazılır (sadece testler için).
"""
import os
import sys

if getattr(sys, "frozen", False):
    USER_DIR = os.path.dirname(os.path.abspath(sys.executable))
    DATA_DIR = getattr(sys, "_MEIPASS", USER_DIR)
else:
    USER_DIR = DATA_DIR = os.path.dirname(os.path.abspath(__file__))
# Testler kayıtları geçici bir klasöre yazdırabilsin diye (test_sahte_ps5.py)
USER_DIR = os.environ.get("GT7_KOC_KAYIT") or USER_DIR
