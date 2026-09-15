#!/usr/bin/env python3
"""Телеграм-бот «Тайний гість» Cappi: веде перевіряючого по чек-листу
і віддає адмінам готовий звіт.

Запуск:  python3 bot.py
Конфіг:  ~/.shopper/api.env  (TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_IDS,
         REPORT_CHAT_ID — куди слати звіти; порожньо = усім адмінам)

Тут — тільки Telegram і маршрутизація. Хід перевірки — перевірка.py,
бали і текст звіту — звіт.py, ролі — access.py.
"""
import json
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import access
import перевірка
import сховище
import звіт

КОНФІГ = сховище.конфіг()
TOKEN = КОНФІГ.get("TELEGRAM_BOT_TOKEN", "")
API = f"https://api.telegram.org/bot{TOKEN}"
REPORT_CHAT = КОНФІГ.get("REPORT_CHAT_ID", "").strip()

# ---------------------------------------------------------------- клавіатури
КНОПКИ = {
    "нова": "🕵️ Нова перевірка",
    "мої": "📋 Мої перевірки",
    "усі": "📊 Усі перевірки",
    "люди": "👥 Доступ",
    "допомога": "❓ Допомога",
}
# Кнопки під час перевірки — нижня клавіатура, щоб «Назад» і «Скасувати»
# були під рукою на будь-якому кроці, а не лише під останнім повідомленням.
ХІД = {"назад": "◀️ Назад", "пропустити": "⏭ Пропустити", "скасувати": "❌ Скасувати"}


def клавіатура(chat):
    if перевірка.поточна(chat):
        return {"keyboard": [[{"text": ХІД["назад"]}, {"text": ХІД["пропустити"]}],
                             [{"text": ХІД["скасувати"]}]], "resize_keyboard": True}
    ряди = [[{"text": КНОПКИ["нова"]}, {"text": КНОПКИ["мої"]}]]
    if access.можна(chat, "адмінити"):
        ряди.append([{"text": КНОПКИ["усі"]}, {"text": КНОПКИ["люди"]}])
    ряди.append([{"text": КНОПКИ["допомога"]}])
    return {"keyboard": ряди, "resize_keyboard": True}


# ---------------------------------------------------------------- Telegram
def tg(method, **params):
    data = urllib.parse.urlencode(
        {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
         for k, v in params.items() if v is not None}).encode()
    req = urllib.request.Request(f"{API}/{method}", data=data)
    with urllib.request.urlopen(req, timeout=70) as r:
        return json.loads(r.read())


def е(т):
    return звіт.е(т)


def say(chat, text, inline=None, keys=True):
    if isinstance(chat, int) and chat < 0:
        keys = False          # у групі нижнє меню з'явиться в усіх — не треба
    markup = {"inline_keyboard": inline} if inline else (клавіатура(chat) if keys else None)
    return tg("sendMessage", chat_id=chat, text=text, parse_mode="HTML", reply_markup=markup)


def фото(chat, file_id, підпис=None):
    return tg("sendPhoto", chat_id=chat, photo=file_id, caption=підпис, parse_mode="HTML")


# ---------------------------------------------------------------- екрани
def головне(chat):
    say(chat, "Що робимо?")


def допомога(chat):
    say(chat, "Я веду тайного гостя по перевірці.\n\n"
              "1. <b>Нова перевірка</b> — обираєш філію і канал замовлення.\n"
              "2. Відповідаєш на питання по ходу: замовив — натиснув, отримав — натиснув, "
              "оцінив, сфотографував.\n"
              "3. У кінці бачиш усе, що вніс, і відправляєш звіт.\n\n"
              "Перевірку можна перервати і повернутись — я пам'ятаю, де ти зупинився.")


