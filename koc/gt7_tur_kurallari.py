# -*- coding: utf-8 -*-
"""
GT7 Türkçe Koç - Tur kuralları
Hangi turun referans olabileceğine karar veren ek kurallar. Fikirler gt7-datalogger
belgelerinden (docs.gt7-datalogger.com, "Lap detection & sessions", "Derived channels",
"Fuel & race strategy") alındı, kod bu proje için yazıldı.
"""
FPS = 60
MAX_STEP = 60          # 1 sn'den uzun paket boşluğu tek kare sayılır (duraklatma, menü)
TIME_TOL_MS = 500      # kayıt süresi oyunun tur süresinden en fazla bu kadar sapabilir...
TIME_TOL_RATIO = 0.005  # ...ya da turun %0,5'i (hangisi büyükse)
SPAN_WINDOW = 5        # tur uzunluğu ölçütü: son 5 turun ortancası
SPAN_FULL = 0.97       # 3+ turdan sonra ortancanın %97'sinden kısa tur eksiktir
SPAN_EARLY = 0.93      # 2 turla sadece bariz eksik (%93'ten kısa) yakalanır
LOOSE = frozenset("DGSs")  # toprak, çim, kum, kar (C biçimi teker zemini)
OFF_WHEELS = 3         # 3+ teker gevşek zeminde...
OFF_TICKS = 6          # ...en az 6 paket (~0,1 sn) = pist dışı


class LapClock:
    """Tur saati: oyunun paket numarasından. Duraklatma ve menü süresi tura eklenmez,
    kaybolan paketler ise boşluk kadar zaman sayılır."""

    def __init__(self):
        self.last = None

    def step(self, pid):
        """Her pakette çağrılır; önceki paketten bu yana geçen saniyeyi verir."""
        d = 1 if self.last is None else pid - self.last
        self.last = pid
        return (d if 1 <= d <= MAX_STEP else 1) / FPS


def lap_change_ok(new, cur, on_track, paused):
    """Tur sayacındaki değişiklik gerçek mi? Menü, pit ya da duraklatmadaki
    oynamalar (örn. 6 -> 0 -> 6) turu bölmesin. +1 adımı duraklatılmamışsa her zaman
    geçerli: yarışın bitiş paketinde 'pistte' bayrağı kapanmış olabilir."""
    return (on_track and not paused) or (new == cur + 1 and not paused)


def records(lap_no, total_laps):
    """Bu tur kaydedilir mi? 0 = çıkış turu; yarışta toplam turdan sonraki tur = soğuma turu."""
    return lap_no > 0 and not (total_laps > 0 and lap_no > total_laps)


def note_packet(lap, pkt):
    """Kaydedilen her pakette: teker zemini ve yarış bilgisi."""
    s = pkt.surface_types
    lap.setdefault("loose", []).append(sum(c in LOOSE for c in s) if s else -1)
    lap["lap_no"] = pkt.current_lap
    lap["total_laps"] = pkt.total_laps
    if pkt.total_laps > 0 and pkt.race_position >= 1 and pkt.total_positions >= 2:
        lap["race"] = True


def time_problem(lap, lap_ms):
    """Kayıt süresi oyunun bildirdiği tur süresini tutuyor mu?"""
    rec_ms = (lap["t"][-1] + 1 / FPS) * 1000
    tol = max(TIME_TOL_MS, TIME_TOL_RATIO * lap_ms)
    if lap_ms - rec_ms > tol:
        return (f"turun {(lap_ms - rec_ms) / 1000:.1f} sn'si kaydedilmedi "
                "(pit, bekleme ya da bağlantı kopması)")
    if rec_ms - lap_ms > tol:
        return f"kayıt oyunun tur süresinden {(rec_ms - lap_ms) / 1000:.1f} sn uzun (geri sarma?)"
    return None


def race_start(lap):
    """Yarışın 1. turu ızgaradan başlar, başlangıç çizgisinden değil."""
    return bool(lap.get("race")) and lap.get("lap_no") == 1


def off_track_count(lap):
    """3+ tekerin gevşek zeminde (çim, kum, toprak) kaldığı çıkış sayısı. C biçimi yoksa 0."""
    count, run = 0, 0
    for v in lap.get("loose", []):
        run = run + 1 if v >= OFF_WHEELS else 0
        if run == OFF_TICKS:
            count += 1
    return count


def span_limit(spans):
    """Son turların uzunluğuna göre 'tam tur' alt sınırı (metre). Yetersiz veride None."""
    recent = sorted(spans[-SPAN_WINDOW:])
    n = len(recent)
    if n < 2:
        return None
    med = recent[n // 2] if n % 2 else (recent[n // 2 - 1] + recent[n // 2]) / 2
    return (SPAN_FULL if n >= 3 else SPAN_EARLY) * med


def drop_partial(laps, spans):
    """Ölçüt değiştikçe eski referansları da yeniden yargıla: kısa kalanları çıkar."""
    limit = span_limit(spans)
    if limit is None:
        return 0
    keep = [L for L in laps if L["dist"][-1] >= limit]
    dropped = len(laps) - len(keep)
    laps[:] = keep
    return dropped


TASMA_TICKS = 6        # 1+ teker gevşek zeminde en az 6 paket (~0,1 sn) = taşma


def tasmalar(lap):
    """Tekerlerin çim/kum/toprağa taştığı yerler: [(mesafe m, en fazla kaç teker)]. C biçimi yoksa []."""
    out, run, en = [], 0, 0
    loose, dist = lap.get("loose", []), lap.get("dist", [])
    for i, v in enumerate(loose[:len(dist)]):
        if v >= 1:
            run += 1
            en = max(en, v)
            if run == TASMA_TICKS:
                out.append([dist[i], en])
            elif run > TASMA_TICKS:
                out[-1][1] = en
        else:
            run, en = 0, 0
    return [tuple(o) for o in out]
