"""Окно с парой полей: период, подразделение, ответственный → отчёт в Google Таблице.

Запуск:
    python report_app.py
"""

from __future__ import annotations

import os
import random
import threading
import webbrowser
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, Callable

import tkinter as tk
from tkinter import messagebox, ttk

from google_sheets import GoogleSheetsClient, _load_dotenv

COLS = 9
FONT = "Times New Roman"

NAVY = "#1B3A4B"
GOLD = "#C4A574"
INK = "#2C2C2C"
MUTED = "#5E6A71"
LINE = "#D9D3C7"
PAPER = "#FFFFFF"
ZEBRA = "#F7F4EE"
TOTAL_BG = "#E7EEF1"
NOTE_BG = "#F8F6F1"
WHITE = "#FFFFFF"

STATUS_COLORS = {
    "Выполнено": "#1F7A4D",
    "В работе": "#A86B12",
    "Частично": "#1D4E89",
    "Отменено": "#A33B3B",
}

MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

# name, price_from, price_to, qty_from, qty_to
DEPARTMENTS: dict[str, dict[str, Any]] = {
    "Отдел продаж": {
        "sheet": "Продажи",
        "heading": "Отчёт о продажах",
        "lead": "Документ сводит отгрузки и реализации подразделения «Отдел продаж».",
        "items": [
            ("Кабель ВВГнг 3×2,5", 40, 180, 5, 40),
            ("Автомат 16А", 350, 900, 2, 24),
            ("Щит учёта ЩУ-3", 12000, 28000, 1, 5),
            ("Светильник LED 36 Вт", 700, 2400, 2, 18),
            ("Кабель-канал 40×25", 90, 260, 8, 60),
            ("Розетка скрытая", 120, 450, 4, 30),
            ("Лоток перфорированный", 600, 1800, 2, 16),
            ("Контактор 25А", 1400, 4200, 1, 10),
        ],
    },
    "Логистика": {
        "sheet": "Логистика",
        "heading": "Отчёт по логистике",
        "lead": "Документ сводит перевозки, хранение и складские работы подразделения «Логистика».",
        "items": [
            ("Доставка по городу", 1500, 6000, 1, 8),
            ("Междугородняя перевозка", 8000, 42000, 1, 3),
            ("Хранение паллета", 250, 700, 2, 20),
            ("Погрузочные работы", 800, 3500, 1, 10),
            ("Экспедирование", 2000, 9000, 1, 6),
            ("Возврат тары", 300, 1500, 1, 12),
            ("Срочная доставка", 2500, 11000, 1, 5),
        ],
    },
    "Производство": {
        "sheet": "Производство",
        "heading": "Отчёт о производстве",
        "lead": "Документ сводит производственные операции подразделения «Производство».",
        "items": [
            ("Сборка щита", 6000, 24000, 1, 6),
            ("Монтаж линии", 15000, 60000, 1, 3),
            ("Нарезка кабеля", 400, 1800, 2, 20),
            ("Маркировка жгутов", 250, 900, 4, 30),
            ("Контроль ОТК", 500, 2000, 1, 15),
            ("Пайка узла", 700, 2800, 2, 16),
            ("Настройка привода", 3000, 12000, 1, 6),
        ],
    },
    "Маркетинг": {
        "sheet": "Маркетинг",
        "heading": "Отчёт о маркетинге",
        "lead": "Документ сводит рекламные и оформительские работы подразделения «Маркетинг».",
        "items": [
            ("Контекстная кампания", 8000, 35000, 1, 2),
            ("Макет баннера", 2500, 9000, 1, 4),
            ("Рассылка клиентам", 1500, 6000, 1, 5),
            ("Печать буклетов", 4000, 18000, 1, 3),
            ("Ведение карточек", 2000, 7000, 1, 6),
            ("Фотосъёмка товара", 3000, 12000, 1, 4),
        ],
    },
    "Финансы": {
        "sheet": "Финансы",
        "heading": "Финансовый отчёт",
        "lead": "Документ сводит расчётные и закрывающие операции подразделения «Финансы».",
        "items": [
            ("Сверка с контрагентом", 1500, 6000, 1, 4),
            ("Платёжное поручение", 200, 800, 2, 20),
            ("Закрывающие документы", 800, 3000, 1, 10),
            ("Акт сверки", 500, 2000, 1, 8),
            ("Счёт на оплату", 300, 1200, 2, 15),
            ("Командировочный аванс", 4000, 25000, 1, 3),
        ],
    },
}

