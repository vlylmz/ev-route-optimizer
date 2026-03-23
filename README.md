# EV Route Optimizer

Elektrikli araçlar için rota bazlı enerji tüketimi ve şarj planlama sistemi.

## Hafta 1 Çıktıları
- Araç veritabanı (`vehicles.json`)
- Enerji tüketim modeli (`energy_model.py`)
- SOC simülasyonu (`vehicle_simulator.py`)
- Otomatik testler (`tests/test_energy.py`)
- Sentetik sürüş verisi üretimi (`generate_synthetic_data.py`)

## Proje Yapısı
```text
ev-route-optimizer/
├── app/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── energy_model.py
│   │   └── vehicle_simulator.py
│   └── data/
│       ├── vehicles.json
│       └── synthetic_drive_data.csv
├── scripts/
│   └── generate_synthetic_data.py
├── tests/
│   ├── conftest.py
│   └── test_energy.py
├── requirements.txt
└── README.md