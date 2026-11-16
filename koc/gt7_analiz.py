# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Tur sonu ek analizleri
Fikirler gt7-datalogger belgelerinden, kod bu proje için yazıldı:
- ters yön: tur, seçilen pistin çizgisinde ters sırayla mı ilerliyor?
- tur özeti: tam gaz / fren / boşta / arka patinaj yüzdesi, en yüksek hız
- tutarlılık: tur süresi sapması ve her tur farklı sürülen virajlar
- tekrarlayan teker olayı: aynı virajda son 3 turun 3'ünde
- tempo düşüşü: son 3 temiz turun ortalaması seansın en iyisinden 0,8 sn yavaş
- fren alışkanlığı: bir virajda son 2 turdur en iyi geçişten 10 m+ aynı yönde sapma
- ıslak pist tahmini (9 Kasım 2026): virajların neredeyse hepsinde kayıp + tur belirgin yavaş + lastikler
  önceki turlardan soğuk (telemetride hava bilgisi yok; eşikler tahmini, gerçek oyunda denenmedi)
"""
import math

from gt7_kopru import de, ye

YON_ADIM_M = 20          # tur bu aralıkla örneklenir
YON_ESIK = -0.5          # puan bunun altındaysa ters yön (puan +1 düz, -1 ters)
TAM_GAZ = 98             # %
FREN_VAR = 5             # %
BOSTA = 1                # % (gaz da fren de bunun altında)
PATINAJ_KAYMA = 1.1
PATINAJ_GAZ = 40
TEKRAR_TUR = 3           # tekrarlayan teker olayı: son 3 turun 3'ünde
TEMPO_DUSUK_MS = 800     # son 3 turun ortalaması en iyiden bu kadar yavaşsa söylenir
TEMPO_TEMIZ_MS = 400     # ... bu kadara inince uyarı temizlenir
FREN_ALISKANLIK_M = 10   # son 2 turun ikisinde de en az bu kadar sapma
TUTARSIZ_SN = 0.08       # virajda bundan büyük standart sapma "tutarsız"
ISLAK_YAVAS = 1.03       # ıslak tahmini: tur en iyiden en az %3 yavaş
ISLAK_VIRAJ_ORAN = 0.8   # ... virajların en az %80'inde 0,03 sn+ kayıp
ISLAK_LASTIK_DUSUS = 5   # ... ve lastik ortalaması önceki turlardan en az bu kadar °C düşük
KURU_YAKIN = 1.02        # ıslak şüphesindeyken temiz tur en iyiye bu kadar yaklaşınca pist kurumuş sayılır


# ---------------- Ters yön ----------------
def yon_puani(path, lap):
    """Turun pist çizgisinde ilerleme yönü: +1'e yakın = çizgiyle aynı, -1'e yakın = ters.
    Çizgi yoksa ya da veri azsa None."""
    if not path or len(path) < 10 or not lap.get("dist"):
        return None
    n = len(path)
    idx, son_d = [], -1e9
    for x, z, d in zip(lap["x"], lap["z"], lap["dist"]):
        if d - son_d < YON_ADIM_M:
            continue
        son_d = d
        idx.append(min(range(n), key=lambda i: (path[i][0] - x) ** 2 + (path[i][1] - z) ** 2))
    ileri = geri = 0
    for a, b in zip(idx, idx[1:]):
        f = b - a
        if f > n / 2:
            f -= n
        elif f < -n / 2:
            f += n
        if f > 0:
            ileri += 1
        elif f < 0:
            geri += 1
    if ileri + geri < 10:
        return None
    return (ileri - geri) / (ileri + geri)


def ters_yon(path, lap):
    p = yon_puani(path, lap)
    return p is not None and p < YON_ESIK


# ---------------- Tur özeti ----------------
def tur_ozeti(lap):
    """{"tam_gaz", "fren", "bosta", "patinaj" (% olarak), "max_hiz" (km/s)}"""
    th, br, sp = lap.get("throttle") or [], lap.get("brake") or [], lap.get("speed") or []
    n = min(len(th), len(br), len(sp))
    if not n:
        return None
    rl, rr = lap.get("slip_rl") or [], lap.get("slip_rr") or []
    pat = 0
    if len(rl) >= n and len(rr) >= n:
        pat = sum(1 for i in range(n) if th[i] >= PATINAJ_GAZ
                  and max(rl[i] or 1, rr[i] or 1) > PATINAJ_KAYMA)
    return {"tam_gaz": 100 * sum(1 for v in th[:n] if v >= TAM_GAZ) / n,
            "fren": 100 * sum(1 for v in br[:n] if v >= FREN_VAR) / n,
            "bosta": 100 * sum(1 for i in range(n) if th[i] < BOSTA and br[i] < BOSTA) / n,
            "patinaj": 100 * pat / n,
            "max_hiz": max(sp[:n])}


def tur_ozeti_satiri(oz):
    if not oz:
        return None
    s = (f"Tur özeti: tam gaz %{oz['tam_gaz']:.0f}, fren %{oz['fren']:.0f}, "
         f"boşta (ne gaz ne fren) %{oz['bosta']:.0f}")
    if oz["patinaj"] >= 0.5:
        s += f", arka patinaj %{oz['patinaj']:.0f}"
    return s + f", en yüksek hız {oz['max_hiz']:.0f} km/s."


# ---------------- Tutarlılık ----------------
def _std(v):
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def tutarlilik(temiz_ms, viraj_gecmisi, n=5):
    """temiz_ms: bu seansın temiz tur süreleri; viraj_gecmisi: [{"v": {no: fark}}].
    Ekran satırları (en az 3 temiz tur yoksa boş)."""
    out = []
    son = temiz_ms[-n:]
    if len(son) >= 3:
        out.append(f"Tutarlılık: son {len(son)} temiz turun standart sapması {_std(son) / 1000:.2f} sn "
                   "(küçüldükçe daha tutarlısın).")
    g = (viraj_gecmisi or [])[-n:]
    if len(g) >= 3:
        sap = {}
        for no in g[-1]["v"]:
            v = [t["v"][no] for t in g if t["v"].get(no) is not None]
            if len(v) >= 3:
                sap[no] = _std(v)
        kotu = sorted((s, no) for no, s in sap.items() if s > TUTARSIZ_SN)[::-1][:2]
        if kotu:
            out.append("Her tur farklı sürdüğün virajlar: "
                       + ", ".join(f"Viraj {no} (±{s:.2f} sn)" for s, no in kotu)
                       + ". Önce buralarda aynı fren ve gaz noktasını tutturmaya çalış.")
    return out


# ---------------- Tekrarlayan teker olayı ----------------
def teker_tekrari(state, olaylar):
    """Aynı virajda son 3 turun 3'ünde de olan kilit/patinaj; her biri bir kez söylenir."""
    turlar = state.setdefault("teker_turlar", [])
    turlar.append({(e["tip"], e["viraj"]) for e in olaylar if e["viraj"]})
    del turlar[:-TEKRAR_TUR]
    soylendi = state.setdefault("teker_soylendi", set())
    soylendi &= turlar[-1]          # kaybolan olay, tekrar ederse yeniden söylenebilir
    out = []
    if len(turlar) < TEKRAR_TUR:
        return out
    for e in olaylar:
        k = (e["tip"], e["viraj"])
        if e["viraj"] and k not in soylendi and all(k in t for t in turlar):
            soylendi.add(k)
            out.append(e)
    return out


