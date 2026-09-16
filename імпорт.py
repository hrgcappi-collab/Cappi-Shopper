#!/usr/bin/env python3
"""Дані від людей — файлом у чат з ботом. Маркетолог надсилає CSV або
txt, бот розкладає у ~/.shopper. Так підключення джерела, у якого ще
немає API, — це «надіслав файл», а не «попросив розробника».

Що приймається (за назвою файлу або підписом до нього):

    еталони*.csv       база еталонів від шефа → еталони.json
    співробітники*     телефони співробітників від HR → співробітники.txt
    новинки*.csv       новинки та акції від маркетингу / CappiX → новинки.json
    зміни*.csv         графік змін → зміни.json
    abc*.csv           ABC-продажі за місяць (замість OLAP, який тримає Core) → abc.json

CSV — через «;», перший рядок — заголовки, кодування UTF-8 (Excel:
«CSV UTF-8»). Списки всередині клітинки — через «|».
"""
import csv
import io
from datetime import datetime

import сховище

ФОРМАТИ = {
    "еталони": "id;назва;категорія;статус;версія;ціна;шматків;упаковка;температура;склад;комплектність;ознаки;фірмове;syrve_id;запущено",
    "співробітники": "телефон (по одному в рядку або CSV зі стовпцем «телефон»)",
    "новинки": "назва;syrve_id;тип (новинка|акція);від;до",
    "зміни": "дата;філія;роль;імя",
    "abc": "syrve_id;назва;кількість;виручка (за місяць; ранг рахує бот)",
}


def розпізнати(імя, підпис=""):
    ключ = (підпис or "").strip().lower() or (імя or "").lower()
    for вид in ФОРМАТИ:
        if ключ.startswith(вид) or вид in ключ:
            return вид
    return None


def _csv(текст):
    текст = текст.lstrip("﻿")
    зразок = текст[:2000]
    роздільник = ";" if зразок.count(";") >= зразок.count(",") else ","
    return list(csv.DictReader(io.StringIO(текст), delimiter=роздільник))


def _список(значення):
    return [x.strip() for x in str(значення or "").split("|") if x.strip()]


def _число(значення):
    try:
        return float(str(значення).replace(",", ".")) if str(значення).strip() else None
    except ValueError:
        return None


def еталони(текст):
    рядки = _csv(текст)
    картки, помилки = [], []
    for i, р in enumerate(рядки, 2):
        р = {k.strip().lower(): (v or "").strip() for k, v in р.items() if k}
        if not р.get("назва"):
            помилки.append(f"рядок {i}: без назви")
            continue
        к = {"id": р.get("id") or р.get("syrve_id") or f"csv-{i}", "назва": р["назва"], "категорія": р.get("категорія", ""),
             "статус": р.get("статус") or "опубліковано", "версія": р.get("версія") or "1",
             "ціна": _число(р.get("ціна")), "шматків": int(_число(р.get("шматків")) or 0) or None,
             "упаковка": р.get("упаковка"), "температура": р.get("температура"), "склад": р.get("склад", ""),
             "комплектність": _список(р.get("комплектність")), "ознаки": _список(р.get("ознаки")),
             "фірмове": р.get("фірмове", ""), "syrve_id": р.get("syrve_id") or None, "запущено": р.get("запущено") or None}
        if к["статус"] == "опубліковано" and not к["ознаки"]:
            помилки.append(f"{к['назва']}: опубліковано без ознак — стане чернеткою")
            к["статус"] = "чернетка"
        картки.append(к)
    if not картки:
        return 0, помилки or ["жодної картки не розібрав — перевір заголовки"]
    сховище.json_писати("еталони.json", {"версія": datetime.now().strftime("%Y-%m-%d"), "опубліковано": datetime.now().date().isoformat(),
                                         "джерело": "csv від шефа", "картки": картки})
    return len(картки), помилки


