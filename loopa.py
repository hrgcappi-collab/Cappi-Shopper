#!/usr/bin/env python3
"""Loopa (Review360) — ТЗ 20.2, двосторонній обмін.

Читаємо (є в Core): `/metrics/reviews` — відгуки з тональністю по
філіях і категоріях (kitchen, courier, packing, operator…). Негатив за
останній місяць — вхід для генератора завдань: де гості скаржаться,
туди й дивимось.

Пишемо (ТЗ вимагає, API поки немає): анкети, автотікети по червоній
зоні, ознака «тестове звернення». Поки Loopa не дала endpoint, тікет
формується тут, лягає у `тікети.jsonl` і йде маркетологу текстом —
щоб завести руками. Точка підключення одна: `надіслати_тікет`.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

import журнал
import сховище

# Категорії Loopa → наші групи оцінки.
КАТЕГОРІЇ = {"kitchen": "кухня", "packing": "упаковка", "courier": "курєр", "operator": "оператор",
             "site": "сайт", "app": "сайт", "support": "підтримка", "pickup": "точка"}
ФІЛІЇ = {"Лазарева": "Лазарєва", "Лазарєва": "Лазарєва", "Левітана": "Левітана", "Левитана": "Левітана"}


def _конф():
    к = сховище.конфіг()
    return {"url": к.get("LOOPA_URL", "").rstrip("/"), "токен": к.get("LOOPA_TOKEN", "")}


def налаштовано():
    к = _конф()
    return bool(к["url"] and к["токен"])


def _метрики(**параметри):
    к = _конф()
    q = urllib.parse.urlencode(параметри)
    req = urllib.request.Request(f"{к['url']}/metrics/reviews?{q}", headers={"Authorization": f"Bearer {к['токен']}"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        print(f"Loopa не відповіла: {str(e)[:100]}")
        return None


def негатив(днів=30):
    """{'групи': {кухня: n, …}, 'філії': {Лазарєва: n, …}, 'всього': n} або None."""
    if not налаштовано():
        return None
    до = datetime.now().date()
    від = до - timedelta(days=днів)
    за_кат = _метрики(**{"from": від.isoformat(), "to": до.isoformat(), "tone": "negative", "group_by": "category"})
    if за_кат is None:
        return None
    за_філ = _метрики(**{"from": від.isoformat(), "to": до.isoformat(), "tone": "negative", "group_by": "branch"}) or {}
    групи, філії = {}, {}
    for g in за_кат.get("groups", []):
        for ключ in str(g.get("key") or "").replace(" ", "").split(","):
            наша = КАТЕГОРІЇ.get(ключ)
            if наша:
                групи[наша] = групи.get(наша, 0) + int(g.get("count") or 0)
    for g in за_філ.get("groups", []):
        наша = ФІЛІЇ.get(str(g.get("key") or "").strip())
        if наша:
            філії[наша] = філії.get(наша, 0) + int(g.get("count") or 0)
    return {"групи": групи, "філії": філії, "всього": int(за_кат.get("total") or 0), "днів": днів}


# ---------------------------------------------------------------- тікети
def тікет(п, чому, тестове=False):
    """Тікет по червоній зоні або за провокацією-скаргою.

    `тестове` — ознака «тестове звернення»: такий тікет не має псувати
    статистику скарг і компенсацій (ТЗ розділ 12).
    """
    т = {"коли": datetime.now().isoformat(timespec="seconds"), "перевірка": п["id"], "філія": п["філія"],
         "канал": п["канал"], "чому": чому, "тестове": тестове, "відправлено": False, "loopa_id": None,
         "відповідальний": None, "строк": (datetime.now() + timedelta(days=3)).date().isoformat()}
    т["відправлено"], т["loopa_id"] = надіслати_тікет(т)
    сховище.jsonl_дописати("тікети.jsonl", т)
    журнал.запис("агент", "тікет", п["id"], ("Loopa: " if т["відправлено"] else "локально, Loopa без API запису: ") + чому)
    return т


def надіслати_тікет(т):
    """Єдина точка підключення запису в Loopa. Поки endpoint не узгоджено —
    нічого не шле, повертає (False, None)."""
    return False, None


def текст_тікета(т):
    return ("🎫 <b>Тікет для Loopa</b>" + (" · <i>тестове звернення</i>" if т["тестове"] else "") +
            f"\nПеревірка {т['перевірка']} · {т['філія']} · {т['канал']}\n{т['чому']}\n"
            f"Строк виправлення: {т['строк']}. Loopa ще не приймає тікети з бота — заведи руками і постав відповідального.")


def тікети(лише_відкриті=True):
    всі = сховище.jsonl_читати("тікети.jsonl")
    return [т for т in всі if not лише_відкриті or not т.get("закрито")]
