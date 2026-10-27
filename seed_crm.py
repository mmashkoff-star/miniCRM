"""Очищает CRM и заново заполняет её через HTTP API.

Сделка всегда ссылается на клиента, заказ и задача — на эту же
пару клиент + сделка.

Нужен запущенный бэкенд:
    docker compose up -d

Запуск из корня проекта:
    python seed_crm.py
"""

from __future__ import annotations

import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

API_BASE = os.getenv("CRM_API_URL", "http://127.0.0.1:8020").rstrip("/")
DB_PATH = Path(__file__).resolve().parent / "data" / "crm.sqlite3"
COUNT = 200
TIMEOUT = 20

FIRST_NAMES = (
    "Александр", "Алексей", "Андрей", "Антон", "Артём", "Борис", "Вадим",
    "Василий", "Виктор", "Владимир", "Денис", "Дмитрий", "Евгений", "Игорь",
    "Иван", "Кирилл", "Константин", "Максим", "Михаил", "Никита", "Николай",
    "Олег", "Павел", "Пётр", "Роман", "Сергей", "Станислав", "Степан",
    "Юрий", "Ярослав", "Анна", "Валерия", "Дарья", "Екатерина", "Елена",
    "Ирина", "Марина", "Мария", "Наталья", "Ольга", "Светлана", "Татьяна",
    "Юлия", "Алина", "Виктория", "Полина",
)
LAST_NAMES = (
    "Иванов", "Петров", "Сидоров", "Смирнов", "Кузнецов", "Попов", "Васильев",
    "Соколов", "Михайлов", "Новиков", "Фёдоров", "Морозов", "Волков", "Алексеев",
    "Лебедев", "Семёнов", "Егоров", "Павлов", "Козлов", "Степанов", "Николаев",
    "Орлов", "Андреев", "Макаров", "Никитин", "Захаров", "Зайцев", "Соловьёв",
    "Борисов", "Яковлев", "Григорьев", "Романов", "Воробьёв", "Сергеев",
    "Кузьмин", "Фролов", "Александров", "Дмитриев", "Королёв", "Гусев",
    "Киселёв", "Ильин", "Максимов", "Поляков", "Сорокин", "Виноградов",
    "Ковалёв", "Белов", "Медведев", "Антонов", "Тарасов", "Жуков", "Баранов",
    "Филиппов", "Комаров", "Давыдов", "Беляев", "Герасимов", "Богданов",
    "Осипов", "Сидорова", "Кузнецова", "Смирнова", "Новикова", "Морозова",
    "Волкова", "Лебедева", "Козлова", "Соколова", "Павлова", "Орлова",
)
PATRONYMICS = (
    "Александрович", "Алексеевич", "Андреевич", "Викторович", "Владимирович",
    "Дмитриевич", "Евгеньевич", "Игоревич", "Иванович", "Николаевич",
    "Петрович", "Сергеевич", "Михайлович", "Павлович", "Александровна",
    "Алексеевна", "Андреевна", "Владимировна", "Дмитриевна", "Ивановна",
    "Николаевна", "Сергеевна", "Петровна", "Михайловна",
)
COMPANY_FORMS = ("ООО", "АО", "ПАО", "ИП", "ЗАО")
COMPANY_CORES = (
    "ЭнергоСнаб", "СибКабель", "УралЩит", "МеталлПром", "ТехноСвет",
    "СеверСтрой", "ВолгаЭлектро", "НеваКомплект", "БайкалСервис", "ДонМонтаж",
    "РусИнжиниринг", "ПромАвтоматика", "ЭлектроМаш", "КабельТорг", "ЩитЭнерго",
    "СтройЛиния", "Городские сети", "Завод РИТМ", "Альфа-Электро", "Вектор Плюс",
    "Магистраль", "Горизонт", "ПолимерПласт", "ТеплоКом", "СветСервис",
    "АгроТех", "Логистик 24", "Форум", "Модуль", "Контур",
    "Ресурс", "Старт", "Лидер", "Практика", "Эталон",
)
DOMAINS = ("mail.ru", "yandex.ru", "gmail.com", "bk.ru", "list.ru", "inbox.ru")
CLIENT_STATUSES = ("lead", "active", "active", "active")
CLIENT_NOTES = (
    "Просит счёт с НДС, работает по оферте.",
    "Предпочитает WhatsApp, на почту отвечает редко.",
    "Постоянный заказчик щитового оборудования.",
    "Нужна отсрочка 14 дней, согласовывает с бухгалтерией.",
    "Закупает кабель партиями под объекты.",
    "Контакт от рекомендации партнёра по тендеру.",
    "Интересует поставка в регион, самовывоз со склада.",
    "Готов закрывать месяц комплектом закрывающих документов.",
)

