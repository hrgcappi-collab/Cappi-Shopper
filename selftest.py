#!/usr/bin/env python3
"""Самоперевірка перед деплоєм. Ловить те, з чим бот виглядає живим,
але не працює: зламаний сценарій, кнопку без обробника, виклик функції,
якої немає (у Cappi-Core таке двічі пропадало після правок).

    python3 selftest.py        → «ok» або список і код виходу 1
"""
import ast
import os
import re
import sys

ТУТ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ТУТ)
os.environ.setdefault("SHOPPER_HOME", os.path.join(ТУТ, ".selftest-home"))

помилки = []


def перевірка_сценарію():
    import перевірка
    for п in перевірка.перевірити_сценарій():
        помилки.append(f"сценарій: {п}")


def невідомі_функції():
    """Виклик імені, яке ніде не визначене і не імпортоване."""
    for файл in sorted(f for f in os.listdir(ТУТ) if f.endswith(".py")):
        код = open(os.path.join(ТУТ, файл), encoding="utf-8").read()
        дерево = ast.parse(код)
        визначені = set(dir(__builtins__))
        for в in ast.walk(дерево):
            if isinstance(в, (ast.FunctionDef, ast.ClassDef)):
                визначені.add(в.name)
                for а in в.args.args + в.args.kwonlyargs:
                    визначені.add(а.arg)
            elif isinstance(в, (ast.Import, ast.ImportFrom)):
                for a in в.names:
                    визначені.add((a.asname or a.name).split(".")[0])
            elif isinstance(в, ast.Name) and isinstance(в.ctx, ast.Store):
                визначені.add(в.id)
            elif isinstance(в, (ast.For, ast.comprehension)):
                for n in ast.walk(в.target):
                    if isinstance(n, ast.Name):
                        визначені.add(n.id)
            elif isinstance(в, ast.ExceptHandler) and в.name:
                визначені.add(в.name)
        for в in ast.walk(дерево):
            if isinstance(в, ast.Call) and isinstance(в.func, ast.Name) and в.func.id not in визначені:
                помилки.append(f"{файл}:{в.lineno}: виклик невідомої функції {в.func.id}()")


def кнопки_без_обробника():
    """Кожен префікс callback_data з екранів має гілку у кнопка()."""
    код = open(os.path.join(ТУТ, "bot.py"), encoding="utf-8").read()
    вживані = set(re.findall(r'callback_data": f?"([^:"]+):', код))
    обробник = код[код.index("def кнопка("):код.index("# ---", код.index("def кнопка("))]
    оброблені = set(re.findall(r'вид == "([^"]+)"', обробник))
    for п in вживані - оброблені:
        помилки.append(f"bot.py: callback «{п}:» ніде не обробляється")
    # Так само для текстових кнопок нижньої клавіатури.
    import bot
    for ім in bot.КНОПКИ:
        if f'КНОПКИ["{ім}"]' not in код[код.index("def повідомлення("):]:
            помилки.append(f"bot.py: кнопка КНОПКИ[{ім!r}] не має обробника")
    for ім in bot.ХІД:
        if f'ХІД["{ім}"]' not in код[код.index("def повідомлення("):]:
            помилки.append(f"bot.py: кнопка ХІД[{ім!r}] не має обробника")


def прогін():
    """Повна перевірка на фальшивому Telegram — від /start до звіту."""
    import tests.dryrun as d
    try:
        d.прогнати(тихо=True)
    except Exception as e:
        помилки.append(f"прогін: {type(e).__name__}: {e}")


if __name__ == "__main__":
    for крок in (перевірка_сценарію, невідомі_функції, кнопки_без_обробника, прогін):
        try:
            крок()
        except Exception as e:
            помилки.append(f"{крок.__name__}: {type(e).__name__}: {e}")
    if помилки:
        print("\n".join(помилки))
        sys.exit(1)
    print("ok")
