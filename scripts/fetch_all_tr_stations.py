"""
Türkiye'deki tüm EV şarj istasyonlarını birleştirilmiş bir cache'e indirir.

Kaynaklar:
  1) Open Charge Map (OCM) — countrycode=TR + lat slicing (5000 cap aşma)
  2) OpenStreetMap Overpass — amenity=charging_station, bölge dilimleri

Çıktı:  app/data/all_tr_stations.json (OCM-uyumlu format)

Kullanım:
    OCM_API_KEY=xxx python scripts/fetch_all_tr_stations.py
    # veya
    python scripts/fetch_all_tr_stations.py --key xxx --out app/data/all_tr_stations.json
    # OSM'i atlamak için
    python scripts/fetch_all_tr_stations.py --key xxx --no-osm
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


# ============================================================
# OCM (Open Charge Map)
# ============================================================


def fetch_ocm_tr(
    *,
    api_key: str,
    base_url: str = "https://api.openchargemap.io/v3",
    max_per_query: int = 5000,
    timeout: int = 60,
    debug: bool = True,
) -> List[Dict[str, Any]]:
    """OCM'den TR'deki istasyonları çeker (tek sorgu + lat dilimleri union)."""
    headers = {
        "User-Agent": "ev-route-optimizer/0.7 (academic project)",
        "Accept": "application/json",
        "X-API-Key": api_key,
    }

    def _query(params: Dict[str, Any], retries: int = 3) -> List[Dict[str, Any]]:
        for attempt in range(retries):
            try:
                resp = requests.get(
                    f"{base_url}/poi", params=params, headers=headers, timeout=timeout
                )
                if debug:
                    print(f"  → OCM status={resp.status_code}")
                if resp.status_code == 429:
                    wait = 2 ** attempt * 3
                    print(f"  ⚠ rate-limit, bekleniyor {wait}s")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, list) else []
            except Exception as exc:  # noqa: BLE001
                print(f"  ⚠ OCM attempt {attempt + 1} failed: {exc}")
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)
        return []

    base_params = {
        "output": "json",
        "countrycode": "TR",
        "maxresults": max_per_query,
        "compact": "true",
        "verbose": "false",
        "client": "ev-route-optimizer",
    }

    print("📡 OCM tek sorgu (countrycode=TR, maxresults=5000)…")
    main_batch = _query(base_params)
    print(f"  ✓ tek sorgu: {len(main_batch)} kayıt")

    print("📡 OCM bbox dilimleri (5000 cap aşmak için)…")
    sliced: List[Dict[str, Any]] = []
    lat = 35.5
    while lat < 42.5:
        next_lat = min(lat + 0.5, 42.5)
        params = {**base_params, "boundingbox": f"({lat},25.0),({next_lat},45.5)"}
        if debug:
            print(f"  • lat {lat:.1f}–{next_lat:.1f}")
        try:
            sliced.extend(_query(params))
        except Exception as exc:  # noqa: BLE001
            print(f"    ⚠ slice fail: {exc}")
        lat = next_lat
        time.sleep(0.4)
    print(f"  ✓ bbox toplam: {len(sliced)}")

    # Birleştir + dedupe
    seen: set[int] = set()
    unique: List[Dict[str, Any]] = []
    for s in main_batch + sliced:
        sid = s.get("ID")
        if sid is None or sid in seen:
            continue
        seen.add(sid)
        unique.append(s)
    print(f"📦 OCM benzersiz: {len(unique)}")
    return unique


# ============================================================
# OSM (Overpass)
# ============================================================


OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]


def _overpass_query(
    ql: str, *, timeout: int = 180, debug: bool = True
) -> List[Dict[str, Any]]:
    """Overpass mirror'ları arasında deneyerek query gönderir."""
    headers = {
        "User-Agent": "ev-route-optimizer/0.7 (academic project)",
        "Accept": "application/json",
    }
    last_err: Optional[Exception] = None
    for mirror in OVERPASS_MIRRORS:
        for attempt in range(2):
            try:
                resp = requests.post(
                    mirror, data={"data": ql}, headers=headers, timeout=timeout
                )
                if debug:
                    print(
                        f"    → {mirror.split('//')[1].split('/')[0]} "
                        f"status={resp.status_code}"
                    )
                if resp.status_code == 504 or resp.status_code == 429:
                    time.sleep(3)
                    continue
                resp.raise_for_status()
                data = resp.json()
                return data.get("elements", []) or []
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                continue
    if last_err:
        print(f"    ⚠ tüm mirror'lar başarısız: {last_err}")
    return []