# ---------------- Tempo düşüşü ----------------
def tempo(state, temiz_ms):
    """Son 3 temiz tur seansın en iyisinden belirgin yavaşsa bir kez cümle döndürür."""
    if len(temiz_ms) < 4:
        return None
    son3 = temiz_ms[-3:]
    en_iyi = min(temiz_ms)
    if en_iyi in son3:              # pencerede rekor varsa sus
        state["tempo_uyari"] = False
        return None
    fark = sum(son3) / 3 - en_iyi
    if fark <= TEMPO_TEMIZ_MS:
        state["tempo_uyari"] = False
        return None
    if fark > TEMPO_DUSUK_MS and not state.get("tempo_uyari"):
        state["tempo_uyari"] = True
        return (f"Tempon düşüyor, son 3 turda en iyi turundan ortalama {fark / 1000:.1f} saniye geridesin. "
                "Sakin bir turla ritmini bul.")
    return None


# ---------------- Fren alışkanlığı ----------------
def _kayip_metni(kayip):
    if kayip < 0.05:
        return "süreye etkisi az"
    return f"bu virajda tur başına ortalama {kayip:.2f} sn kaybettirdi"


def fren_aliskanligi(state, cmp_res):
    """Son 2 turdur aynı virajda aynı yönde 10 m+ fren sapması ve bunun süreye maliyeti
    (iki turdaki viraj farkının ortalaması). En çok kaybettiren önce.
    Döndürür: (ekran satırları, sesli kısa cümle ya da None). Her alışkanlık bir kez söylenir;
    fren bipi açıkken de söylenir."""
    gec = state.setdefault("fren_gecmis", [])
    gec.append({r["no"]: (r.get("fren_m"), r.get("delta") or 0.0) for r in cmp_res or []})
    del gec[:-2]
    soylendi = state.setdefault("fren_soylendi", set())
    if len(gec) < 2:
        return [], None
    bulunan = []
    for no, (d2, k2) in gec[-1].items():
        d1, k1 = gec[-2].get(no, (None, 0.0))
        if d1 is None or d2 is None or (d1 > 0) != (d2 > 0):
            continue
        en_az = min(abs(d1), abs(d2))
        if en_az > FREN_ALISKANLIK_M:
            kayip = max(0.0, (k1 + k2) / 2)
            bulunan.append((kayip, en_az, no, "geç" if d2 > 0 else "erken"))
    bulunan.sort(reverse=True)
    aktif = {(no, yon) for _, _, no, yon in bulunan}
    soylendi &= aktif
    satirlar = [f"Fren alışkanlığı: Viraj {de(no)} son 2 turdur en iyi geçişinden en az {m:.0f} m {yon} "
                f"frene basıyorsun ({_kayip_metni(k)})." for k, m, no, yon in bulunan[:3]]
    ses = None
    for k, m, no, yon in bulunan:
        if (no, yon) not in soylendi and k >= 0.05:   # zaman kaybettirmeyen alışkanlık sadece ekranda
            soylendi.add((no, yon))
            ses = (f"Viraj {ye(no)} girerken iki turdur frene {yon} basıyorsun, yaklaşık {m:.0f} metre. "
                   + ("Biraz daha geç bas." if yon == "erken" else "Biraz daha erken bas."))
            break
    return satirlar, ses


