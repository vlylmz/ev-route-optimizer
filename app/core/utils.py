"""Veri normalize yardimcilari - safe_float, pick.

Eskiden hemen her core/services modulunde duplike _safe_float, _pick vardi.
"""

from __future__ import annotations

import math
from typing import Any, Dict


def safe_float(value: Any, default: float = 0.0) -> float:
    """None / TypeError / ValueError / NaN -> default; aksi halde float(value)."""
    try:
        if value is None:
            return default
        result = float(value)
        if math.isnan(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def pick(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """data icinde keys'den ilk bulunan ve None olmayan degeri dondur."""
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default
