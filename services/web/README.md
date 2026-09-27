# Fire Risk Web

Минимальный React-интерфейс для WEB-01…WEB-06.

## Запуск

```powershell
cd services/web
npm install
npm run dev
```

По умолчанию используется встроенный набор с видимой отметкой `DEMO`.
Для подключения API создайте `.env.local`:

```text
VITE_DEMO_MODE=false
```

Dev-сервер проксирует `/api` на `http://localhost:5000`. Для отдельного
production-хоста задайте `VITE_API_URL` или настройте reverse proxy.

## Проверка

```powershell
npm test -- --run
npm run typecheck
npm run build
```