COMMON_INTRO = (
    " В реестре — дата, наименование, количество, цена и статус исполнения. "
    "Сумма строки считается как цена, умноженная на количество, и пересчитывается сама, "
    "если поправить число в таблице."
)


def long_date(value: date) -> str:
    return f"{value.day} {MONTHS[value.month - 1]} {value.year} г."


def fmt_money(value: float) -> str:
    rounded = round(float(value) + 1e-9)
    return f"{rounded:,}".replace(",", " ")


def parse_date(text: str) -> date:
    raw = text.strip()
    try:
        return datetime.strptime(raw, "%d.%m.%Y").date()
    except ValueError:
        raise ValueError("Дата должна быть в формате ДД.ММ.ГГГГ") from None


def _pick_price(low: int, high: int) -> int:
    if high <= low:
        return low
    step = 10 if high - low >= 100 else 1
    steps = (high - low) // step
    return low + random.randint(0, steps) * step


def _operation_count(days: int) -> int:
    if days <= 3:
        return random.randint(5, 8)
    if days <= 14:
        return random.randint(7, 12)
    return random.randint(10, 16)


def generate_operations(date_from: date, date_to: date, department: str) -> list[dict[str, Any]]:
    catalog = DEPARTMENTS[department]["items"]
    span = (date_to - date_from).days
    operations = []
    for _ in range(_operation_count(span + 1)):
        name, price_low, price_high, qty_low, qty_high = random.choice(catalog)
        operations.append(
            {
                "date": date_from + timedelta(days=random.randint(0, span)),
                "name": name,
                "qty": random.randint(qty_low, qty_high),
                "price": _pick_price(price_low, price_high),
                "status": random.choices(
                    list(STATUS_COLORS),
                    weights=[68, 16, 10, 6],
                    k=1,
                )[0],
            }
        )
    operations.sort(key=lambda item: (item["date"], item["name"]))
    return operations


def _hex(value: str) -> dict[str, float]:
    raw = value.lstrip("#")
    return {
        "red": int(raw[0:2], 16) / 255,
        "green": int(raw[2:4], 16) / 255,
        "blue": int(raw[4:6], 16) / 255,
    }


def _font(size: int, color: str, *, bold: bool = False, italic: bool = False) -> dict[str, Any]:
    return {
        "fontFamily": FONT,
        "fontSize": size,
        "bold": bold,
        "italic": italic,
        "foregroundColor": _hex(color),
    }


def _check_merges(values: list[list[Any]], merges: list[tuple[int, int, int, int]]) -> None:
    occupied: set[tuple[int, int]] = set()
    for r1, c1, r2, c2 in merges:
        if r2 <= r1 or c2 <= c1:
            raise RuntimeError("Внутренняя ошибка вёрстки: пустое объединение")
        for row in range(r1, r2):
            for col in range(c1, c2):
                if (row, col) in occupied:
                    raise RuntimeError(f"Внутренняя ошибка вёрстки: пересечение ячеек {row + 1}:{col + 1}")
                occupied.add((row, col))
                if (row, col) != (r1, c1) and values[row][col] != "":
                    raise RuntimeError(
                        f"Внутренняя ошибка вёрстки: значение внутри объединения {row + 1}:{col + 1}"
                    )


class BuiltReport:
    def __init__(
        self,
        sheet_title: str,
        values: list[list[Any]],
        format_requests: Callable[[int], list[dict[str, Any]]],
        operations: int,
        total: int,
    ) -> None:
        self.sheet_title = sheet_title
        self.values = values
        self.format_requests = format_requests
        self.operations = operations
        self.total = total