def екран_кроку(chat):
    с = перевірка.поточна(chat)
    к = перевірка.крок(с)
    if к is None:
        return екран_підсумку(chat)
    n, всього = перевірка.прогрес(с)
    текст = f"<b>{е(к['розділ_назва'])}</b> · {n}/{всього}\n\n{е(к['питання'])}"
    if not перевірка.обовязковий(к):
        текст += "\n<i>Можна пропустити.</i>"
    попереднє = с["відповіді"].get(к["код"])
    if попереднє is not None:
        текст += f"\nЗараз: {звіт._показати(к, попереднє)}"
    # Нижня клавіатура «Назад / Пропустити / Скасувати» уже висить з
    # початку перевірки: inline-кнопки під питанням її не прибирають.
    say(chat, текст, inline=_кнопки_кроку(к))


def _кнопки_кроку(к):
    т = к["тип"]
    if т == "оцінка":
        return [[{"text": str(i), "callback_data": f"в:{i}"} for i in range(1, 6)]]
    if т == "так_ні":
        return [[{"text": "✅ Так", "callback_data": "в:так"}, {"text": "❌ Ні", "callback_data": "в:ні"}]]
    if т == "вибір":
        return [[{"text": в, "callback_data": f"в:{в}"}] for в in к["варіанти"]]
    if т == "час":
        return [[{"text": "⏱ Зафіксувати зараз", "callback_data": "в:зараз"}]]
    return None


def екран_підсумку(chat):
    с = перевірка.поточна(chat)
    перевірка.до_кінця(chat)
    inline = [[{"text": "✅ Надіслати звіт", "callback_data": "з:надіслати"}],
              [{"text": "✏️ Виправити", "callback_data": "з:виправити"}]]
    say(chat, "Перевір, чи все правильно:\n\n" + звіт.підсумок_для_гостя(с), inline=inline)


def екран_виправити(chat):
    с = перевірка.поточна(chat)
    inline = [[{"text": f"{к['питання'][:40]}", "callback_data": f"п:{к['код']}"}]
              for к in перевірка.кроки(с)]
    say(chat, "Який крок виправити?", inline=inline)


def екран_філії(chat):
    inline = [[{"text": ф, "callback_data": f"ф:{ф}"}] for ф in перевірка.сценарій()["філії"]]
    # Перше повідомлення перевірки вішає нижню клавіатуру ходу — далі
    # вона лишається сама, поки перевірка не закриється.
    say(chat, "Починаємо. Внизу — «Назад», «Пропустити», «Скасувати».")
    say(chat, "Яку філію перевіряємо?", inline=inline)


def екран_каналу(chat):
    inline = [[{"text": к, "callback_data": f"к:{к}"}] for к in перевірка.сценарій()["канали"]]
    say(chat, "Як замовляв(ла)?", inline=inline)


def екран_журналу(chat, свої=True):
    записи = перевірка.журнал(uid=chat if свої else None, скільки=15)
    if not записи:
        return say(chat, "Поки що порожньо.")
    рядки = [звіт.рядок_журналу(з) + ("" if свої else f" · {е(з['хто'].get('імя') or з['хто'].get('id'))}")
             for з in reversed(записи)]
    say(chat, "\n".join(рядки))


def екран_людей(chat):
    рядки = []
    for uid, п in access.список():
        рядки.append(f"{е(п.get('імя') or '—')} · <code>{uid}</code> · {п['роль']}")
    inline = [[{"text": f"✖ {п.get('імя') or uid}", "callback_data": f"д:прибрати:{uid}"}]
              for uid, п in access.список() if int(uid) != chat]
    say(chat, "Хто має доступ:\n\n" + "\n".join(рядки), inline=inline or None)


# ---------------------------------------------------------------- звіт
def надіслати_звіт(chat):
    з = перевірка.завершити(chat)
    текст = звіт.текст_звіту(з)
    кому = [int(REPORT_CHAT)] if REPORT_CHAT else access.адміни()
    for адресат in кому:
        try:
            say(адресат, текст, keys=False)
            for підпис, file_id in звіт.фото(з):
                фото(адресат, file_id, е(підпис))
        except Exception as e:
            print(f"звіт не пішов у {адресат}: {str(e)[:100]}")
    о = з["оцінка"]
    оц = f"{о['відсоток']}%" if о["відсоток"] is not None else "без балів"
    say(chat, f"Дякую! Звіт відправлено. Оцінка: <b>{оц}</b>.")


