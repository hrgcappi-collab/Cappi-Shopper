#!/usr/bin/env python3
"""Де лежить стан бота і як його читати-писати.

Все — у одній папці, яку контейнер монтує з хоста (`~/.shopper`):
конфіг з токеном, реєстр тайників, хвилі, перевірки, журнал агента.
Усередині образу це стерлося б при кожній пересборці.

Файли невеликі (сотні записів на рік), тому кожен — один json, який
читається цілком і пишеться цілком під замком. База даних тут була б
зайвою залежністю.
"""
import json
import os
import threading

DIR = os.environ.get("SHOPPER_HOME") or os.path.expanduser("~/.shopper")
_ЗАМОК = threading.RLock()
_КЕШ = {}


def шлях(імя):
    os.makedirs(DIR, exist_ok=True)
    return os.path.join(DIR, імя)


def конфіг():
    """Читає api.env: KEY=value, порожні рядки й # — пропускаємо.

    Змінні середовища мають пріоритет — так у compose можна перекрити
    окреме значення, не правлячи файл.
    """
    з_файлу = {}
    try:
        with open(шлях("api.env")) as f:
            for рядок in f:
                рядок = рядок.strip()
                if not рядок or рядок.startswith("#") or "=" not in рядок:
                    continue
                k, v = рядок.split("=", 1)
                з_файлу[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    for k, v in os.environ.items():
        if k in з_файлу or k.startswith(("TELEGRAM_", "SHOPPER_", "REPORT_", "OPENAI_", "SYRVE_", "LOOPA_", "CAPPI_")):
            з_файлу[k] = v
    return з_файлу


def json_читати(імя, типово):
    with _ЗАМОК:
        if імя in _КЕШ:
            return _КЕШ[імя]
        try:
            with open(шлях(імя)) as f:
                дані = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            дані = типово
        _КЕШ[імя] = дані
        return дані


def json_писати(імя, дані):
    # Спочатку у тимчасовий, потім rename: якщо процес уб'ють посеред
    # запису, на диску залишиться стара ціла версія, а не половина нової.
    with _ЗАМОК:
        _КЕШ[імя] = дані
        тимч = шлях(імя) + ".tmp"
        with open(тимч, "w") as f:
            json.dump(дані, f, ensure_ascii=False, indent=1)
        os.replace(тимч, шлях(імя))


def jsonl_дописати(імя, запис):
    with _ЗАМОК:
        with open(шлях(імя), "a") as f:
            f.write(json.dumps(запис, ensure_ascii=False) + "\n")


def jsonl_читати(імя):
    try:
        with open(шлях(імя)) as f:
            return [json.loads(р) for р in f if р.strip()]
    except FileNotFoundError:
        return []


def замок():
    return _ЗАМОК


def скинути_кеш():
    with _ЗАМОК:
        _КЕШ.clear()