DEAL_TEMPLATES = (
    "Поставка кабеля {item} для {site}",
    "Щитовое оборудование для {site}",
    "Электромонтаж линии на объекте «{site}»",
    "Комплектация склада {item}",
    "Сервисное обслуживание щитов {site}",
    "Проектирование освещения {site}",
    "Поставка автоматов и контакторов на {site}",
    "Модернизация учёта электроэнергии {site}",
    "Поставка лотков и кабель-каналов для {site}",
    "Аварийный ремонт сети {site}",
)
DEAL_ITEMS = (
    "ВВГнг 3×2,5", "ВВГнг 5×6", "АВВГ 4×120", "NYM 3×1,5",
    "СИП-4 4×16", "КГ 3×25", "лоток 100×50", "кабель-канал 40×25",
)
SITES = (
    "ЖК «Салют»", "цех №3", "склад на Южной", "ТЦ «Галерея»",
    "школа №14", "котельная «Север»", "офис на Ленина", "ферма «Заречье»",
    "БЦ «Горизонт»", "линия фасовки", "подстанция ПС-110", "ангар №2",
    "жилой дом по ул. Мира", "цех покраски", "насосная станция",
)
DEAL_STATUSES = (
    "new", "new", "in_progress", "in_progress", "in_progress",
    "won", "won", "lost", "cancelled",
)
DEAL_DESCRIPTIONS = (
    "КП отправлено, ждём решение закупщика.",
    "Согласована спецификация, осталось закрыть сроки.",
    "Клиент сравнивает с двумя поставщиками.",
    "Нужна поставка партиями в течение квартала.",
    "Объект на паузе до получения разрешения.",
    "Победили по цене, уточняем логистику.",
)

ORDER_TEMPLATES = (
    "Счёт на предоплату 50% — {item}",
    "Отгрузка партия 1: {item}",
    "Отгрузка партия 2: {item}",
    "Дозаказ комплектующих для {site}",
    "Сборка щита учёта для {site}",
    "Доставка на объект «{site}»",
    "Монтаж и пусконаладка {site}",
    "Замена автоматов на {site}",
)
ORDER_STATUSES = (
    "new", "confirmed", "confirmed", "in_progress", "in_progress",
    "paid", "paid", "done", "done", "cancelled",
)
ORDER_DESCRIPTIONS = (
    "Отгрузка со склада в Новосибирске.",
    "Нужны закрывающие: УПД и счёт-фактура.",
    "Самовывоз, пропуск на склад заказать заранее.",
    "Доставка манипулятором, разгрузка силами клиента.",
    "Оплата по счёту в течение трёх банковских дней.",
)

