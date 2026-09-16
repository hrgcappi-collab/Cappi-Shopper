#!/usr/bin/env python3
"""Syrve Cloud API — факти про замовлення для приймання анкети (ТЗ 20.1).

Тільки читання. Ключ ТП уміє створювати накази про ціни — боту тайного
гостя туди писати нема чого; будь-який запис у Syrve звідси — помилка
проєктування. Server API (сесії, ліцензія на три слоти) не чіпаємо:
замовлення шукаємо через Cloud, він слотів не займає.

Що знаємо з Core про ці дані:
- філіал замовлення — `conception.name` («1 Лазарева», «2 Левітана»);
  `terminalGroupId` у замовлень порожній, `deliveryZone` — null;
- відмітки: whenCreated, whenConfirmed, whenSended, whenDelivered,
  whenClosed; обіцяний час — completeBefore; формат «2026-09-16 19:40:12»;
- тиждень одним запитом Cloud не віддає («too many data») — по дню.

Пошук замовлення тайника — за телефоном і датою:
`deliveries/by_delivery_date_and_phone`.
"""
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

import сховище

КОНЦЕПЦІЇ = {"1 Лазарева": "Лазарєва", "2 Левітана": "Левітана", "3 Поселок": None}
_токен = {"значення": None, "до": 0}


class Недоступний(RuntimeError):
    pass


def _конф():
    к = сховище.конфіг()
    return {"url": к.get("SYRVE_CLOUD_URL", "").rstrip("/"), "ключ": к.get("SYRVE_CLOUD_API_KEY", ""),
            "орг": к.get("SYRVE_ORG_ID", "")}


def налаштовано():
    к = _конф()
    return bool(к["url"] and к["ключ"] and к["орг"])