def build_report(
    date_from: date,
    date_to: date,
    department: str,
    responsible: str,
    *,
    today: date | None = None,
) -> BuiltReport:
    if department not in DEPARTMENTS:
        raise ValueError("Выберите подразделение")
    responsible = responsible.strip()
    if len(responsible) < 2:
        raise ValueError("Укажите ответственного")
    if len(responsible) > 80:
        raise ValueError("Слишком длинное имя ответственного")
    if date_to < date_from:
        raise ValueError("Дата начала позже даты окончания")

    profile = DEPARTMENTS[department]
    issued = today or date.today()
    operations = generate_operations(date_from, date_to, department)
    counts = Counter(item["status"] for item in operations)
    total = sum(item["qty"] * item["price"] for item in operations)
    largest = max(operations, key=lambda item: item["qty"] * item["price"])
    days = (date_to - date_from).days + 1
    doc_number = f"ОТ-{issued.year}-{random.randint(1000, 9999)}"
    issued_text = issued.strftime("%d.%m.%Y")

    note = (
        f"Примечание\n"
        f"В период входит {days} дн. Крупнейшая позиция — «{largest['name']}» "
        f"на {fmt_money(largest['qty'] * largest['price'])} ₽ "
        f"({largest['date'].strftime('%d.%m.%Y')}). "
        f"Сумма строки пересчитывается автоматически."
    )
    share = counts["Выполнено"] / len(operations)
    share_text = f"{share * 100:.1f}".replace(".", ",")
    conclusion = (
        f"За период с {long_date(date_from)} по {long_date(date_to)} подразделение "
        f"«{department}» отразило {len(operations)} операций на общую сумму {fmt_money(total)} ₽. "
        f"Средний чек — {fmt_money(round(total / len(operations)))} ₽. "
        f"Доля завершённых операций — {share_text}%."
    )
    if counts["Отменено"]:
        conclusion += f" Отменено операций: {counts['Отменено']}."
    else:
        conclusion += " Отменённых операций нет."
    conclusion += " Существенных расхождений по сводке не выявлено."

    values: list[list[Any]] = []
    merges: list[tuple[int, int, int, int]] = []
    heights: dict[int, int] = {}

    def add_row(cells: dict[int, Any], height: int) -> int:
        row = [""] * COLS
        for col, value in cells.items():
            row[col] = value
        index = len(values)
        values.append(row)
        heights[index] = height
        return index

    def merge(r1: int, c1: int, r2: int, c2: int) -> None:
        if r2 - r1 == 1 and c2 - c1 == 1:
            return
        merges.append((r1, c1, r2, c2))

    letterhead = add_row({0: "EXCEL FACTORY\nслужебный документ"}, 62)
    merge(letterhead, 0, letterhead + 1, COLS)
    gold = add_row({}, 6)
    add_row({}, 16)

    title = add_row({0: profile["heading"]}, 42)
    merge(title, 0, title + 1, COLS)
    subtitle = add_row(
        {0: f"за период с {long_date(date_from)} по {long_date(date_to)}"},
        24,
    )
    merge(subtitle, 0, subtitle + 1, COLS)
    add_row({}, 10)

    number_row = add_row(
        {
            1: "Номер документа",
            3: doc_number,
            4: f"Дата составления: {issued_text}",
        },
        22,
    )
    merge(number_row, 1, number_row + 1, 3)
    merge(number_row, 4, number_row + 1, 8)

    def add_meta(label: str, value: str) -> None:
        index = add_row({1: label, 3: value}, 22)
        merge(index, 1, index + 1, 3)
        merge(index, 3, index + 1, 8)

    add_meta("Подразделение", department)
    add_meta("Ответственный", responsible)
    add_meta("Период", f"с {date_from.strftime('%d.%m.%Y')} по {date_to.strftime('%d.%m.%Y')}")
    meta_last = len(values) - 1
    add_row({}, 12)

    intro = add_row({1: profile["lead"] + COMMON_INTRO}, 92)
    merge(intro, 1, intro + 1, 8)
    add_row({}, 8)

    section_registry = add_row({1: "1.  Реестр операций"}, 28)
    merge(section_registry, 1, section_registry + 1, 8)

    table_header = add_row(
        {1: "№", 2: "Дата", 3: "Наименование", 4: "Кол-во", 5: "Цена", 6: "Сумма", 7: "Статус"},
        30,
    )

    data_start = len(values)
    for number, item in enumerate(operations, start=1):
        excel_row = len(values) + 1
        add_row(
            {
                1: number,
                2: "'" + item["date"].strftime("%d.%m.%Y"),
                3: item["name"],
                4: item["qty"],
                5: item["price"],
                6: f"=E{excel_row}*F{excel_row}",
                7: item["status"],
            },
            26,
        )
    data_end = len(values)
    first_excel = data_start + 1
    last_excel = data_end

    total_row = add_row(
        {
            3: "Итого",
            4: f"=SUM(E{first_excel}:E{last_excel})",
            6: f"=SUM(G{first_excel}:G{last_excel})",
        },
        28,
    )
    add_row({}, 14)

    section_summary = add_row({1: "2.  Сводные показатели"}, 28)
    merge(section_summary, 1, section_summary + 1, 8)

    summary_header = add_row({1: "Показатель", 3: "Значение", 4: note}, 28)
    merge(summary_header, 1, summary_header + 1, 3)

    summary_specs: list[tuple[str, Any, str]] = [
        ("Операций", f"=COUNTA(D{first_excel}:D{last_excel})", "int"),
        ("Оборот", f"=SUM(G{first_excel}:G{last_excel})", "money"),
        ("Средний чек", f"=AVERAGE(G{first_excel}:G{last_excel})", "money"),
        ("Выполнено", counts["Выполнено"], "int"),
        ("В работе", counts["В работе"], "int"),
        ("Частично", counts["Частично"], "int"),
        ("Отменено", counts["Отменено"], "int"),
        ("Доля выполнения", share, "percent"),
    ]
    summary_rows: list[tuple[int, str]] = []
    for label, value, kind in summary_specs:
        index = add_row({1: label, 3: value}, 24)
        merge(index, 1, index + 1, 3)
        summary_rows.append((index, kind))
    summary_last = len(values) - 1
    merge(summary_header, 4, summary_last + 1, 8)
    add_row({}, 14)

    section_close = add_row({1: "3.  Заключение"}, 28)
    merge(section_close, 1, section_close + 1, 8)
    conclusion_row = add_row({1: conclusion}, 112)
    merge(conclusion_row, 1, conclusion_row + 1, 8)
    add_row({}, 16)

    sign_name = add_row({1: "Составил", 3: responsible}, 24)
    merge(sign_name, 1, sign_name + 1, 3)
    merge(sign_name, 3, sign_name + 1, 8)
    sign_role = add_row({3: f"ответственный, {department}"}, 20)
    merge(sign_role, 3, sign_role + 1, 8)
    sign_line = add_row({1: "Подпись", 3: "______________________________"}, 28)
    merge(sign_line, 1, sign_line + 1, 3)
    merge(sign_line, 3, sign_line + 1, 8)
    add_row({}, 18)

    footer = add_row(
        {0: "Сформировано автоматически в Excel Factory. Показатели демонстрационные."},
        22,
    )
    merge(footer, 0, footer + 1, COLS)

    if any(len(row) != COLS for row in values):
        raise RuntimeError("Внутренняя ошибка вёрстки: разная длина строк")
    _check_merges(values, merges)

    statuses = [(data_start + offset, item["status"]) for offset, item in enumerate(operations)]
    section_rows = (section_registry, section_summary, section_close)
    meta_first = number_row

    def format_requests(sheet_id: int) -> list[dict[str, Any]]:
        requests: list[dict[str, Any]] = []

        def grid(r1: int, c1: int, r2: int, c2: int) -> dict[str, int]:
            return {
                "sheetId": sheet_id,
                "startRowIndex": r1,
                "endRowIndex": r2,
                "startColumnIndex": c1,
                "endColumnIndex": c2,
            }

        def paint(r1: int, c1: int, r2: int, c2: int, fmt: dict[str, Any]) -> None:
            requests.append(
                {
                    "repeatCell": {
                        "range": grid(r1, c1, r2, c2),
                        "cell": {"userEnteredFormat": fmt},
                        "fields": ",".join(f"userEnteredFormat.{key}" for key in fmt),
                    }
                }
            )

        def runs(row: int, col: int, items: list[dict[str, Any]]) -> None:
            requests.append(
                {
                    "repeatCell": {
                        "range": grid(row, col, row + 1, col + 1),
                        "cell": {"textFormatRuns": items},
                        "fields": "textFormatRuns",
                    }
                }
            )

        def edges(r1: int, c1: int, r2: int, c2: int, **sides: dict[str, Any]) -> None:
            requests.append({"updateBorders": {"range": grid(r1, c1, r2, c2), **sides}})

        solid = {"style": "SOLID", "color": _hex(LINE)}
        navy_line = {"style": "SOLID_MEDIUM", "color": _hex(NAVY)}
        gold_line = {"style": "SOLID_MEDIUM", "color": _hex(GOLD)}

        for index, width in enumerate((18, 48, 102, 206, 68, 96, 114, 116, 18)):
            requests.append(
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": index,
                            "endIndex": index + 1,
                        },
                        "properties": {"pixelSize": width},
                        "fields": "pixelSize",
                    }
                }
            )
        for index, height in heights.items():
            requests.append(
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "startIndex": index,
                            "endIndex": index + 1,
                        },
                        "properties": {"pixelSize": height},
                        "fields": "pixelSize",
                    }
                }
            )

        for r1, c1, r2, c2 in merges:
            requests.append(
                {
                    "mergeCells": {
                        "range": grid(r1, c1, r2, c2),
                        "mergeType": "MERGE_ALL",
                    }
                }
            )

        paint(
            0,
            0,
            len(values),
            COLS,
            {
                "backgroundColor": _hex(PAPER),
                "verticalAlignment": "MIDDLE",
                "textFormat": _font(11, INK),
                "wrapStrategy": "CLIP",
            },
        )
        paint(
            letterhead,
            0,
            letterhead + 1,
            COLS,
            {
                "backgroundColor": _hex(NAVY),
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP",
                "textFormat": _font(18, WHITE, bold=True),
            },
        )
        runs(
            letterhead,
            0,
            [
                {"startIndex": 0, "format": _font(18, WHITE, bold=True)},
                {"startIndex": len("EXCEL FACTORY\n"), "format": _font(10, "#F3E6C8")},
            ],
        )
        paint(gold, 0, gold + 1, COLS, {"backgroundColor": _hex(GOLD)})
        paint(
            title,
            0,
            title + 1,
            COLS,
            {
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "textFormat": _font(22, NAVY, bold=True),
            },
        )
        paint(
            subtitle,
            0,
            subtitle + 1,
            COLS,
            {
                "horizontalAlignment": "CENTER",
                "textFormat": _font(12, MUTED, italic=True),
            },
        )
        paint(
            meta_first,
            1,
            meta_last + 1,
            3,
            {"textFormat": _font(10, MUTED), "horizontalAlignment": "LEFT"},
        )
        paint(
            meta_first,
            3,
            meta_last + 1,
            8,
            {"textFormat": _font(11, INK, bold=True), "horizontalAlignment": "LEFT"},
        )
        paint(
            number_row,
            4,
            number_row + 1,
            8,
            {
                "textFormat": _font(10, MUTED),
                "horizontalAlignment": "RIGHT",
                "verticalAlignment": "MIDDLE",
            },
        )
        edges(meta_last, 1, meta_last + 1, 8, bottom=gold_line)

        paint(
            intro,
            1,
            intro + 1,
            8,
            {
                "wrapStrategy": "WRAP",
                "verticalAlignment": "TOP",
                "horizontalAlignment": "LEFT",
                "textFormat": _font(11, INK),
            },
        )
        for row in section_rows:
            paint(
                row,
                1,
                row + 1,
                8,
                {
                    "verticalAlignment": "BOTTOM",
                    "textFormat": _font(14, NAVY, bold=True),
                },
            )
            edges(row, 1, row + 1, 8, bottom=navy_line)

        paint(
            table_header,
            1,
            table_header + 1,
            8,
            {
                "backgroundColor": _hex(NAVY),
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "textFormat": _font(10, WHITE, bold=True),
                "padding": {"top": 4, "bottom": 4, "left": 6, "right": 6},
            },
        )
        paint(
            table_header,
            3,
            table_header + 1,
            4,
            {
                "horizontalAlignment": "LEFT",
                "textFormat": _font(10, WHITE, bold=True),
                "padding": {"left": 6, "right": 6},
            },
        )
        for offset in range(data_end - data_start):
            if offset % 2 == 1:
                paint(data_start + offset, 1, data_start + offset + 1, 8, {"backgroundColor": _hex(ZEBRA)})

        alignments = {1: "CENTER", 2: "CENTER", 3: "LEFT", 4: "RIGHT", 5: "RIGHT", 6: "RIGHT", 7: "CENTER"}
        for col, align in alignments.items():
            paint(
                data_start,
                col,
                total_row + 1,
                col + 1,
                {
                    "horizontalAlignment": align,
                    "verticalAlignment": "MIDDLE",
                    "textFormat": _font(10, INK),
                    "padding": {"left": 6, "right": 8},
                },
            )
        for row, status in statuses:
            paint(
                row,
                7,
                row + 1,
                8,
                {
                    "horizontalAlignment": "CENTER",
                    "textFormat": _font(10, STATUS_COLORS[status], bold=True),
                },
            )
        paint(
            data_start,
            4,
            total_row + 1,
            5,
            {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}, "horizontalAlignment": "RIGHT"},
        )
        paint(
            data_start,
            5,
            data_end,
            7,
            {
                "numberFormat": {"type": "NUMBER", "pattern": '#,##0" ₽"'},
                "horizontalAlignment": "RIGHT",
            },
        )
        paint(
            total_row,
            1,
            total_row + 1,
            8,
            {
                "backgroundColor": _hex(TOTAL_BG),
                "textFormat": _font(10, NAVY, bold=True),
            },
        )
        paint(
            total_row,
            6,
            total_row + 1,
            7,
            {
                "numberFormat": {"type": "NUMBER", "pattern": '#,##0" ₽"'},
                "horizontalAlignment": "RIGHT",
                "textFormat": _font(10, NAVY, bold=True),
            },
        )
        edges(
            table_header,
            1,
            total_row + 1,
            8,
            top=navy_line,
            bottom=navy_line,
            left=navy_line,
            right=navy_line,
            innerHorizontal=solid,
            innerVertical=solid,
        )
        edges(total_row, 1, total_row + 1, 8, top=navy_line)

        paint(
            summary_header,
            1,
            summary_header + 1,
            4,
            {
                "backgroundColor": _hex(NAVY),
                "horizontalAlignment": "CENTER",
                "textFormat": _font(10, WHITE, bold=True),
            },
        )
        for index, kind in summary_rows:
            if (index - summary_rows[0][0]) % 2 == 1:
                paint(index, 1, index + 1, 4, {"backgroundColor": _hex(ZEBRA)})
            paint(
                index,
                1,
                index + 1,
                3,
                {"textFormat": _font(10, INK), "horizontalAlignment": "LEFT", "padding": {"left": 8}},
            )
            value_fmt: dict[str, Any] = {
                "textFormat": _font(10, NAVY, bold=True),
                "horizontalAlignment": "RIGHT",
                "padding": {"right": 8},
            }
            if kind == "money":
                value_fmt["numberFormat"] = {"type": "NUMBER", "pattern": '#,##0" ₽"'}
            elif kind == "percent":
                value_fmt["numberFormat"] = {"type": "PERCENT", "pattern": "0.0%"}
            else:
                value_fmt["numberFormat"] = {"type": "NUMBER", "pattern": "#,##0"}
            paint(index, 3, index + 1, 4, value_fmt)
        edges(
            summary_header,
            1,
            summary_last + 1,
            4,
            top=navy_line,
            bottom=navy_line,
            left=navy_line,
            right=navy_line,
            innerHorizontal=solid,
            innerVertical=solid,
        )
        paint(
            summary_header,
            4,
            summary_last + 1,
            8,
            {
                "backgroundColor": _hex(NOTE_BG),
                "wrapStrategy": "WRAP",
                "verticalAlignment": "TOP",
                "horizontalAlignment": "LEFT",
                "textFormat": _font(10, INK),
                "padding": {"top": 10, "bottom": 10, "left": 12, "right": 12},
            },
        )
        runs(
            summary_header,
            4,
            [
                {"startIndex": 0, "format": _font(11, NAVY, bold=True)},
                {"startIndex": len("Примечание\n"), "format": _font(10, INK)},
            ],
        )
        edges(
            summary_header,
            4,
            summary_last + 1,
            8,
            top=gold_line,
            bottom=gold_line,
            left=gold_line,
            right=gold_line,
        )

        paint(
            conclusion_row,
            1,
            conclusion_row + 1,
            8,
            {
                "wrapStrategy": "WRAP",
                "verticalAlignment": "TOP",
                "textFormat": _font(11, INK),
            },
        )
        paint(sign_name, 1, sign_name + 1, 3, {"textFormat": _font(10, MUTED)})
        paint(sign_name, 3, sign_name + 1, 8, {"textFormat": _font(12, INK, bold=True)})
        paint(sign_role, 3, sign_role + 1, 8, {"textFormat": _font(10, MUTED, italic=True)})
        paint(sign_line, 1, sign_line + 1, 3, {"textFormat": _font(10, MUTED)})
        paint(
            sign_line,
            3,
            sign_line + 1,
            8,
            {"textFormat": _font(12, INK), "verticalAlignment": "BOTTOM"},
        )
        paint(
            footer,
            0,
            footer + 1,
            COLS,
            {
                "horizontalAlignment": "CENTER",
                "textFormat": _font(9, MUTED, italic=True),
            },
        )

        requests.append(
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "tabColor": _hex(NAVY),
                        "gridProperties": {
                            "hideGridlines": True,
                            "rowCount": len(values),
                            "columnCount": COLS,
                        },
                    },
                    "fields": (
                        "tabColor,gridProperties.hideGridlines,gridProperties.rowCount,"
                        "gridProperties.columnCount"
                    ),
                }
            }
        )
        return requests

    return BuiltReport(
        sheet_title=f"{profile['sheet']} {doc_number}",
        values=values,
        format_requests=format_requests,
        operations=len(operations),
        total=total,
    )


