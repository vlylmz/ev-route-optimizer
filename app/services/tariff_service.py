"""
Şarj operatörü tarife servisi — TRY/kWh fiyatları.

Veri:
    app/data/charging_tariffs.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


class TariffService:
    """Operatör adı → kWh fiyatı (TRY)."""

    def __init__(self, data_path: str | Path = "app/data/charging_tariffs.json") -> None:
        self.data_path = Path(data_path)
        self._operators: Dict[str, Dict[str, float]] = {}
        self._default_dc: float = 11.0
        self._default_ac: float = 8.0
        self._currency: str = "TRY"
        self._load()

    def _load(self) -> None:
        if not self.data_path.exists():
            return
        try:
            with self.data_path.open("r", encoding="utf-8") as f:
                data: Dict[str, Any] = json.load(f)
        except Exception:  # noqa: BLE001
            return

        self._operators = data.get("operators", {}) or {}
        self._default_dc = float(data.get("default_dc_try_per_kwh", 11.0))
        self._default_ac = float(data.get("default_ac_try_per_kwh", 8.0))
        self._currency = str(data.get("currency", "TRY"))

    @property
    def currency(self) -> str:
        return self._currency

    def price_per_kwh(
        self,
        operator: Optional[str],
        *,
        is_dc: bool = True,
    ) -> float:
        """Operator için kWh fiyatı (TRY). Operator None/bilinmiyorsa default kullanılır."""
        if not operator:
            return self._default_dc if is_dc else self._default_ac

        # Birebir eşleşme dene
        op_data = self._operators.get(operator)
        if op_data is None:
            # Case-insensitive fallback
            for key, val in self._operators.items():
                if key.casefold() == operator.casefold():
                    op_data = val
                    break

        if op_data is None:
            return self._default_dc if is_dc else self._default_ac

        if is_dc:
            return float(op_data.get("dc_try_per_kwh", self._default_dc))
        return float(op_data.get("ac_try_per_kwh", self._default_ac))

    def estimate_stop_cost(
        self,
        *,
        operator: Optional[str],
        kwh: float,
        is_dc: bool = True,
    ) -> float:
        """Tek bir şarj durağında eklenen kWh için TL maliyet."""
        if kwh <= 0:
            return 0.0
        return round(kwh * self.price_per_kwh(operator, is_dc=is_dc), 2)
