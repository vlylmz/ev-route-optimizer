"""Servisler arasi kanonik aratiplar.

Reflective dispatch yerine bu Protocol'leri kullaniyoruz; imzasi uymayan
implementation -> TypeError ile net hata.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, Tuple


Coordinate = Tuple[float, float]


class IRouteContextService(Protocol):
    def build_route_context(
        self,
        start: Coordinate,
        end: Coordinate,
        **opts: Any,
    ) -> Dict[str, Any]:
        ...


class IRouteEnergySimulator(Protocol):
    def simulate(
        self,
        *,
        vehicle: Any,
        route_context: Dict[str, Any],
        start_soc_pct: float,
        use_ml: Optional[bool] = None,
        strategy: str = "balanced",
    ) -> Any:
        ...


class IChargeNeedAnalyzer(Protocol):
    def analyze(
        self,
        *,
        simulation: Any,
        usable_battery_kwh: float,
        reserve_soc_pct: float,
    ) -> Any:
        ...


class IChargingStopSelector(Protocol):
    def select_stop(
        self,
        *,
        vehicle: Dict[str, Any],
        route_context: Dict[str, Any],
        simulation_result: Dict[str, Any],
        charge_need: Dict[str, Any],
        strategy: str = "balanced",
    ) -> Dict[str, Any]:
        ...
