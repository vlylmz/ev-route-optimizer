"""
Sofistike şarj eğrisi servisi.

Vehicle.charge_curve_hint ('flat_lfp' / 'tapered_nmc') üzerinden SOC bazlı
güç çarpanı eğrisi döner ve şarj süresini (start_soc → target_soc) entegre
eder. Eski sabit "0.55 taper above 80%" yaklaşımını değiştirir.

İki standart profil:
- **flat_lfp**: LFP kimyası (Tesla M3 SR, BYD Han, Atto3, Aksigorta…). Düz
  eğri; %70-90 arası kademeli taper, %90+ keskin düşüş.
- **tapered_nmc**: NMC kimyası (Tesla M3 LR, VW ID.4, BMW i4…). %15'te peak,
  %50'den itibaren kademeli taper, %80 sonrası dik düşüş.

Ek olarak istasyon gücü vehicle accept gücünden büyükse vehicle limit kullanılır.
"""

from __future__ import annotations

from typing import Any, List, Tuple


# (soc_pct, power_factor_of_max_kw)
# 0 - 100 SOC için faktörler; aralarda lineer enterpolasyon yapılır.
CURVE_PROFILES: dict[str, List[Tuple[float, float]]] = {
    "flat_lfp": [
        (0.0, 0.55),
        (10.0, 0.90),
        (20.0, 1.00),
        (50.0, 1.00),
        (70.0, 1.00),
        (80.0, 0.85),
        (90.0, 0.55),
        (95.0, 0.35),
        (100.0, 0.18),
    ],
    "tapered_nmc": [
        (0.0, 0.55),
        (8.0, 0.80),
        (15.0, 1.00),
        (40.0, 1.00),
        (50.0, 0.95),
        (60.0, 0.85),
        (70.0, 0.70),
        (80.0, 0.50),
        (85.0, 0.38),
        (90.0, 0.28),
        (95.0, 0.18),
        (100.0, 0.10),
    ],
}

DEFAULT_PROFILE = "tapered_nmc"


class ChargingCurveService:
    """Vehicle + station gücü → SOC bazlı şarj süresi/eğrisi."""

    def __init__(
        self,
        profiles: dict[str, List[Tuple[float, float]]] | None = None,
    ) -> None:
        self.profiles = profiles or CURVE_PROFILES

    def get_profile(self, vehicle: Any) -> List[Tuple[float, float]]:
        hint = self._get_attr(vehicle, "charge_curve_hint", DEFAULT_PROFILE)
        if not isinstance(hint, str):
            hint = DEFAULT_PROFILE
        return self.profiles.get(hint, self.profiles[DEFAULT_PROFILE])

    def power_factor_at(self, vehicle: Any, soc_pct: float) -> float:
        """SOC için power factor (0..1) — lineer enterpolasyon."""
        curve = self.get_profile(vehicle)
        soc = max(0.0, min(100.0, soc_pct))
        # Aralığı bul
        for i in range(len(curve) - 1):
            soc_a, fac_a = curve[i]
            soc_b, fac_b = curve[i + 1]
            if soc_a <= soc <= soc_b:
                if soc_b == soc_a:
                    return fac_a
                t = (soc - soc_a) / (soc_b - soc_a)
                return fac_a + (fac_b - fac_a) * t
        # Aralık dışı (genelde %100)
        return curve[-1][1]

    def power_at_soc(
        self,
        vehicle: Any,
        station_max_kw: float,
        soc_pct: float,
    ) -> float:
        """Vehicle accept × station limit min."""
        vehicle_max = float(self._get_attr(vehicle, "max_dc_charge_kw", 50.0) or 50.0)
        factor = self.power_factor_at(vehicle, soc_pct)
        vehicle_kw = vehicle_max * factor
        return max(min(station_max_kw, vehicle_kw), 1.0)

    def compute_charge_minutes(
        self,
        vehicle: Any,
        station_kw: float,
        start_soc_pct: float,
        target_soc_pct: float,
        usable_battery_kwh: float,
        *,
        step_pct: float = 0.5,
    ) -> float:
        """Riemann toplam ile şarj süresi (dakika)."""
        if (
            target_soc_pct <= start_soc_pct
            or usable_battery_kwh <= 0
            or station_kw <= 0
        ):
            return 0.0

        total_minutes = 0.0
        soc = start_soc_pct
        while soc < target_soc_pct:
            next_soc = min(soc + step_pct, target_soc_pct)
            mid = (soc + next_soc) / 2
            kw = self.power_at_soc(vehicle, station_kw, mid)
            energy_kwh = (next_soc - soc) / 100.0 * usable_battery_kwh
            total_minutes += (energy_kwh / kw) * 60.0
            soc = next_soc
        return round(total_minutes, 2)

    def simulate_session(
        self,
        vehicle: Any,
        station_kw: float,
        start_soc_pct: float,
        target_soc_pct: float,
        usable_battery_kwh: float,
        *,
        dt_min: float = 0.5,
        max_minutes: float = 600.0,
    ) -> List[dict]:
        """
        Zaman bazlı şarj seansı simulasyonu — grafik için.
        Dönüş: [{time_min, soc_pct, power_kw}, ...]
        """
        if (
            target_soc_pct <= start_soc_pct
            or usable_battery_kwh <= 0
            or station_kw <= 0
        ):
            return []

        points: List[dict] = []
        soc = start_soc_pct
        time_min = 0.0

        # İlk nokta
        points.append(
            {
                "time_min": 0.0,
                "soc_pct": round(soc, 2),
                "power_kw": round(self.power_at_soc(vehicle, station_kw, soc), 1),
            }
        )

        while soc < target_soc_pct and time_min < max_minutes:
            kw = self.power_at_soc(vehicle, station_kw, soc)
            # SOC artış hızı: kW / battery_kwh × dt_min(saat) × 100 (yüzdeye)
            soc_per_min = (kw / usable_battery_kwh) / 60.0 * 100.0
            next_soc = soc + soc_per_min * dt_min
            time_min += dt_min
            if next_soc > target_soc_pct:
                next_soc = target_soc_pct
            points.append(
                {
                    "time_min": round(time_min, 2),
                    "soc_pct": round(next_soc, 2),
                    "power_kw": round(self.power_at_soc(vehicle, station_kw, next_soc), 1),
                }
            )
            soc = next_soc

        return points

    @staticmethod
    def _get_attr(obj: Any, name: str, default: Any) -> Any:
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)