TASK_TEMPLATES = (
    "Перезвонить {name} по КП",
    "Отправить договор {company}",
    "Согласовать сроки поставки на {site}",
    "Подготовить счёт для {company}",
    "Уточнить остатки {item} на складе",
    "Напомнить об оплате счёта {company}",
    "Согласовать схему щита с {name}",
    "Запросить реквизиты у {company}",
    "Назначить встречу на объекте {site}",
    "Проверить закрывающие документы {company}",
    "Отправить фото отгрузки {name}",
    "Уточнить адрес доставки для {site}",
)
TASK_DETAILS = (
    "Клиент просил связаться после 11:00.",
    "Нужен скан с печатью, оригинал отправим позже.",
    "Если не возьмёт трубку — писать в Telegram.",
    "Сверить количество с накладной перед звонком.",
    "Подготовить альтернативу, если позиции нет.",
)

rng = random.Random()


def _translit(text: str) -> str:
    table = str.maketrans(
        {
            "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
            "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
            "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
            "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
            "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
            " ": "", "-": "", "«": "", "»": "",
        }
    )
    return text.lower().translate(table)


def _phone() -> str:
    codes = ("903", "905", "909", "916", "917", "919", "925", "926", "929", "950", "961", "999")
    return f"+7{rng.choice(codes)}{rng.randint(1000000, 9999999)}"


def _when(days_from: int, days_to: int) -> str:
    day = datetime.now() + timedelta(days=rng.randint(days_from, days_to), hours=rng.randint(8, 18))
    return day.replace(minute=rng.choice((0, 15, 30, 45)), second=0, microsecond=0).isoformat(timespec="seconds")


