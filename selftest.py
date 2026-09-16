#!/usr/bin/env python3
"""Самоперевірка перед деплоєм. Ловить те, з чим бот виглядає живим,
але не працює: зламану анкету або еталони, кнопку без обробника,
виклик функції, якої немає (у Cappi-Core таке двічі пропадало після
правок), і ганяє повний цикл на фальшивому Telegram.

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
МОДУЛІ = [f for f in sorted(os.listdir(ТУТ)) if f.endswith(".py")]


def швидко():
    """Те, що бот перевіряє при старті: анкета, еталони, форми реєстрації."""
    import анкета, еталони, тайники, форма, провокації
    п = [f"анкета: {x}" for x in анкета.перевірити()]
    п += [f"еталони: {x}" for x in еталони.перевірити()]
    п += [f"провокації: {x}" for x in провокації.перевірити()]
    п += [f"реєстрація: {x}" for x in форма.перевірити_кроки(тайники.кроки_реєстрації())]
    п += [f"згоди/тест: {x}" for x in форма.перевірити_кроки(тайники.кроки_згод_і_тесту())]
    return п


def невідомі_функції():
    """Виклик імені, яке ніде не визначене і не імпортоване."""
    for файл in МОДУЛІ:
        код = open(os.path.join(ТУТ, файл), encoding="utf-8").read()
        дерево = ast.parse(код)
        визначені = set(dir(__builtins__))
        for в in ast.walk(дерево):
            if isinstance(в, ast.ClassDef):
                визначені.add(в.name)
            elif isinstance(в, ast.FunctionDef):
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
            elif isinstance(в, ast.Lambda):
                for а in в.args.args:
                    визначені.add(а.arg)
        for в in ast.walk(дерево):
            if isinstance(в, ast.Call) and isinstance(в.func, ast.Name) and в.func.id not in визначені:
                помилки.append(f"{файл}:{в.lineno}: виклик невідомої функції {в.func.id}()")


def невідомі_атрибути_модулів():
    """bot.py кличе перевірки.щось() — а «щось» у модулі є?"""
    import importlib
    for файл in МОДУЛІ:
        код = open(os.path.join(ТУТ, файл), encoding="utf-8").read()
        дерево = ast.parse(код)
        модулі = {}
        for в in ast.walk(дерево):
            if isinstance(в, ast.Import):
                for a in в.names:
                    if a.name.replace(".py", "") + ".py" in МОДУЛІ:
                        модулі[a.asname or a.name] = a.name
        for в in ast.walk(дерево):
            if isinstance(в, ast.Attribute) and isinstance(в.value, ast.Name) and в.value.id in модулі:
                м = importlib.import_module(модулі[в.value.id])
                if not hasattr(м, в.attr):
                    помилки.append(f"{файл}:{в.lineno}: {в.value.id}.{в.attr} не існує")


def кнопки_без_обробника():
    """Кожен префікс callback_data з екранів має гілку у кнопка()."""
    код = open(os.path.join(ТУТ, "bot.py"), encoding="utf-8").read()
    вживані = set(re.findall(r'callback_data": f?"([^:"]+):', код))
    обробник = код[код.index("def кнопка("):код.index("# ====", код.index("def кнопка("))]
    оброблені = set(re.findall(r'вид (?:==|in) \(?"([^)]+?)"\)?', обробник))
    оброблені = {x.strip('" ') for s in оброблені for x in s.split(",")}
    for п in вживані - оброблені:
        помилки.append(f"bot.py: callback «{п}:» ніде не обробляється")
    import bot
    маршрути = код[код.index("def повідомлення("):код.index("def кнопка(")]
    for ім in bot.КНОПКИ:
        if f'КНОПКИ["{ім}"]' not in маршрути:
            помилки.append(f"bot.py: кнопка КНОПКИ[{ім!r}] не має обробника")
    for ім in bot.ХІД:
        if f'ХІД["{ім}"]' not in код[код.index("def _форма_або_режим("):]:
            помилки.append(f"bot.py: кнопка ХІД[{ім!r}] не має обробника")


def прогін():
    """Повний цикл на фальшивому Telegram — від кандидата до виплати."""
    import tests.dryrun as d
    try:
        d.прогнати(тихо=True)
        d.api_прогін()
    except Exception as e:
        import traceback
        помилки.append(f"прогін: {type(e).__name__}: {e}\n" + traceback.format_exc()[-1500:])


if __name__ == "__main__":
    for крок in (lambda: помилки.extend(швидко()), невідомі_функції, невідомі_атрибути_модулів, кнопки_без_обробника, прогін):
        try:
            крок()
        except Exception as e:
            помилки.append(f"{getattr(крок, '__name__', 'старт')}: {type(e).__name__}: {e}")
    if помилки:
        print("\n".join(помилки))
        sys.exit(1)
    print("ok")
