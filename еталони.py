#!/usr/bin/env python3
"""База еталонів страв — читаємо, не пишемо.

Живе поза ботом (Google Drive → вивантаження у ~/.shopper/еталони.json),
власник — шеф-кухар. Поки справжньої немає, береться зразок із
репозиторію. Правила з ТЗ, які виконує саме цей модуль:

- у завдання і анкету потрапляють лише картки зі статусом
  «опубліковано»: чернетка — ні;
- анкета прив'язується до версії картки на дату замовлення, тому в
  перевірці зберігається копія картки, а не посилання.
"""
import json
import os

import сховище

ТУТ = os.path.dirname(os.path.abspath(__file__))


def база():
    try:
        with open(сховище.шлях("еталони.json"), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        with open(os.path.join(ТУТ, "еталони.приклад.json"), encoding="utf-8") as f:
            return json.load(f)


def опубліковані():
    return [к for к in база().get("картки", []) if к.get("статус") == "опубліковано" and к.get("ознаки")]


def за_id(id_):
    return next((к for к in база().get("картки", []) if к.get("id") == id_), None)


def за_категорією(категорія):
    return [к for к in опубліковані() if к.get("категорія") == категорія]


def категорії_покриті():
    return sorted({к["категорія"] for к in опубліковані()})


def перевірити():
    """Помилки формату — для selftest і для екрану маркетолога."""
    помилки = []
    б = база()
    ids = set()
    for к in б.get("картки", []):
        if not к.get("id") or not к.get("назва"):
            помилки.append(f"картка без id або назви: {к}")
            continue
        if к["id"] in ids:
            помилки.append(f"id повторюється: {к['id']}")
        ids.add(к["id"])
        if к.get("статус") == "опубліковано" and not к.get("ознаки"):
            помилки.append(f"{к['назва']}: опубліковано без ознак")
        if к.get("статус") == "опубліковано" and not к.get("категорія"):
            помилки.append(f"{к['назва']}: без категорії")
    return помилки
