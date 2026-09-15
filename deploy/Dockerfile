# Залежностей немає — лише стандартна бібліотека Python.
FROM python:3.12-slim

# Час перевірок — київський: «замовив о 19:40» має означати 19:40 в Одесі,
# а сервер живе в UTC.
ENV TZ=Europe/Kyiv PYTHONUNBUFFERED=1
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app
COPY *.py сценарій.json ./

CMD ["python3", "bot.py"]
