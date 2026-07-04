# Публичная демо-ссылка без карты и без регистраций

Всё крутится у тебя на машине (Neo4j + приложение в docker), а наружу отдаётся через
**Cloudflare quick tunnel** — аккаунт Cloudflare **не нужен**, карта **не нужна**,
Neo4j Aura ни при чём. Единственное внешнее — Yandex API (ключи у тебя уже есть).

## Запуск (одна команда)

```bash
# в .env должны быть YANDEX_API_KEY / YANDEX_FOLDER_ID
docker compose -f docker-compose.tunnel.yml up --build
```

Что произойдёт:
1. Поднимется Neo4j, дождётся готовности.
2. Приложение при старте построит граф из закоммиченных `data/processed/*.json`
   (в фоне, идемпотентно) и запустит Streamlit.
3. `cloudflared` создаст публичный HTTPS-адрес.

## Где взять ссылку

```bash
docker compose -f docker-compose.tunnel.yml logs cloudflared | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com'
```

Строка вида `https://<random>.trycloudflare.com` — это и есть публичная ссылка на демо.
Локально доступно тут же: http://localhost:8501

## Остановить

```bash
docker compose -f docker-compose.tunnel.yml down        # данные графа сохранятся (volume)
docker compose -f docker-compose.tunnel.yml down -v      # снести и данные графа
```

## Нюансы

- Ссылка живёт, **пока работает контейнер `cloudflared`** (и твоя машина). Выключил —
  ссылка пропала, при следующем запуске будет новая. Для защиты проекта: запусти перед
  выступлением, держи ноут включённым.
- Quick tunnel не требует токена, но и не даёт фиксированный домен. Нужен постоянный
  адрес — это уже именованный туннель Cloudflare (нужен бесплатный аккаунт CF, но всё
  ещё без карты); для демо не обязательно.
- Первый заход после старта может подождать ~1–2 мин, пока достроится граф (спиннер
  «Первый запуск: строю граф…»).

## Долив новых документов

```bash
python scripts/run_pipeline.py --extract-only --subdir "Статьи"   # обработать
git add data/processed && git commit -m "add chunks"              # (по желанию — в git)
docker compose -f docker-compose.tunnel.yml restart app           # подхватит новые JSON
```
