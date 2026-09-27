# Fire Risk API

Минимальный ASP.NET Core API для демонстрационного сценария пожарного риска.

## Запуск

```powershell
docker compose -f compose.api.yml up -d
$env:PYTHONPATH = "services/ml/src"
python -m fire_risk.ml_api
dotnet run --project services/api/FireRisk.Api
```

Нужен Python 3.12+ с зависимостями проекта. Альтернатива `PYTHONPATH` — установка
пакета через `pip install -e services/ml`. По умолчанию используется артефакт
`.artifacts/ml/catboost-synthetic-v1/manifest.json`.

Миграция `Migrations/001_initial.sql` применяется API при старте и добавляет
небольшой demo-объект с каналом без пикета.

## Основные endpoints

- `GET /health`, `/api/dashboard`, `/api/objects`
- `GET /api/objects/{id}`, `/api/objects/{id}/pickets`
- `GET /api/alerts`, `/api/alerts/{id}`
- `POST /api/objects/{id}/predict`
- `POST /api/alerts/{id}/decision`, `/api/alerts/{id}/requests`
- `GET /api/requests`, `PATCH /api/requests/{id}/status`
- `GET /api/sms`, `/api/model/metrics`

Пример прогноза:

```json
{
  "features": {
    "active_state_duration_seconds_5m": 120,
    "malfunction_duration_seconds_5m": 0
  },
  "topK": 5
}
```
