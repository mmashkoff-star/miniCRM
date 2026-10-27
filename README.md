# Excel Factory

Личная мини-CRM на FastAPI и SQLite, окно на Tkinter и выгрузка отчётов в Google Таблицы с личного Google-аккаунта (OAuth).

## Состав

| Путь | Назначение |
| --- | --- |
| `backend/` | FastAPI, модели SQLite, CRUD |
| `ui/crm_app.py` | Окно CRM: клиенты, сделки, заказы, задачи |
| `ui/report_app.py` | Генератор демонстрационного отчёта в Google Таблицу |
| `integrations/` | Клиенты Google Drive и Google Sheets |
| `data/` | Файл базы `crm.sqlite3` |
| `credentials/` | JSON-ключи OAuth и сервисного аккаунта |
| `docker-compose.yml` | Запуск API в контейнере |
| `seed_crm.py` | Тестовые данные через HTTP API |
| `.env.example` | Пример переменных окружения |

## Подготовка

Нужны Python 3.11+ и Docker Engine.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

JSON-ключи кладите в `credentials/`. Пути и ID папки Drive для окна CRM сохраняются в `google_gui.txt` (в git не попадает).

## Запуск CRM

Сервер (код смонтирован в контейнер, Watchdog перезапускает uvicorn при правках):

```powershell
docker compose up --build -d
```

API: http://127.0.0.1:8020  
Документация: http://127.0.0.1:8020/docs

Окно:

```powershell
python ui/crm_app.py
```

Остановка API: `docker compose down`.

Порт хоста **8020**, чтобы не пересекаться с другими контейнерами (8000, 8010, 8080, 8100).

Без Docker:

```powershell
python backend/crm.py
```

Тогда в `.env` укажите `CRM_API_URL=http://127.0.0.1:8000`.

## Google в CRM

В шапке окна — кнопка **Google**: OAuth JSON, файл token, ID папки Drive (рядом кнопка «Вставить»). На вкладках с таблицей — **Выгрузить отчёт**: создаётся Google Таблица через Drive API, данные и оформление пишутся через Sheets API.

Авторизация идёт в GUI, не на сервере.

## Тестовые данные

Сервер должен быть запущен. Скрипт очищает базу и пишет по 200 связанных записей (клиент → сделка → заказ и задача):

```powershell
python seed_crm.py
```

## Генератор отчётов для Google Таблиц

```powershell
python ui/report_app.py
```

Цифры в этом отчёте случайные, это указано на листе. Каждый запуск создаёт новый лист, лист из `SHEET_NAME` не меняется.

Проверка API таблиц:

```powershell
python integrations/google_sheets.py
```

Клиент Drive:

```powershell
python integrations/google_drive.py
```

## .env

См. `.env.example`. Основные ключи:

```env
SPREADSHEET_ID=
SHEET_NAME=Invoices
GOOGLE_CREDENTIALS_PATH=credentials/excel-factory-....json
GOOGLE_AUTH=oauth
GOOGLE_OAUTH_CLIENT_SECRET=credentials/client_secret_....json
GOOGLE_OAUTH_TOKEN_PATH=credentials/token.json
DRIVE_FOLDER_ID=
CRM_DB_PATH=data/crm.sqlite3
CRM_API_URL=http://127.0.0.1:8020
```