def _post(шлях, тіло, токен=None, timeout=60):
    к = _конф()
    заголовки = {"Content-Type": "application/json"}
    if токен:
        заголовки["Authorization"] = f"Bearer {токен}"
    req = urllib.request.Request(f"{к['url']}/api/1/{шлях}", data=json.dumps(тіло).encode(), headers=заголовки)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise Недоступний(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise Недоступний(str(e)[:120]) from None


def токен():
    if _токен["значення"] and time.time() < _токен["до"]:
        return _токен["значення"]
    т = _post("access_token", {"apiLogin": _конф()["ключ"]}, timeout=40).get("token")
    if not т:
        raise Недоступний("не видав токен")
    _токен.update(значення=т, до=time.time() + 50 * 60)
    return т


def момент(v):
    try:
        return datetime.strptime(v[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


_АЛФАВІТ = str.maketrans({"і": "и", "ї": "и", "ы": "и", "є": "е", "э": "е", "ё": "е", "ґ": "г",
                          "'": "", "’": "", "ʼ": "", "`": "", "ъ": ""})


def норм(s):
    return re.sub(r"[^a-zа-я0-9 ]", " ", str(s or "").lower().translate(_АЛФАВІТ)).split()


def схоже(а, б):
    """Назва з еталону проти назви в замовленні: усі слова однієї є в іншій."""
    x, y = set(норм(а)), set(норм(б))
    return bool(x) and (x <= y or y <= x)


# ---------------------------------------------------------------- запити
def замовлення_за_телефоном(телефон, дата, днів=1):
    """Замовлення з цього номера за дату ± днів. Телефон — як у Syrve: +380…"""
    к = _конф()
    д = datetime.fromisoformat(дата[:10]).date()
    тіло = {"organizationIds": [к["орг"]],
            "deliveryDateFrom": f"{д - timedelta(days=днів)} 00:00:00.000",
            "deliveryDateTo": f"{д + timedelta(days=днів + 1)} 00:00:00.000",
            "phone": телефон}
    r = _post("deliveries/by_delivery_date_and_phone", тіло, токен(), timeout=90)
    return [o.get("order") or {} for g in (r.get("ordersByOrganizations") or []) if isinstance(g, dict)
            for o in (g.get("orders") or []) if isinstance(o, dict)]


def замовлення_за_день(дата):
    к = _конф()
    д = datetime.fromisoformat(дата[:10]).date()
    r = _post("deliveries/by_delivery_date_and_status",
              {"organizationIds": [к["орг"]], "deliveryDateFrom": f"{д} 00:00:00.000",
               "deliveryDateTo": f"{д + timedelta(days=1)} 00:00:00.000"}, токен(), timeout=120)
    return [o.get("order") or {} for g in (r.get("ordersByOrganizations") or []) if isinstance(g, dict)
            for o in (g.get("orders") or []) if isinstance(o, dict)]


def номенклатура():
    """Товари: id, назва, група, ціна — для прив'язки еталонів і завдань."""
    к = _конф()
    r = _post("nomenclature", {"organizationId": к["орг"]}, токен(), timeout=90)
    групи = {g["id"]: g.get("name") for g in (r.get("groups") or []) if isinstance(g, dict)}
    out = []
    for p in r.get("products") or []:
        if not isinstance(p, dict) or p.get("type") not in (None, "Dish", "Good", "Modifier"):
            continue
        sp = (p.get("sizePrices") or [{}])[0].get("price") or {}
        out.append({"id": p["id"], "назва": p.get("name"), "код": p.get("code"), "група": групи.get(p.get("parentGroup")),
                    "ціна": sp.get("currentPrice"), "в_меню": sp.get("isIncludedInMenu"), "тип": p.get("type")})
    return out


def стоплист():
    """productId → множина terminalGroupId, де позиція в стопі."""
    к = _конф()
    r = _post("stop_lists", {"organizationIds": [к["орг"]]}, токен())
    out = {}
    for г in r.get("terminalGroupStopLists") or []:
        for т in (г.get("items") or []) if isinstance(г, dict) else []:
            for it in (т.get("items") or []) if isinstance(т, dict) else []:
                if isinstance(it, dict) and it.get("productId"):
                    out.setdefault(it["productId"], set()).add(т.get("terminalGroupId"))
    return out


def клієнт(телефон):
    """Картка клієнта в Syrve за телефоном: чи є, скільки замовлень.
    Для верифікації кандидата (ТЗ 5) — контекст, не вирок."""
    к = _конф()
    try:
        r = _post("customer/info", {"organizationId": к["орг"], "type": "phone", "phone": телефон}, токен(), timeout=30)
    except Недоступний as e:
        if "400" in str(e) or "404" in str(e):
            return {"є": False}
        raise
    if not isinstance(r, dict) or not r.get("id"):
        return {"є": False}
    return {"є": True, "з": (r.get("whenRegistered") or "")[:10], "замовлень": len(r.get("orders") or []) or None,
            "категорії": [c.get("name") for c in (r.get("categories") or []) if isinstance(c, dict)]}


# ---------------------------------------------------------------- звірка
def розібрати(o):
    """Замовлення Syrve → плоский словник для перевірки і звіту."""
    створено, доставлено = момент(o.get("whenCreated")), момент(o.get("whenDelivered"))
    до_строку = момент(o.get("completeBefore"))
    return {
        "id": o.get("id"), "номер": o.get("number"), "статус": o.get("status"),
        "філія": КОНЦЕПЦІЇ.get((o.get("conception") or {}).get("name")),
        "створено": створено.isoformat(timespec="seconds") if створено else None,
        "підтверджено": (момент(o.get("whenConfirmed")) or створено or datetime.min).isoformat(timespec="seconds") if момент(o.get("whenConfirmed")) else None,
        "відправлено": момент(o.get("whenSended")).isoformat(timespec="seconds") if момент(o.get("whenSended")) else None,
        "доставлено": доставлено.isoformat(timespec="seconds") if доставлено else None,
        "обіцяно_до": до_строку.isoformat(timespec="seconds") if до_строку else None,
        "факт_хв": round((доставлено - створено).total_seconds() / 60) if створено and доставлено else None,
        "обіцяно_хв": round((до_строку - створено).total_seconds() / 60) if створено and до_строку else None,
        "сума": o.get("sum"),
        "тип": (o.get("orderType") or {}).get("name") if isinstance(o.get("orderType"), dict) else o.get("orderType"),
        "джерело": o.get("sourceKey") or (o.get("marketingSource") or {}).get("name") if isinstance(o.get("marketingSource"), dict) else o.get("sourceKey"),
        "позиції": [{"id": (i.get("product") or {}).get("id"), "назва": (i.get("product") or {}).get("name"),
                     "кількість": i.get("amount"), "сума": i.get("resultSum", i.get("price"))}
                    for i in (o.get("items") or []) if isinstance(i, dict)],
        # Адреса — лише хешем: досить, щоб помітити повтор, і нічого не розкриває.
        "адреса_хеш": _хеш_адреси(o.get("deliveryPoint")),
        # Оператор і кур'єр — для внутрішньої прив'язки; у чати не йдуть.
        "оператор": (o.get("operator") or {}).get("name") if isinstance(o.get("operator"), dict) else None,
        "курєр": ((o.get("courierInfo") or {}).get("courier") or {}).get("name") if isinstance(o.get("courierInfo"), dict) else None,
    }


def _хеш_адреси(точка):
    if not isinstance(точка, dict):
        return None
    а = точка.get("address") or {}
    ключ = " ".join(str(а.get(k) or "").lower().strip() for k in ("street", "house", "flat")) if isinstance(а, dict) else str(а)
    ключ = re.sub(r"\s+", " ", ключ).strip()
    return hashlib.sha256(ключ.encode()).hexdigest()[:16] if ключ else None


def адреса_повторюється(п, з, днів=90):
    """Та сама адреса доставки в іншій перевірці за період — кухня її впізнає."""
    import перевірки
    if not з.get("адреса_хеш"):
        return False
    від = (datetime.now() - timedelta(days=днів)).date().isoformat()
    for інша in перевірки.усі():
        зз = (інша.get("syrve") or {}).get("замовлення") or {}
        if інша["id"] != п["id"] and інша["вікно"]["дата"] >= від and зз.get("адреса_хеш") == з["адреса_хеш"]:
            return True
    return False


def знайти(п, телефон):
    """Замовлення тайника для перевірки: за телефоном, у день оформлення,
    найближче за часом створення до відмітки в анкеті."""
    в = п["анкета"]["відповіді"]
    дата = (в.get("час_оформлення") or п["вікно"]["дата"])[:10]
    кандидати = [розібрати(o) for o in замовлення_за_телефоном(телефон, дата)]
    кандидати = [к for к in кандидати if к["статус"] != "Cancelled"]
    if п.get("канал") == "Glovo":
        # Glovo-замовлення приходять у Syrve через інтеграцію з джерелом «glovo»;
        # якщо позначки немає — беремо як є, але це і є те, що треба підтвердити.
        з_glovo = [к for к in кандидати if "glovo" in str(к.get("джерело") or "").lower()]
        кандидати = з_glovo or кандидати
    if not кандидати:
        return None
    if в.get("номер_замовлення"):
        за_номером = [к for к in кандидати if str(к["номер"]) == str(в["номер_замовлення"]).strip()]
        if за_номером:
            return за_номером[0]
    оф = момент(в.get("час_оформлення", "").replace("T", " ")) if в.get("час_оформлення") else None
    if оф:
        кандидати.sort(key=lambda к: abs((datetime.fromisoformat(к["створено"]) - оф).total_seconds()) if к["створено"] else 1e9)
    return кандидати[0]


def звірити(п, телефон):
    """Повертає п['syrve']: факт замовлення і збіги з анкетою та завданням.

    Кидає Недоступний — тоді приймання позначає «відкладено» і
    планувальник повторить пізніше.
    """
    з = знайти(п, телефон)
    if not з:
        return {"коли": datetime.now().isoformat(timespec="seconds"), "знайдено": False,
                "збіги": {"замовлення існує": False}}
    в = п["анкета"]["відповіді"]
    завд = п.get("завдання") or {}
    збіги = {"замовлення існує": True}
    збіги["філія відповідає завданню"] = (з["філія"] == п["філія"]) if з["філія"] else None
    # склад: кожна обов'язкова позиція завдання є серед позицій замовлення
    відсутні = []
    for поз in завд.get("позиції", []):
        є = any((поз["id"] == x["id"]) or схоже(поз["назва"], x["назва"]) for x in з["позиції"])
        if not є:
            відсутні.append(поз["назва"])
    збіги["склад відповідає завданню"] = not відсутні
    if в.get("сума_замовлення") is not None and з["сума"] is not None:
        збіги["сума збігається з анкетою"] = abs(float(в["сума_замовлення"]) - float(з["сума"])) <= max(10, 0.05 * float(з["сума"]))
    збіги["сума в ліміті"] = (з["сума"] <= завд.get("бюджет", 1e9)) if з["сума"] is not None else None
    # тайминг: факт із системи проти відмітки тайника
    оф, отр = в.get("час_оформлення"), в.get("час_отримання")
    if з["факт_хв"] is not None and оф and отр:
        свій = (datetime.fromisoformat(отр) - datetime.fromisoformat(оф)).total_seconds() / 60
        збіги["час вручення збігається (±15 хв)"] = abs(свій - з["факт_хв"]) <= 15
    import налаштування
    збіги["адреса не повторюється за квартал"] = not адреса_повторюється(п, з, налаштування.дай("адреса_повтор_днів"))
    return {"коли": datetime.now().isoformat(timespec="seconds"), "знайдено": True, "замовлення": з,
            "відсутні_позиції": відсутні, "збіги": збіги}


def текст(с):
    """Рядки для картки маркетолога."""
    if not с:
        return ["Syrve: звірки ще не було"]
    if not с.get("знайдено"):
        return ["Syrve: замовлення з цього номера в цей день <b>не знайдено</b>"]
    з = с["замовлення"]
    рядки = [f"Syrve: замовлення №{з['номер']} · {з['філія'] or '?'} · {з['статус']} · {з['сума']} грн",
             f"  створено {з['створено'][11:16] if з['створено'] else '—'}, доставлено {з['доставлено'][11:16] if з['доставлено'] else '—'}"
             + (f" · факт <b>{з['факт_хв']} хв</b>" if з["факт_хв"] is not None else "")
             + (f", обіцяно {з['обіцяно_хв']}" if з["обіцяно_хв"] is not None else "")]
    if с.get("відсутні_позиції"):
        рядки.append("  ❌ немає в замовленні: " + ", ".join(с["відсутні_позиції"]))
    значки = {True: "✅", False: "❌", None: "⏸"}
    рядки += [f"  {значки[ок]} {назва}" for назва, ок in с["збіги"].items() if назва != "замовлення існує"]
    return рядки