def fetch_osm_tr(*, debug: bool = True) -> List[Dict[str, Any]]:
    """
    OSM Overpass'tan Türkiye'deki amenity=charging_station kayıtlarını çeker.
    Yoğun bölgeler (Marmara, İç Anadolu) için ayrıca alt-dilimler kullanılır.
    """
    # Türkiye'yi yoğunluğa göre bölgelere ayır:
    slices = [
        # Marmara — küçük dilimlere böl (İstanbul yoğun)
        ("İstanbul Avrupa", 40.8, 41.4, 27.9, 29.1),
        ("İstanbul Anadolu", 40.8, 41.3, 29.0, 30.0),
        ("Marmara Batı", 39.5, 40.8, 26.0, 28.5),
        ("Marmara Doğu", 39.5, 40.8, 28.5, 31.5),
        # Karadeniz
        ("Karadeniz Batı", 40.5, 42.2, 31.5, 35.5),
        ("Karadeniz Doğu", 40.0, 41.6, 35.5, 41.5),
        # Ege
        ("Ege Kuzey", 38.0, 39.5, 26.0, 29.5),
        ("Ege Güney", 36.5, 38.0, 26.0, 29.5),
        # Akdeniz
        ("Akdeniz Batı", 36.0, 37.8, 29.5, 32.5),
        ("Akdeniz Doğu", 35.8, 37.5, 32.5, 36.5),
        # İç Anadolu
        ("İç Anadolu Kuzey", 38.5, 40.5, 31.0, 35.5),
        ("İç Anadolu Güney", 37.0, 38.5, 31.0, 35.5),
        # Güneydoğu / Doğu
        ("GAP", 36.5, 38.5, 36.5, 41.5),
        ("Doğu Anadolu", 38.0, 41.5, 39.0, 44.5),
        ("Iğdır/Ağrı", 38.0, 41.5, 41.5, 45.0),
    ]

    all_elements: List[Dict[str, Any]] = []
    for name, lat_min, lat_max, lon_min, lon_max in slices:
        ql = (
            f"[out:json][timeout:120];"
            f"(node[\"amenity\"=\"charging_station\"]({lat_min},{lon_min},{lat_max},{lon_max});"
            f"way[\"amenity\"=\"charging_station\"]({lat_min},{lon_min},{lat_max},{lon_max}););"
            f"out center tags;"
        )
        if debug:
            print(f"  • {name}")
        els = _overpass_query(ql, timeout=180, debug=debug)
        all_elements.extend(els)
        if debug:
            print(f"    + {len(els)} kayıt")
        time.sleep(1.5)

    # OSM type+id ile dedupe + Türkiye dışı koordinatları ele
    seen = set()
    unique = []
    for e in all_elements:
        k = (e.get("type"), e.get("id"))
        if k in seen:
            continue
        seen.add(k)
        # OSM'in 'lat'/'lon' alanı var; way'lerde 'center' altında
        lat = e.get("lat")
        lon = e.get("lon")
        if lat is None and "center" in e:
            lat = e["center"].get("lat")
            lon = e["center"].get("lon")
        if lat is None or lon is None:
            continue
        # Türkiye sınırları (yaklaşık)
        if not (35.8 <= lat <= 42.2) or not (25.5 <= lon <= 45.0):
            continue
        # Yunanistan/Bulgaristan'ı kabaca ele: Ege denizinin Yunan adaları
        # için ek filtre: çok kuzeybatı Trakya kısmında bazı kayıtlar
        # Türkiye dışı; isim/operatorde Cyrillic/Yunan harfi varsa atla
        op = (e.get("tags") or {}).get("operator", "") or ""
        if any(ord(c) > 0x0370 and ord(c) < 0x0500 for c in op):
            # Yunan veya Kiril → Türkiye dışı
            continue
        e["_lat"] = float(lat)
        e["_lon"] = float(lon)
        unique.append(e)
    print(f"📦 OSM benzersiz: {len(unique)} (Türkiye filtreli)")
    return unique


