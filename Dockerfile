FROM python:3.10-slim

WORKDIR /app

# Зависимости отдельным слоем — кэшируется, пока не меняется requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py .
# тёмная тема (theme=dark) — иначе Streamlit рисует тёмный текст на тёмном фоне
COPY .streamlit/ .streamlit/
COPY schema/ schema/
COPY src/ src/
COPY scripts/ scripts/
COPY fixtures/ fixtures/

# data/ монтируется томом (см. docker-compose.prod.yml), в образ не запекается.
# .env тоже не копируется — передаётся через env_file, ключи в образ не попадают.

EXPOSE 8501
CMD ["streamlit", "run", "src/app/streamlit_app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
