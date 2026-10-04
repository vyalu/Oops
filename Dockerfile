FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY entrypoint.sh /entrypoint.sh
# убираем возможные Windows-переводы строк (если файл правили в Блокноте)
RUN sed -i 's/\r$//' /entrypoint.sh

EXPOSE 8000

# Запуск через sh — не зависит от бита исполнения (теряется при загрузке через веб GitHub)
ENTRYPOINT ["sh", "/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
