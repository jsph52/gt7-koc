# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Çekiş türü (arkadan itiş / önden çekiş / 4 çeker) ve güç dağılımı

Telemetride çekiş türü yok; tekerlerden anlaşılır: tam gazda (düşük viteste, frensiz) çekiş
veren tekerler aracın hızından biraz daha hızlı döner (teker hızı / araç hızı > 1). Her tekerin
"gazsız" hâlindeki oranı ölçüt alınır (lastik çapı farkını siler), tam gazdaki artış ön ve arka
için ayrı ayrı biriktirilir. Ön ve arka birlikte artıyorsa 4 çeker.
Araba başına `cekis.json`'da saklanır; birkaç turda karar verilir. Eşikler tahmini (gerçek oyunda
denenmedi).

Güç dağılımı (ön:arka, ör. 40:60) 4 çeker araçlara takılan "güç dağıtıcı" parçasıyla garajda
ayarlanır; telemetride gelmez, kullanıcı ayarlardan yazar (`ayarlar.json` → `guc_dagilimi`).
"""
import json
import os

from gt7_yol import USER_DIR

DOSYA = os.path.join(USER_DIR, "cekis.json")

GAZ_TAM = 90          # % : bu ve üstü "tam gaz"
GAZ_YOK = 5           # % : bu ve altı (frensiz) "gazsız" ölçüt
EN_AZ_HIZ = 30        # km/s
EN_COK_VITES = 3      # ivmenin (ve teker kaymasının) belirgin olduğu düşük vitesler
EN_AZ_ORNEK = 60      # bir turda bu kadar tam gaz örneği yoksa tur sayılmaz (~1 sn)
KARAR_ORNEK = 240     # toplam bu kadar tam gaz örneği birikince karar verilir (~4 sn)
CEKEN = 0.012         # tekerin tam gazdaki fazladan dönüşü bunu geçerse "çekiş veriyor" (tahmini)
ORAN_4X4 = 0.25       # zayıf aksın artışı güçlü aksın en az bu kadarıysa 4 çeker

ADLAR = {"arka": "arkadan itiş", "on": "önden çekiş", "4x4": "4 çeker"}

DAGILIM_ADIM = 5      # öneri bu kadar puan kaydırır
DAGILIM_EN_ON = 50    # GT7'de güç dağıtıcı 0:100 ile 50:50 arası ayarlanır


def _ortanca(v):
    v = sorted(v)
    return v[len(v) // 2] if v else None


def tur_olc(lap):
    """Bir turdan ölçüm: {"on": ön artış, "arka": arka artış, "n": tam gaz örneği} ya da None."""
    sl = [lap.get(f"slip_{w}") for w in ("fl", "fr", "rl", "rr")]
    th, br, sp, gr = (lap.get(k) for k in ("throttle", "brake", "speed", "gear"))
    if not all(sl) or not th or not br or not sp or not gr:
        return None
    n = min(len(th), len(br), len(sp), len(gr), *(len(c) for c in sl))
    tam, bos = [[] for _ in range(4)], [[] for _ in range(4)]
    for i in range(n):
        if sp[i] is None or sp[i] < EN_AZ_HIZ or (br[i] or 0) > 0:
            continue
        hedef = None
        if th[i] >= GAZ_TAM and 1 <= (gr[i] or 0) <= EN_COK_VITES:
            hedef = tam
        elif th[i] <= GAZ_YOK:
            hedef = bos
        if hedef is None or any(c[i] is None for c in sl):
            continue
        for k in range(4):
            hedef[k].append(sl[k][i])
    if len(tam[0]) < EN_AZ_ORNEK:
        return None
    # Gazsız örnek yoksa ölçüt 1,0 (lastik çapı farkı silinemez ama ön/arka farkı yine görünür)
    artis = [(_ortanca(tam[k]) or 1.0) - (_ortanca(bos[k]) if len(bos[k]) >= 20 else 1.0) for k in range(4)]
    return {"on": (artis[0] + artis[1]) / 2, "arka": (artis[2] + artis[3]) / 2, "n": len(tam[0])}


def karar(on, arka):
    """Ortalama artışlardan çekiş türü ya da None (henüz belli değil)."""
    guclu, zayif = max(on, arka), min(on, arka)
    if guclu < CEKEN:
        return None
    if zayif >= ORAN_4X4 * guclu and zayif >= CEKEN / 2:
        return "4x4"
    return "arka" if arka > on else "on"


def oku():
    try:
        with open(DOSYA, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def ogren(lap, car):
    """Turun ölçümünü arabanın kaydına ekler. Döndürür: (çekiş türü ya da None, yeni mi bulundu)."""
    kayit = oku()
    k = kayit.get(str(car), {"on": 0.0, "arka": 0.0, "n": 0, "tur": None})
    eski = k.get("tur")
    try:
        o = tur_olc(lap)
    except Exception:
        o = None
    if o:
        k["on"] += o["on"] * o["n"]
        k["arka"] += o["arka"] * o["n"]
        k["n"] += o["n"]
        if k["n"] >= KARAR_ORNEK:
            k["tur"] = karar(k["on"] / k["n"], k["arka"] / k["n"]) or k.get("tur")   # belirsizse eskisi kalır
        kayit[str(car)] = k
        _TUR[str(car)] = k.get("tur")
        try:
            with open(DOSYA, "w", encoding="utf-8") as f:
                json.dump(kayit, f, ensure_ascii=False)
        except OSError:
            pass
    return k.get("tur"), bool(k.get("tur")) and k.get("tur") != eski


_TUR = {}   # araba -> çekiş türü (canlı ekran her pakette sorar, dosya bir kez okunur)


def cekis_turu(car):
    if str(car) not in _TUR:
        _TUR[str(car)] = oku().get(str(car), {}).get("tur")
    return _TUR[str(car)]


def dagilim_yazi(on):
    return f"{on}:{100 - on}"


def dagilim_oneri(on, yon):
    """Mevcut ön payından bir adım ileri öneri. yon: "arkaya" ya da "one". Sınırdaysa None."""
    yeni = on - DAGILIM_ADIM if yon == "arkaya" else on + DAGILIM_ADIM
    yeni = max(0, min(max(DAGILIM_EN_ON, on), yeni))
    return None if yeni == on else yeni


def dagilim_cumlesi(on, yon):
    """Garaj önerisi cümlesi. on: kullanıcının yazdığı ön payı ya da None."""
    ne = "arkaya" if yon == "arkaya" else "öne"
    if on is None:
        return (f"Güç dağıtıcı takılıysa gücü biraz {ne} kaydır "
                "(mevcut ayarını Ayarlar'a yazarsan somut değer söylerim).")
    yeni = dagilim_oneri(on, yon)
    if yeni is None:
        return f"Güç dağılımı zaten en {'arkada' if yon == 'arkaya' else 'önde'} ({dagilim_yazi(on)})."
    return f"Güç dağılımını {dagilim_yazi(on)} → {dagilim_yazi(yeni)} yap."