def _amount(low: int, high: int) -> float:
    return float(rng.randint(low // 100, high // 100) * 100)


def _company() -> str:
    form = rng.choice(COMPANY_FORMS)
    core = rng.choice(COMPANY_CORES)
    if form == "ИП":
        return f"ИП {rng.choice(LAST_NAMES)} {rng.choice(FIRST_NAMES)[0]}.{rng.choice(PATRONYMICS)[0]}."
    suffix = rng.choice(("", "", " Групп", " Трейд", " Сибирь", " Урал"))
    return f"{form} «{core}{suffix}»"


def _person() -> tuple[str, str, str]:
    first = rng.choice(FIRST_NAMES)
    last = rng.choice(LAST_NAMES)
    middle = rng.choice(PATRONYMICS)
    if first[-1] in "ая" and last.endswith("ов"):
        last = last + "а"
    elif first[-1] not in "ая" and last.endswith("ова"):
        last = last[:-1]
    return first, last, middle


def build_client() -> dict:
    first, last, middle = _person()
    name = f"{last} {first} {middle}"
    company = _company()
    slug = _translit(f"{first}.{last}") or f"user{rng.randint(1000, 9999)}"
    if rng.random() < 0.55:
        domain = _translit(rng.choice(COMPANY_CORES)) or "mail"
        email = f"{slug}@{domain}.ru"
    else:
        email = f"{slug}{rng.randint(1, 99)}@{rng.choice(DOMAINS)}"
    telegram = None
    if rng.random() < 0.55:
        telegram = f"@{slug[:24]}{rng.randint(1, 99)}"
    notes = rng.choice(CLIENT_NOTES) if rng.random() < 0.7 else None
    return {
        "name": name,
        "company": company,
        "phone": _phone(),
        "email": email,
        "telegram": telegram,
        "notes": notes,
        "status": rng.choice(CLIENT_STATUSES),
    }


def build_deal(client_ids: list[int]) -> dict:
    if not client_ids:
        raise RuntimeError("Сначала нужны клиенты")
    site = rng.choice(SITES)
    item = rng.choice(DEAL_ITEMS)
    title = rng.choice(DEAL_TEMPLATES).format(item=item, site=site)
    return {
        "title": title,
        "client_id": rng.choice(client_ids),
        "amount": _amount(18_000, 2_400_000),
        "currency": "RUB",
        "status": rng.choice(DEAL_STATUSES),
        "description": rng.choice(DEAL_DESCRIPTIONS),
        "expected_close_at": _when(-20, 90),
    }


def build_order(deals: list[dict]) -> dict:
    if not deals:
        raise RuntimeError("Сначала нужны сделки")
    deal = rng.choice(deals)
    site = rng.choice(SITES)
    item = rng.choice(DEAL_ITEMS)
    title = rng.choice(ORDER_TEMPLATES).format(item=item, site=site)
    return {
        "title": title,
        "client_id": deal["client_id"],
        "deal_id": deal["id"],
        "amount": _amount(8_000, 980_000),
        "currency": "RUB",
        "status": rng.choice(ORDER_STATUSES),
        "description": rng.choice(ORDER_DESCRIPTIONS),
        "due_at": _when(-10, 60),
    }


def build_task(clients_by_id: dict[int, dict], deals: list[dict]) -> dict:
    if not deals:
        raise RuntimeError("Сначала нужны сделки")
    deal = rng.choice(deals)
    client = clients_by_id[deal["client_id"]]
    name = client["name"]
    parts = name.split()
    short = parts[1] if len(parts) > 1 else name
    title = rng.choice(TASK_TEMPLATES).format(
        name=short,
        company=client.get("company") or "компании",
        site=rng.choice(SITES),
        item=rng.choice(DEAL_ITEMS),
    )
    return {
        "title": title,
        "description": rng.choice(TASK_DETAILS) if rng.random() < 0.7 else None,
        "client_id": client["id"],
        "deal_id": deal["id"],
        "due_at": _when(-25, 40),
        "is_done": rng.random() < 0.42,
    }


def clear_database() -> None:
    if not DB_PATH.is_file():
        print(f"База ещё не создана: {DB_PATH}", flush=True)
        return
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        for table in ("tasks", "orders", "deals", "clients"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM sqlite_sequence")
        conn.commit()
    finally:
        conn.close()
    print(f"База очищена: {DB_PATH}", flush=True)


def post(session: requests.Session, path: str, payload: dict) -> dict:
    response = session.post(f"{API_BASE}{path}", json=payload, timeout=TIMEOUT)
    if response.status_code >= 400:
        raise SystemExit(
            f"{path} → {response.status_code}: {response.text[:400]}\n"
            f"Тело: {payload}"
        )
    return response.json()


def fill(session: requests.Session, path: str, factory, count: int) -> list[dict]:
    created: list[dict] = []
    for index in range(1, count + 1):
        created.append(post(session, path, factory()))
        if index % 100 == 0 or index == count:
            print(f"  {path}: {index}/{count}", flush=True)
    return created


def main() -> None:
    seed = int(os.getenv("SEED_CRM_SEED", "2026"))
    rng.seed(seed)
    print(f"API: {API_BASE}", flush=True)
    print(f"Записей в каждую таблицу: {COUNT}", flush=True)
    session = requests.Session()
    try:
        health = session.get(f"{API_BASE}/health", timeout=TIMEOUT)
        health.raise_for_status()
    except requests.RequestException as exc:
        raise SystemExit(
            "Нет связи с CRM API. Сначала поднимите сервер:\n"
            "  docker compose up -d\n"
            f"Детали: {exc}"
        ) from exc

    print("Очищаю таблицы", flush=True)
    clear_database()

    print("Клиенты", flush=True)
    clients = fill(session, "/clients", build_client, COUNT)
    client_ids = [item["id"] for item in clients]
    clients_by_id = {item["id"]: item for item in clients}

    print("Сделки", flush=True)
    deals = fill(session, "/deals", lambda: build_deal(client_ids), COUNT)

    print("Заказы", flush=True)
    orders = fill(session, "/orders", lambda: build_order(deals), COUNT)

    print("Задачи", flush=True)
    tasks = fill(session, "/tasks", lambda: build_task(clients_by_id, deals), COUNT)

    print(
        f"Готово: клиентов {len(clients)}, сделок {len(deals)}, "
        f"заказов {len(orders)}, задач {len(tasks)}",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("Остановлено")