# ---------------- Islak pist tahmini ----------------
def islak_tur(state, cmp_res, lap_ms, best_ms, lastik_ort):
    """Tutuş düşüşü: neredeyse her virajda kayıp + belirgin yavaş tur + lastikler soğumuş.
    Döner (ekran satırı ya da None, ses ya da None (seansta bir kez), ıslak mı)."""
    onceki = state.setdefault("lastik_turlar", [])
    sonuc = (None, None, False)
    if cmp_res and len(cmp_res) >= 4 and best_ms and lap_ms >= ISLAK_YAVAS * best_ms and onceki and lastik_ort:
        n = sum(1 for r in cmp_res if r["delta"] > 0.03)
        son = onceki[-5:]
        dusus = sum(son) / len(son) - lastik_ort
        if n >= ISLAK_VIRAJ_ORAN * len(cmp_res) and dusus >= ISLAK_LASTIK_DUSUS:
            satir = (f"Tutuş düştü: {len(cmp_res)} virajın {n} tanesinde yavaşsın ve lastikler önceki turlardan "
                     f"{dusus:.0f} °C soğuk. Pist ıslak olabilir; viraj uyarıları pist kuruyana kadar susar.")
            ses = None
            if not state.get("islak_dedi"):
                state["islak_dedi"] = True
                ses = "Bütün virajlarda yavaşladın, lastikler soğudu. Pist ıslak olabilir."
            sonuc = (satir, ses, True)
    if lastik_ort and not sonuc[2]:
        onceki.append(lastik_ort)
        del onceki[:-10]
    return sonuc
