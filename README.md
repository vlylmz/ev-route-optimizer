# EV Route Optimizer

Elektrikli araçlar için rota bazlı enerji tüketimi, SOC simülasyonu ve şarj planlama sistemi.

## Çıktılar — Faz 1 → Faz 6

### Faz 1 — Veri temeli ve enerji modeli
- Araç veritabanı: [`app/data/vehicles.json`](app/data/vehicles.json)
- Formül bazlı enerji modeli: [`app/core/energy_model.py`](app/core/energy_model.py)
- SOC simülasyonu: [`app/core/vehicle_simulator.py`](app/core/vehicle_simulator.py)
- Sentetik sürüş verisi üretimi: [`scripts/generate_synthetic_data.py`](scripts/generate_synthetic_data.py) → `app/data/synthetic_drive_data.csv` (5000 satır)
- Birim testler: `tests/test_energy.py`

### Faz 2 — Dış API entegrasyonları
- OSRM rota servisi: [`app/services/routing_service.py`](app/services/routing_service.py)
- Open-Elevation yükseklik / eğim: [`app/services/elevation_service.py`](app/services/elevation_service.py)
- OpenWeather sıcaklık: [`app/services/weather_service.py`](app/services/weather_service.py)
- Open Charge Map istasyonları: [`app/services/charging_service.py`](app/services/charging_service.py)
- Orkestrasyon: [`app/services/route_context_service.py`](app/services/route_context_service.py)
- Her servis için `retry + timeout + fallback mock` + testler.

### Faz 3 — SOC simülasyonu ve optimizasyon
- Segment bazlı simülatör: [`app/core/route_energy_simulator.py`](app/core/route_energy_simulator.py)
- Şarj ihtiyaç analizi: [`app/core/charge_need_analyzer.py`](app/core/charge_need_analyzer.py)
- Şarj durak seçici (çok-kriterli): [`app/core/charging_stop_selector.py`](app/core/charging_stop_selector.py)
- Şarj planlayıcı: [`app/core/charging_planner.py`](app/core/charging_planner.py)
- 3 rota profili (Hızlı / Verimli / Dengeli): [`app/core/route_profiles.py`](app/core/route_profiles.py)
- Çekirdek orkestrasyon: [`app/core/route_planner.py`](app/core/route_planner.py)

