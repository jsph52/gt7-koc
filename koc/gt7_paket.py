# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Telemetri paketi
GT7 paketinin şifresini çözer (Salsa20, saf Python), temel alanları okur,
PS5'e "veri gönder" (kalp atışı) mesajı yollar. Ek paket gerekmez.
"""
import os
import struct

SEND_PORT = 33739      # PS'e "veri gönder" mesajı bu kapıya gider
RECV_PORT = 33740      # GT7 verileri bu kapıya gönderir
KEY = b"Simulator Interface Packet GT7 ver 0.0"[:32]
from gt7_yol import USER_DIR

IP_FILE = os.path.join(USER_DIR, "ps_ip.txt")


# ---------- Salsa20 şifre çözme (GT7 verisi şifreli gelir) ----------
def _rotl(v, c):
    return ((v << c) & 0xFFFFFFFF) | (v >> (32 - c))


def _salsa20_block(key_words, nonce_words, counter):
    c = (0x61707865, 0x3320646E, 0x79622D32, 0x6B206574)
    s = [c[0], *key_words[:4], c[1], *nonce_words,
         counter & 0xFFFFFFFF, counter >> 32, c[2], *key_words[4:], c[3]]
    x = s[:]
    for _ in range(10):
        for a, b, cc, d in ((0, 4, 8, 12), (5, 9, 13, 1), (10, 14, 2, 6), (15, 3, 7, 11)):
            x[b] ^= _rotl((x[a] + x[d]) & 0xFFFFFFFF, 7)
            x[cc] ^= _rotl((x[b] + x[a]) & 0xFFFFFFFF, 9)
            x[d] ^= _rotl((x[cc] + x[b]) & 0xFFFFFFFF, 13)
            x[a] ^= _rotl((x[d] + x[cc]) & 0xFFFFFFFF, 18)
        for a, b, cc, d in ((0, 1, 2, 3), (5, 6, 7, 4), (10, 11, 8, 9), (15, 12, 13, 14)):
            x[b] ^= _rotl((x[a] + x[d]) & 0xFFFFFFFF, 7)
            x[cc] ^= _rotl((x[b] + x[a]) & 0xFFFFFFFF, 9)
            x[d] ^= _rotl((x[cc] + x[b]) & 0xFFFFFFFF, 13)
            x[a] ^= _rotl((x[d] + x[cc]) & 0xFFFFFFFF, 18)
    return struct.pack("<16I", *((x[i] + s[i]) & 0xFFFFFFFF for i in range(16)))


def salsa20_xor(key, nonce, data):
    kw = struct.unpack("<8I", key)
    nw = struct.unpack("<2I", nonce)
    out = bytearray(len(data))
    for blk in range(0, len(data), 64):
        ks = _salsa20_block(kw, nw, blk // 64)
        chunk = data[blk:blk + 64]
        for i, b in enumerate(chunk):
            out[blk + i] = b ^ ks[i]
    return bytes(out)


# Her veri biçiminin kendi şifre sabiti var (paket uzunluğundan anlaşılır)
XOR_A, XOR_B, XOR_TILDE = 0xDEADBEAF, 0xDEADBEEF, 0x55FABB4F
XOR_BY_SIZE = {296: XOR_A, 316: XOR_B, 344: XOR_TILDE, 368: XOR_B}


def decrypt_packet(data):
    if len(data) < 0x44:
        return None
    iv1 = struct.unpack_from("<I", data, 0x40)[0]
    first = XOR_BY_SIZE.get(len(data), XOR_A)
    for xor in (first, *(x for x in (XOR_A, XOR_B, XOR_TILDE) if x != first)):
        nonce = struct.pack("<II", iv1 ^ xor, iv1)
        dec = salsa20_xor(KEY, nonce, data)
        if struct.unpack_from("<I", dec, 0)[0] == 0x47375330:
            return dec
    return None


# ---------- Paketten değerleri okuma ----------
def parse(p):
    gear_byte = p[0x90]
    best = struct.unpack_from("<i", p, 0x78)[0]
    last = struct.unpack_from("<i", p, 0x7C)[0]
    return {
        "hiz": struct.unpack_from("<f", p, 0x4C)[0] * 3.6,
        "devir": struct.unpack_from("<f", p, 0x3C)[0],
        "vites": gear_byte & 0x0F,
        "onerilen_vites": gear_byte >> 4,
        "gaz": p[0x91] / 2.55,
        "fren": p[0x92] / 2.55,
        "tur": struct.unpack_from("<h", p, 0x74)[0],
        "toplam_tur": struct.unpack_from("<h", p, 0x76)[0],
        "en_iyi": best,
        "son_tur": last,
        "konum": struct.unpack_from("<3f", p, 0x04),
        "araba": struct.unpack_from("<i", p, 0x124)[0],
    }


def sure(ms):
    if ms is None or ms <= 0:
        return "--:--.---"
    return f"{ms // 60000}:{(ms % 60000) / 1000:06.3f}"


def vites_yazi(v):
    return "R" if v == 0 else ("N" if v == 15 else str(v))


# ---------- Bağlantı ----------
def send_heartbeat(sock, target, fmt="A"):
    try:
        sock.sendto(fmt.encode("ascii"), (target, SEND_PORT))
    except OSError:
        pass