def osm_to_ocm_format(osm: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """OSM amenity=charging_station kaydını OCM-uyumlu dict'e çevirir."""
    tags = osm.get("tags") or {}
    lat = osm.get("_lat") or osm.get("lat")
    lon = osm.get("_lon") or osm.get("lon")
    if lat is None or lon is None:
        return None

    operator = tags.get("operator") or tags.get("network")
    name = (
        tags.get("name")
        or tags.get("ref")
        or operator
        or "Şarj İstasyonu"
    )
    addr_parts = [
        tags.get("addr:street"),
        tags.get("addr:housenumber"),
        tags.get("addr:district"),
        tags.get("addr:city"),
        tags.get("addr:postcode"),
    ]
    addr_line = ", ".join(p for p in addr_parts if p) or name

    # Güç bilgisi
    socket_kw = None
    for k, v in tags.items():
        if k.startswith("socket:") and (k.endswith(":output") or k.endswith(":power")):
            try:
                kw = float(str(v).rstrip("kW ").strip())
                if socket_kw is None or kw > socket_kw:
                    socket_kw = kw
            except Exception:  # noqa: BLE001
                continue
    # Bağlantı listesi
    connections: List[Dict[str, Any]] = []
    for k in [
        "socket:type2_combo",
        "socket:type2",
        "socket:chademo",
        "socket:tesla_supercharger_ccs",
        "socket:tesla_supercharger",
        "socket:type1_combo",
    ]:
        if k in tags:
            ct = k.replace("socket:", "").replace("_", " ").title()
            kw_key = f"{k}:output"
            kw_val = tags.get(kw_key)
            try:
                kw = float(str(kw_val).rstrip("kW ").strip()) if kw_val else None
            except Exception:  # noqa: BLE001
                kw = None
            connections.append(
                {
                    "ConnectionType": {"Title": ct},
                    "PowerKW": kw if kw is not None else (socket_kw or 50),
                    "CurrentType": {"Title": "DC"},
                    "Quantity": 1,
                    "Level": {"IsFastChargeCapable": (kw or socket_kw or 0) >= 50},
                    "StatusType": {"Title": "Operational"},
                }
            )
    if not connections:
        connections.append(
            {
                "ConnectionType": {"Title": "Unknown"},
                "PowerKW": socket_kw or 22,
                "CurrentType": {"Title": "AC" if (socket_kw or 22) < 50 else "DC"},
                "Quantity": 1,
                "Level": {"IsFastChargeCapable": (socket_kw or 0) >= 50},
                "StatusType": {"Title": "Operational"},
            }
        )

    # OCM ID çakışmasın diye OSM ID'sine 100M ekle
    ocm_id = 100_000_000 + int(osm.get("id") or 0)

    return {
        "ID": ocm_id,
        "UUID": f"osm-{osm.get('type','node')}-{osm.get('id')}",
        "UsageCost": tags.get("fee") or "Bilgi yok",
        "NumberOfPoints": int(tags.get("capacity", 1) or 1)
        if str(tags.get("capacity", "1")).isdigit()
        else 1,
        "StatusType": {"Title": "Operational", "IsOperational": True},
        "OperatorInfo": {"Title": operator or "OSM"},
        "UsageType": {"Title": "Public" if tags.get("access", "yes") == "yes" else "Private"},
        "AddressInfo": {
            "Title": name,
            "AddressLine1": tags.get("addr:street", ""),
            "Town": tags.get("addr:city") or tags.get("addr:town", ""),
            "StateOrProvince": tags.get("addr:state", ""),
            "Postcode": tags.get("addr:postcode", ""),
            "Latitude": float(lat),
            "Longitude": float(lon),
        },
        "Connections": connections,
        "_source": "osm",
    }


# ============================================================
# Main
# ============================================================


def main() -> int:
    parser = argparse.ArgumentParser(description="OCM + OSM TR istasyonları")
    parser.add_argument(
        "--key",
        default=os.getenv("OCM_API_KEY"),
        help="OCM API key (veya OCM_API_KEY env var)",
    )
    parser.add_argument(
        "--out",
        default="app/data/all_tr_stations.json",
        help="Çıktı dosyası",
    )
    parser.add_argument(
        "--no-osm",
        action="store_true",
        help="OSM kısmını atla (sadece OCM)",
    )
    parser.add_argument(
        "--no-ocm",
        action="store_true",
        help="OCM kısmını atla (sadece OSM)",
    )
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    combined: List[Dict[str, Any]] = []

    if not args.no_ocm:
        if not args.key:
            print(
                "ERROR: --no-ocm verilmediyse OCM_API_KEY gerekli.",
                file=sys.stderr,
            )
            return 1
        print(f"🔑 OCM key: {args.key[:6]}***{args.key[-4:]}")
        ocm_records = fetch_ocm_tr(api_key=args.key)
        for r in ocm_records:
            r["_source"] = "ocm"
        combined.extend(ocm_records)

    if not args.no_osm:
        osm_records = fetch_osm_tr()
        # OSM kayıtlarını OCM formatına dönüştür
        converted = [osm_to_ocm_format(r) for r in osm_records]
        converted = [r for r in converted if r is not None]

        # OSM kayıtlarını OCM ile yakın koordinata göre dedupe (~50 m içinde aynı sayılır)
        from math import radians, sin, cos, atan2, sqrt

        def hav(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
            r = 6371.0
            d_lat = radians(lat2 - lat1)
            d_lon = radians(lon2 - lon1)
            a = (
                sin(d_lat / 2) ** 2
                + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
            )
            return 2 * r * atan2(sqrt(a), sqrt(1 - a))

        # Mevcut OCM kayıtlarının koordinat indeksi
        existing = [
            (
                float(r.get("AddressInfo", {}).get("Latitude", 0)),
                float(r.get("AddressInfo", {}).get("Longitude", 0)),
            )
            for r in combined
            if r.get("AddressInfo")
        ]

        deduped_osm: List[Dict[str, Any]] = []
        threshold_km = 0.05  # 50 m
        for r in converted:
            ai = r.get("AddressInfo", {}) or {}
            lat = float(ai.get("Latitude", 0))
            lon = float(ai.get("Longitude", 0))
            duplicate = False
            for elat, elon in existing:
                if hav(lat, lon, elat, elon) < threshold_km:
                    duplicate = True
                    break
            if not duplicate:
                deduped_osm.append(r)
                existing.append((lat, lon))

        print(
            f"📦 OSM yeni kayıt: {len(deduped_osm)} "
            f"(toplam {len(converted)} OSM, {len(converted) - len(deduped_osm)} OCM ile çakıştı)"
        )
        combined.extend(deduped_osm)

    out_path.write_text(
        json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    size_kb = out_path.stat().st_size / 1024
    print(f"💾 Yazıldı: {out_path} ({size_kb:.1f} KB, {len(combined)} kayıt)")

    # Kaynak özeti
    by_src: Dict[str, int] = {}
    for r in combined:
        by_src[r.get("_source", "?")] = by_src.get(r.get("_source", "?"), 0) + 1
    print(f"   • Kaynaklar: {by_src}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