def _sheet_range(title: str, cell: str = "A1") -> str:
    escaped = title.replace("'", "''")
    return f"'{escaped}'!{cell}"


def _unique_title(existing: set[str], base: str) -> str:
    if base not in existing:
        return base
    number = 2
    while f"{base} ({number})" in existing:
        number += 1
    return f"{base} ({number})"


def make_client() -> GoogleSheetsClient:
    _load_dotenv()
    spreadsheet_id = os.getenv("SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        raise RuntimeError(
            "В .env не указан SPREADSHEET_ID. Его можно взять из адреса таблицы."
        )
    return GoogleSheetsClient(
        spreadsheet_id=spreadsheet_id,
        credentials_path=os.getenv("GOOGLE_CREDENTIALS_PATH") or None,
        default_sheet=os.getenv("SHEET_NAME", "Sheet1"),
    )


class PublishResult:
    def __init__(self, title: str, url: str, operations: int, total: int) -> None:
        self.title = title
        self.url = url
        self.operations = operations
        self.total = total


def publish_report(
    date_from: date,
    date_to: date,
    department: str,
    responsible: str,
    *,
    client: GoogleSheetsClient | None = None,
) -> PublishResult:
    sheets = client or make_client()
    report = build_report(date_from, date_to, department, responsible)
    title = _unique_title(set(sheets.list_sheets()), report.sheet_title)
    created = sheets.create_sheet(title)
    sheet_id = int(created["replies"][0]["addSheet"]["properties"]["sheetId"])
    try:
        sheets.update(_sheet_range(title), report.values, value_input_option="USER_ENTERED")
        sheets.batch_requests(report.format_requests(sheet_id))
    except Exception:
        try:
            sheets.batch_requests([{"deleteSheet": {"sheetId": sheet_id}}])
        except Exception:
            pass
        raise
    url = f"https://docs.google.com/spreadsheets/d/{sheets.spreadsheet_id}/edit#gid={sheet_id}"
    return PublishResult(title, url, report.operations, report.total)


class ReportApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Генератор отчётов")
        self.configure(bg="#F3EFE6")
        self._busy = False
        self._build()
        self._center()

    def _build(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "App.TCombobox",
            fieldbackground="#F7F5F1",
            background="#F7F5F1",
            arrowcolor=NAVY,
            bordercolor="#E0DBD2",
            lightcolor="#F7F5F1",
            darkcolor="#E0DBD2",
            padding=6,
        )

        card = tk.Frame(self, bg=WHITE, padx=28, pady=24)
        card.pack(fill="both", expand=True, padx=18, pady=18)

        tk.Label(
            card,
            text="Генератор отчётов",
            bg=WHITE,
            fg=NAVY,
            font=("Segoe UI", 18, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Frame(card, bg=GOLD, height=3).pack(fill="x", pady=(8, 10))
        tk.Label(
            card,
            text="Укажите период и два поля. Реестр, суммы и оформление\nприложение заполнит само и запишет на новый лист.",
            bg=WHITE,
            fg=MUTED,
            font=("Segoe UI", 10),
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(0, 16))

        form = tk.Frame(card, bg=WHITE)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        today = date.today()
        self.date_from_var = tk.StringVar(value=today.replace(day=1).strftime("%d.%m.%Y"))
        self.date_to_var = tk.StringVar(value=today.strftime("%d.%m.%Y"))
        self.department_var = tk.StringVar(value="Отдел продаж")
        self.responsible_var = tk.StringVar()

        tk.Label(form, text="Период", bg=WHITE, fg=INK, font=("Segoe UI", 11), anchor="w").grid(
            row=0, column=0, sticky="w", pady=7
        )
        period = tk.Frame(form, bg=WHITE)
        period.grid(row=0, column=1, sticky="ew", pady=7)
        self._entry(period, self.date_from_var, 12).pack(side="left")
        tk.Label(period, text="—", bg=WHITE, fg=MUTED, font=("Segoe UI", 11)).pack(side="left", padx=8)
        self._entry(period, self.date_to_var, 12).pack(side="left")
        tk.Label(
            period,
            text="ДД.ММ.ГГГГ",
            bg=WHITE,
            fg="#A3988C",
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(10, 0))

        tk.Label(form, text="Подразделение", bg=WHITE, fg=INK, font=("Segoe UI", 11), anchor="w").grid(
            row=1, column=0, sticky="w", pady=7
        )
        department = ttk.Combobox(
            form,
            textvariable=self.department_var,
            values=list(DEPARTMENTS),
            state="readonly",
            font=("Segoe UI", 11),
            style="App.TCombobox",
            width=28,
        )
        department.grid(row=1, column=1, sticky="ew", pady=7)

        tk.Label(form, text="Ответственный", bg=WHITE, fg=INK, font=("Segoe UI", 11), anchor="w").grid(
            row=2, column=0, sticky="w", pady=7
        )
        name = self._entry(form, self.responsible_var, 28)
        name.grid(row=2, column=1, sticky="ew", pady=7)
        name.focus_set()

        self.button = tk.Button(
            card,
            text="Сформировать отчёт",
            command=self._on_submit,
            bg=NAVY,
            fg=WHITE,
            activebackground="#142B38",
            activeforeground=WHITE,
            relief="flat",
            font=("Segoe UI", 11, "bold"),
            cursor="hand2",
            padx=14,
            pady=8,
        )
        self.button.pack(fill="x", pady=(18, 12))

        self.status_var = tk.StringVar(
            value="Новый лист появится в таблице из .env. Уже существующие листы не изменяются."
        )
        tk.Label(
            card,
            textvariable=self.status_var,
            bg=WHITE,
            fg=MUTED,
            font=("Segoe UI", 9),
            justify="left",
            anchor="nw",
            wraplength=460,
            height=3,
        ).pack(fill="x")

        self.bind("<Return>", lambda _event: self._on_submit())

    def _entry(self, parent: tk.Misc, variable: tk.StringVar, width: int) -> tk.Entry:
        return tk.Entry(
            parent,
            textvariable=variable,
            width=width,
            font=("Segoe UI", 11),
            relief="flat",
            bg="#F7F5F1",
            fg=INK,
            insertbackground=NAVY,
            highlightthickness=1,
            highlightbackground="#E0DBD2",
            highlightcolor=NAVY,
        )

    def _center(self) -> None:
        self.update_idletasks()
        width = max(self.winfo_reqwidth(), 560)
        height = self.winfo_reqheight()
        x = (self.winfo_screenwidth() - width) // 2
        y = (self.winfo_screenheight() - height) // 3
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)

    def _read_form(self) -> tuple[date, date, str, str]:
        date_from = parse_date(self.date_from_var.get())
        date_to = parse_date(self.date_to_var.get())
        department = self.department_var.get().strip()
        responsible = self.responsible_var.get().strip()
        if department not in DEPARTMENTS:
            raise ValueError("Выберите подразделение")
        if len(responsible) < 2:
            raise ValueError("Укажите ответственного")
        if date_to < date_from:
            raise ValueError("Дата начала позже даты окончания")
        return date_from, date_to, department, responsible

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.button.configure(
            state="disabled" if busy else "normal",
            text="Записываю…" if busy else "Сформировать отчёт",
        )

    def _on_submit(self) -> None:
        if self._busy:
            return
        try:
            params = self._read_form()
        except ValueError as exc:
            messagebox.showerror("Проверьте поля", str(exc), parent=self)
            return
        self._set_busy(True)
        self.status_var.set("Формирую реестр и записываю лист в Google Таблицу…")
        threading.Thread(target=self._worker, args=params, daemon=True).start()

    def _worker(self, date_from: date, date_to: date, department: str, responsible: str) -> None:
        try:
            result = publish_report(date_from, date_to, department, responsible)
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            self.after(0, lambda: self._on_error(message[:900]))
            return
        self.after(0, lambda: self._on_success(result))

    def _on_success(self, result: PublishResult) -> None:
        self._set_busy(False)
        self.status_var.set(
            f"Готово: лист «{result.title}». Операций: {result.operations}, "
            f"оборот {fmt_money(result.total)} ₽."
        )
        open_sheet = messagebox.askyesno(
            "Отчёт записан",
            f"Лист «{result.title}» создан.\n"
            f"Операций: {result.operations}. Оборот: {fmt_money(result.total)} ₽.\n\n"
            "Открыть таблицу?",
            parent=self,
        )
        if open_sheet:
            webbrowser.open(result.url)

    def _on_error(self, message: str) -> None:
        self._set_busy(False)
        self.status_var.set("Не удалось записать отчёт.")
        messagebox.showerror("Ошибка записи", message, parent=self)


def main() -> None:
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = ReportApp()
    app.mainloop()


if __name__ == "__main__":
    main()