### Faz 4 — ML iyileştirme katmanı
- Eğitim scripti: [`ml/train_model.py`](ml/train_model.py) (LightGBM + sklearn Pipeline)
- Değerlendirme: [`ml/evaluate.py`](ml/evaluate.py) (baseline formül vs LightGBM MAE / RMSE / MAPE)
- Servis katmanı: [`ml/model_service.py`](ml/model_service.py) (model yoksa / hata verirse heuristic fallback)
- Çekirdeğe entegrasyon: `RouteEnergySimulator` `model_service` alır, segment bazında ML tahmini kullanır.
- EDA notebook: [`notebooks/eda.ipynb`](notebooks/eda.ipynb)
- Model artefaktı ve rapor dosyası yerel olarak üretilir (`.gitignore`'dadır):
  - `ml/models/lgbm_v1.joblib`
  - `ml/reports/eval_v1.json`

> Not: Çekirdek sistem (enerji modeli + SOC simülasyonu + istasyon seçimi) ML çalışmasa bile ayakta kalacak şekilde tasarlanmıştır.

### Faz 5 — FastAPI MVC backend
- Pydantic v2 şemalar: [`app/api/schemas.py`](app/api/schemas.py)
- DI gövdesi (lifespan → `app.state` → dependency'ler): [`app/api/dependencies.py`](app/api/dependencies.py)
- Controller'lar:
  - [`app/api/controllers/vehicle_controller.py`](app/api/controllers/vehicle_controller.py) — `GET /vehicles`, `GET /vehicles/{id}`
  - [`app/api/controllers/route_controller.py`](app/api/controllers/route_controller.py) — `POST /route`
  - [`app/api/controllers/station_controller.py`](app/api/controllers/station_controller.py) — `GET /stations`
  - [`app/api/controllers/estimate_controller.py`](app/api/controllers/estimate_controller.py) — `POST /estimate-consumption`
  - [`app/api/controllers/optimize_controller.py`](app/api/controllers/optimize_controller.py) — `POST /optimize` (fast / efficient / balanced profilleri)
- Uygulama girişi: [`app/api/main.py`](app/api/main.py) — `lifespan` içinde `ModelService`, `RouteContextService`, `RouteEnergySimulator`, `ChargeNeedAnalyzer`, `ChargingStopSelector`, `ChargingPlanner`, `RouteProfiles`, `OpenChargeMapService` singleton olarak kurulur.
- E2E testler (dependency_overrides ile dış servis mock'lu): [`tests/test_api.py`](tests/test_api.py)
- Postman koleksiyonu: [`postman/ev_route_optimizer.postman_collection.json`](postman/ev_route_optimizer.postman_collection.json)
- CORS middleware — Vite/CRA dev sunucuları için açık (`EV_CORS_ORIGINS` ile override edilebilir)

### Faz 6 — React + TypeScript Frontend
- Stack: **Vite + React 19 + TypeScript**, **Tailwind CSS v4**, **TanStack Query v5**, **react-leaflet**, **axios + zod**
- Dizin: [`frontend/`](frontend)
  - [`frontend/src/App.tsx`](frontend/src/App.tsx) — ana layout + TanStack Query orkestrasyonu
  - [`frontend/src/components/RouteForm.tsx`](frontend/src/components/RouteForm.tsx) — araç seçimi, koordinat, SOC, strateji
  - [`frontend/src/components/MapView.tsx`](frontend/src/components/MapView.tsx) — Leaflet: rota polyline + şarj istasyonu markerleri
  - [`frontend/src/components/ProfileCard.tsx`](frontend/src/components/ProfileCard.tsx) — Hızlı / Verimli / Dengeli profil kartı
  - [`frontend/src/components/ReportPanel.tsx`](frontend/src/components/ReportPanel.tsx) — sonuç özeti + 3 kart
  - [`frontend/src/services/schemas.ts`](frontend/src/services/schemas.ts) — zod şemalar (FastAPI ile birebir uyumlu)
  - [`frontend/src/services/api.ts`](frontend/src/services/api.ts) — axios istemci + runtime validation
  - [`frontend/src/hooks/`](frontend/src/hooks) — `useVehicles`, `useOptimize`, `useRoute`
- Vitest + @testing-library ile 12 komponent/schema testi
- Vite dev-proxy: frontend `localhost:5173` → `/api` → backend `127.0.0.1:8000`

## Kurulum

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux
pip install -r requirements.txt
```

## Çalıştırma

```bash
# Testleri koş
pytest -q

# Sentetik veriyi yeniden üret (isteğe bağlı)
python scripts/generate_synthetic_data.py

# LightGBM modelini eğit -> ml/models/lgbm_v1.joblib
python -m ml.train_model

# Baseline vs model değerlendirmesi -> ml/reports/eval_v1.json
python -m ml.evaluate --out ml/reports/eval_v1.json

# EDA notebook
jupyter notebook notebooks/eda.ipynb

# API sunucusunu başlat (http://127.0.0.1:8000, Swagger: /docs)
uvicorn app.api.main:app --reload
```

### Örnek API çağrıları

```bash
# Sağlık
curl http://127.0.0.1:8000/health

# Araç listesi
curl http://127.0.0.1:8000/vehicles

# Ankara -> İstanbul için 3 profil rota planı
curl -X POST http://127.0.0.1:8000/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "vehicle_id": "tesla_model_y_rwd",
    "start": {"lat": 39.92, "lon": 32.85},
    "end":   {"lat": 41.01, "lon": 28.97},
    "initial_soc_pct": 80,
    "strategies": ["fast", "efficient", "balanced"]
  }'
```

Ortam değişkenleri:
- `EV_VEHICLES_PATH` — araç veritabanı yolu (varsayılan `app/data/vehicles.json`)
- `EV_MODEL_PATH` — ML artefaktı (varsayılan `ml/models/lgbm_v1.joblib`)
- `EV_CORS_ORIGINS` — virgüllü origin listesi (varsayılan: localhost:5173, localhost:3000)
- `OCM_API_KEY` — Open Charge Map API anahtarı (isteğe bağlı)

### Frontend çalıştırma (Faz 6)

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173 — backend zaten 8000'de koşmalı

# Diğer komutlar
npm test               # vitest
npm run typecheck      # tsc -b --noEmit
npm run build          # prod build -> frontend/dist
```

Frontend için env:
- `VITE_API_BASE_URL` — üretimde backend URL'i (default: `/api`, dev'de Vite proxy ile 8000'e yönlenir).

## Proje yapısı

```text
ev-route-optimizer/
├── app/
│   ├── api/           # FastAPI MVC: main, schemas, dependencies, controllers/
│   ├── core/          # Enerji modeli, simülatör, planlayıcı, profiller
│   ├── data/          # vehicles.json, synthetic_drive_data.csv
│   └── services/      # OSRM / Elevation / Weather / OCM istemcileri
├── frontend/          # Vite + React + TS UI (Faz 6)
│   ├── src/
│   │   ├── components/
│   │   ├── hooks/
│   │   └── services/
│   ├── package.json
│   └── vite.config.ts
├── ml/
│   ├── train_model.py
│   ├── evaluate.py
│   └── model_service.py
├── notebooks/
│   └── eda.ipynb
├── postman/
│   └── ev_route_optimizer.postman_collection.json
├── scripts/
│   └── generate_synthetic_data.py
├── tests/             # pytest — core, services, ml, api
├── requirements.txt
└── README.md
```

## Sonraki adım — Faz 7

5 demo senaryosu (kısa/orta/uzun/soğuk hava/düşük SOC), teknik rapor PDF, canlı sunum akışı ve AWS deployment planı.
