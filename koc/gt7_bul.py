# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - PS5'i ev ağında bulma
Kayıtlı IP cevap vermezse (PS5'in adresi değişmiş olabilir) ev ağındaki bütün adreslere
(aynı /24 ağı, örn. 192.168.68.1-254) kısa "veri gönder" mesajı gönderilir. GT7 hangi adresten
cevap verirse PS5 odur; adres ps_ip.txt'ye yazılır. Ek paket gerekmez.
"""
import socket

from gt7_paket import send_heartbeat

ADIM = 64          # her döngüde kaç adrese mesaj gönderilir (1 sn'de bir döngü = ~4 sn'de tüm ağ)


def yerel_ip():
    """Bu bilgisayarın ev ağındaki adresi (bulunamazsa None). İnternete veri gönderilmez."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def tarama_listesi(ip):
    """Aynı /24 ağındaki adresler + yayın adresleri."""
    if not ip or ip.count(".") != 3:
        return ["255.255.255.255"]
    base = ip.rsplit(".", 1)[0]
    return ["255.255.255.255", f"{base}.255"] + [f"{base}.{i}" for i in range(1, 255)]


class Tarayici:
    """Koçun kendi soketiyle (33740'tan cevap gelsin diye) ağı tarar."""

    def __init__(self):
        self.aktif = False
        self.liste = []
        self.i = 0
        self.ag = None

    def baslat(self):
        ip = yerel_ip()
        self.ag = ip.rsplit(".", 1)[0] + ".x" if ip else None
        self.liste = tarama_listesi(ip)
        self.i = 0
        self.aktif = True

    def durdur(self):
        self.aktif = False

    def adim(self, sock, fmt):
        """Sıradaki adreslere mesaj gönderir; liste bitince baştan başlar (PS5 açılana kadar)."""
        if not self.aktif or not self.liste:
            return
        for _ in range(min(ADIM, len(self.liste))):
            send_heartbeat(sock, self.liste[self.i], fmt)
            self.i = (self.i + 1) % len(self.liste)