# ---------------------------------------------------------------- маршрути
def _хто(u):
    return {"id": u.get("id"), "імя": " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x)
            or u.get("username") or ""}


def чужий(chat, користувач):
    say(chat, "Привіт! Я бот тайного гостя Cappi. Тебе ще немає у списку — "
              "адміністратор отримав запит і додасть.", keys=False)
    хто = _хто(користувач)
    inline = [[{"text": "➕ Додати як перевіряючого", "callback_data": f"д:дати:{chat}:перевіряючий"}],
              [{"text": "➕ Додати як адміна", "callback_data": f"д:дати:{chat}:адмін"}]]
    for а in access.адміни():
        try:
            say(а, f"Стукає {е(хто['імя'])} (<code>{chat}</code>), "
                   f"@{е(користувач.get('username') or '—')}", inline=inline)
        except Exception:
            pass
    сховище.jsonl_дописати("невідомі.jsonl", {"коли": перевірка.зараз(), **хто})


def повідомлення(m):
    chat = m["chat"]["id"]
    if chat < 0:
        return          # у групах бот лише пише звіти, не слухає
    користувач = m.get("from", {})
    if not access.можна(chat, "перевіряти"):
        return чужий(chat, користувач)
    access.запамятати_імя(chat, _хто(користувач)["імя"])

    текст = (m.get("text") or "").strip()
    с = перевірка.поточна(chat)

    if текст in ("/start", "/menu"):
        return екран_кроку(chat) if с and с["філія"] and с["канал"] else головне(chat)
    if текст == КНОПКИ["допомога"] or текст == "/help":
        return допомога(chat)

    if с:
        if текст == ХІД["скасувати"]:
            перевірка.скасувати(chat)
            return say(chat, "Перевірку скасовано.")
        if not с["філія"]:
            return екран_філії(chat)
        if not с["канал"]:
            return екран_каналу(chat)
        if текст == ХІД["назад"]:
            перевірка.назад(chat)
            return екран_кроку(chat)
        if текст == ХІД["пропустити"]:
            к = перевірка.крок(с)
            if к and перевірка.обовязковий(к):
                return say(chat, "Цей крок пропустити не можна.")
            перевірка.пропустити(chat)
            return екран_кроку(chat)
        к = перевірка.крок(с)
        if к is None:
            return екран_підсумку(chat)
        if к["тип"] == "фото":
            if m.get("photo"):
                # Telegram дає кілька розмірів; останній — найбільший.
                перевірка.відповісти(chat, m["photo"][-1]["file_id"])
                return екран_кроку(chat)
            if m.get("document") and str(m["document"].get("mime_type", "")).startswith("image/"):
                перевірка.відповісти(chat, m["document"]["file_id"])
                return екран_кроку(chat)
            return say(chat, "Надішли фото — або пропусти.")
        значення = перевірка.розібрати(к, текст)
        if значення is None:
            return say(chat, _підказка(к))
        перевірка.відповісти(chat, значення)
        return екран_кроку(chat)

    if текст == КНОПКИ["нова"] or текст == "/new":
        перевірка.почати(chat, _хто(користувач))
        return екран_філії(chat)
    if текст == КНОПКИ["мої"]:
        return екран_журналу(chat, свої=True)
    if текст == КНОПКИ["усі"] and access.можна(chat, "адмінити"):
        return екран_журналу(chat, свої=False)
    if текст == КНОПКИ["люди"] and access.можна(chat, "адмінити"):
        return екран_людей(chat)
    головне(chat)


def _підказка(к):
    return {
        "число": "Потрібне число, наприклад <code>450</code>.",
        "оцінка": "Оцінка від 1 до 5 — натисни кнопку або набери цифру.",
        "так_ні": "Так чи ні — натисни кнопку.",
        "вибір": "Обери один із варіантів кнопкою.",
        "час": "Натисни кнопку або набери час як <code>14:35</code>.",
        "текст": "Напиши кілька слів.",
    }.get(к["тип"], "Не зрозумів.")