def співробітники(текст):
    номери = set()
    if "телефон" in текст[:300].lower() and (";" in текст[:300] or "," in текст[:300]):
        for р in _csv(текст):
            р = {k.strip().lower(): v for k, v in р.items() if k}
            ц = "".join(ч for ч in str(р.get("телефон") or "") if ч.isdigit())
            if len(ц) >= 9:
                номери.add(ц[-9:])
    else:
        for рядок in текст.splitlines():
            ц = "".join(ч for ч in рядок if ч.isdigit())
            if len(ц) >= 9 and not рядок.strip().startswith("#"):
                номери.add(ц[-9:])
    with open(сховище.шлях("співробітники.txt"), "w", encoding="utf-8") as f:
        f.write("# останні 9 цифр телефонів співробітників; оновлено " + datetime.now().isoformat(timespec="minutes") + "\n")
        f.write("\n".join(sorted(номери)) + "\n")
    import os
    os.chmod(сховище.шлях("співробітники.txt"), 0o600)
    return len(номери), []


def новинки(текст):
    записи, помилки = [], []
    for i, р in enumerate(_csv(текст), 2):
        р = {k.strip().lower(): (v or "").strip() for k, v in р.items() if k}
        if not р.get("назва"):
            помилки.append(f"рядок {i}: без назви")
            continue
        тип = "акція" if "акц" in р.get("тип", "").lower() else "новинка"
        записи.append({"назва": р["назва"], "syrve_id": р.get("syrve_id") or None, "тип": тип,
                       "від": р.get("від") or None, "до": р.get("до") or None})
    сховище.json_писати("новинки.json", {"оновлено": datetime.now().isoformat(timespec="minutes"), "записи": записи})
    return len(записи), помилки


def зміни(текст):
    записи, помилки = [], []
    for i, р in enumerate(_csv(текст), 2):
        р = {k.strip().lower(): (v or "").strip() for k, v in р.items() if k}
        if not (р.get("дата") and р.get("філія") and р.get("імя")):
            помилки.append(f"рядок {i}: потрібні дата, філія, імя")
            continue
        записи.append({"дата": р["дата"][:10], "філія": р["філія"], "роль": р.get("роль", ""), "імя": р["імя"]})
    if записи:
        сховище.json_писати("зміни.json", {"оновлено": datetime.now().isoformat(timespec="minutes"), "записи": записи})
    return len(записи), помилки


def abc(текст):
    записи, помилки = [], []
    for i, р in enumerate(_csv(текст), 2):
        р = {k.strip().lower(): (v or "").strip() for k, v in р.items() if k}
        if not р.get("назва") and not р.get("syrve_id"):
            помилки.append(f"рядок {i}: без назви")
            continue
        записи.append({"syrve_id": р.get("syrve_id") or None, "назва": р.get("назва", ""),
                       "кількість": _число(р.get("кількість")) or 0, "виручка": _число(р.get("виручка")) or 0})
    записи.sort(key=lambda x: -x["виручка"])
    for n, з in enumerate(записи, 1):
        з["ранг"] = n
    if записи:
        сховище.json_писати("abc.json", {"оновлено": datetime.now().isoformat(timespec="minutes"), "записи": записи})
    return len(записи), помилки


def abc_ранг(картка):
    """Місце позиції у продажах (1 — найходовіша); без даних — велике число."""
    import syrve
    for з in сховище.json_читати("abc.json", {}).get("записи", []):
        if (з.get("syrve_id") and з["syrve_id"] in (картка.get("syrve_id"), картка.get("id"))) or syrve.схоже(з["назва"], картка["назва"]):
            return з["ранг"]
    return 10_000


def на_зміні(дата, філія):
    з = сховище.json_читати("зміни.json", {}).get("записи", [])
    return [x for x in з if x["дата"] == дата[:10] and x["філія"].lower().startswith(філія.lower()[:5])]


ОБРОБНИКИ = {"еталони": еталони, "співробітники": співробітники, "новинки": новинки, "зміни": зміни, "abc": abc}


def прийняти(вид, текст):
    return ОБРОБНИКИ[вид](текст)
