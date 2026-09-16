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
ФАЙЛ_ТІКЕТІВ = "тікети.json"


def _тікети():
    return сховище.json_читати(ФАЙЛ_ТІКЕТІВ, {})


def тікет(п, чому, тестове=False):
    """Тікет по червоній зоні або за провокацією-скаргою.

    `тестове` — ознака «тестове звернення»: такий тікет не має псувати
    статистику скарг і компенсацій (ТЗ розділ 12).
    """
    всі = _тікети()
    т = {"id": f"Т{len(всі) + 1:03d}", "коли": datetime.now().isoformat(timespec="seconds"), "перевірка": п["id"],
         "філія": п["філія"], "канал": п["канал"], "чому": чому, "тестове": тестове, "відправлено": False, "loopa_id": None,
         "відповідальний": None, "строк": (datetime.now() + timedelta(days=3)).date().isoformat(), "закрито": None}
    т["відправлено"], т["loopa_id"] = надіслати_тікет(т)
    всі[т["id"]] = т
    сховище.json_писати(ФАЙЛ_ТІКЕТІВ, всі)
    журнал.запис("агент", "тікет", п["id"], ("Loopa: " if т["відправлено"] else "локально, Loopa без API запису: ") + чому)
    return т


def закрити(id_, хто):
    """Виправлено → агент планує повторну перевірку того ж зрізу в
    найближчій хвилі (ТЗ розділ 14)."""
    всі = _тікети()
    т = всі.get(id_)
    if not т or т.get("закрито"):
        return None
    т["закрито"] = datetime.now().isoformat(timespec="seconds")
    т["повторити"] = {"філія": т["філія"], "канал": т["канал"], "виконано": False}
    сховище.json_писати(ФАЙЛ_ТІКЕТІВ, всі)
    журнал.запис(хто, "тікет:закрито", т["перевірка"], f"{id_}; повторна перевірка {т['філія']} / {т['канал']} у найближчій хвилі")
    return т


def повтори_до_планування():
    """Зрізи, які треба перевірити повторно (закриті тікети без повтору)."""
    return [т for т in _тікети().values() if т.get("повторити") and not т["повторити"]["виконано"]]


def відмітити_повтор(т, перевірка_id):
    всі = _тікети()
    всі[т["id"]]["повторити"]["виконано"] = перевірка_id
    сховище.json_писати(ФАЙЛ_ТІКЕТІВ, всі)


def _пише():
    """Запис вмикається змінною LOOPA_WRITE=1 після того, як Loopa підняла
    endpoint-и з docs/Запити-до-джерел.md."""
    return налаштовано() and str(сховище.конфіг().get("LOOPA_WRITE", "")).strip() in ("1", "true", "так")


def _post(шлях, тіло):
    к = _конф()
    req = urllib.request.Request(f"{к['url']}{шлях}", data=json.dumps(тіло, ensure_ascii=False).encode(),
                                 headers={"Authorization": f"Bearer {к['токен']}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read() or b"{}")


def надіслати_тікет(т):
    """Запис тікета — за контрактом із запиту до Loopa:
    POST /api/v1/mystery/tickets → {"id": …}. Поки LOOPA_WRITE не
    увімкнено або Loopa відмовила — (False, None), тікет лишається локально."""
    if not _пише():
        return False, None
    try:
        в = _post("/api/v1/mystery/tickets", {
            "check_id": т["перевірка"], "branch": т["філія"], "channel": т["канал"], "title": т["чому"][:120],
            "description": т["чому"], "due": т["строк"], "test": т["тестове"], "source": "mystery-shopper-bot"})
        return True, в.get("id")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        print(f"Loopa тікет не записано: {str(e)[:100]}")
        return False, None


def надіслати_перевірку(п):
    """Прийнята анкета — у Loopa (розділ «Тайники»): оцінки по групах,
    критичні, тайминг, без персоналій тайника. POST /api/v1/mystery/checks."""
    if not _пише():
        return False
    о = п.get("оцінка") or {}
    тіло = {"id": п["id"], "date": п["вікно"]["дата"], "branch": п["філія"], "channel": п["канал"],
            "shopper": None, "score": о.get("загальна"), "zone": о.get("зона"),
            "groups": {г: гр.get("відсоток") for г, гр in (о.get("групи") or {}).items()},
            "critical": [к["що"] for к in о.get("критичні", [])],
            "delivery_minutes": о.get("час_доставки_хв"), "delay_minutes": о.get("запізнення_хв"),
            "promised_minutes": ((п.get("syrve") or {}).get("замовлення") or {}).get("обіцяно_хв") or п["анкета"]["відповіді"].get("обіцяний_час"),
            "syrve_order": ((п.get("syrve") or {}).get("замовлення") or {}).get("номер"),
            "provocation": ((п.get("завдання") or {}).get("провокація") or {}).get("код"),
            "impression": п["анкета"]["відповіді"].get("заг_враження"), "fix_first": п["анкета"]["відповіді"].get("заг_виправити"),
            "questionnaire_version": п["анкета"].get("версія"), "task_version": (п.get("завдання") or {}).get("версія")}
    try:
        _post("/api/v1/mystery/checks", тіло)
        журнал.запис("агент", "loopa:перевірка записана", п["id"])
        return True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        print(f"Loopa перевірка не записана: {str(e)[:100]}")
        return False


def текст_тікета(т):
    return (f"🎫 <b>Тікет {т['id']} для Loopa</b>" + (" · <i>тестове звернення</i>" if т["тестове"] else "") +
            f"\nПеревірка {т['перевірка']} · {т['філія']} · {т['канал']}\n{т['чому']}\n"
            f"Строк виправлення: {т['строк']}. Loopa ще не приймає тікети з бота — заведи руками і постав відповідального.")


def тікети(лише_відкриті=True):
    return [т for т in _тікети().values() if not лише_відкриті or not т.get("закрито")]