def кнопка(q):
    chat = q["message"]["chat"]["id"]
    дані = q.get("data", "")
    вид, _, решта = дані.partition(":")

    if вид == "д":                                   # доступ — лише адмін
        if not access.можна(chat, "адмінити"):
            return
        дія, _, хвіст = решта.partition(":")
        if дія == "дати":
            uid, _, роль = хвіст.partition(":")
            access.дати(int(uid), роль)
            say(chat, f"Додано <code>{uid}</code> як {роль}.")
            try:
                say(int(uid), f"Тобі відкрито доступ: {роль}. Тисни «Нова перевірка», коли будеш готовий(а).")
            except Exception:
                pass
        elif дія == "прибрати":
            access.прибрати(int(хвіст))
            say(chat, f"Прибрано <code>{хвіст}</code>.")
        return

    if not access.можна(chat, "перевіряти"):
        return
    с = перевірка.поточна(chat)
    if not с:
        return say(chat, "Ця перевірка вже закрита. Почни нову.")

    if вид == "ф":
        перевірка.обрати(chat, "філія", решта)
        return екран_каналу(chat)
    if вид == "к":
        перевірка.обрати(chat, "канал", решта)
        return екран_кроку(chat)
    if вид == "в":
        к = перевірка.крок(с)
        if к is None:
            return екран_підсумку(chat)
        if к["тип"] == "час" and решта == "зараз":
            значення = перевірка.зараз()
        elif к["тип"] == "так_ні":
            значення = решта == "так"
        else:
            значення = перевірка.розібрати(к, решта)
        if значення is None:
            return say(chat, _підказка(к))
        перевірка.відповісти(chat, значення)
        return екран_кроку(chat)
    if вид == "п":
        перевірка.перейти(chat, решта)
        return екран_кроку(chat)
    if вид == "з":
        if решта == "надіслати":
            return надіслати_звіт(chat)
        if решта == "виправити":
            return екран_виправити(chat)


# ---------------------------------------------------------------- цикл
_ПУЛ = ThreadPoolExecutor(max_workers=8, thread_name_prefix="чат")
_ЗАМКИ = {}
_ЗАМКИ_LOCK = threading.Lock()


def _замок(chat):
    with _ЗАМКИ_LOCK:
        return _ЗАМКИ.setdefault(chat, threading.Lock())


def обробити(u):
    try:
        if "callback_query" in u:
            q = u["callback_query"]
            chat = q["message"]["chat"]["id"]
            with _замок(chat):
                кнопка(q)
        elif "message" in u:
            chat = u["message"]["chat"]["id"]
            with _замок(chat):
                повідомлення(u["message"])
    except Exception:
        traceback.print_exc()
        try:
            chat = (u.get("message") or u.get("callback_query", {}).get("message", {}))["chat"]["id"]
            say(chat, "Щось зламалось. Спробуй ще раз або натисни /start.")
        except Exception:
            pass


def main():
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN порожній — заповни ~/.shopper/api.env")
    помилки = перевірка.перевірити_сценарій()
    if помилки:
        raise SystemExit("сценарій.json зламаний:\n  " + "\n  ".join(помилки))
    print(f"тайний гість запущений, сценарій {перевірка.сценарій().get('версія')}, "
          f"адмінів: {len(access.адміни())}")
    offset = None
    while True:
        try:
            for u in tg("getUpdates", offset=offset, timeout=50).get("result", []):
                offset = u["update_id"] + 1
                if "callback_query" in u:
                    try:
                        tg("answerCallbackQuery", callback_query_id=u["callback_query"]["id"])
                    except Exception:
                        pass
                _ПУЛ.submit(обробити, u)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            print(f"зв'язок із Telegram обірвався: {str(e)[:80]} — пробую знову")
            time.sleep(5)
        except Exception:
            traceback.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    main()
