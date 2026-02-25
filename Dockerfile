FROM python:3.12-slim

WORKDIR /app

# Системные зависимости для сборки пакетов
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Зависимости Python — отдельным слоем для кэша
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY bot/       bot/
COPY web/       web/
COPY web_main.py .

# Папка для SQLite (монтируется как volume)
RUN mkdir -p /app/data

EXPOSE 8080
