# onfine-back

Думал на протяжении пары секунд


## Onfine-back — шпаргалка разработчика / Dev Runbook

*(актуально на 03 мая 2025)*

---

### 1. Обзор папок проекта

| Путь                     | Что лежит                                                                                                                                                                                                                |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **`onfine/models/`**     | Таблицы SQLAlchemy. <br>‣ `user.py`, `wallet.py`, `transaction.py`, `ledger_entry.py` — базовый слой. <br>‣ **Крауд-майнинг**: `funding_round.py`, `round_investment.py`, `round_income.py`.                             |
| **`onfine/services/`**   | Чистая бизнес-логика (не Flask). <br>‣ `wallet_service.py` — баланс / вывод / кредиты. <br>‣ `round_invest_service.py` — вход в текущий раунд. <br>‣ `pool_income_service.py` — запись дохода пула и раздача по раундам. |
| **`onfine/api/`**        | REST-namespaces (Flask-RESTX). <br>‣ `auth.py`, `wallet_api.py`. <br>‣ **`equipment_round_api.py`** — список раундов и инвестиция.                                                                                       |
| **`onfine/external/`**   | Лёгкие клиенты внешних API. <br>‣ `emcd_client.py` — GET today-income.                                                                                                                                                   |
| **`onfine/utils/`**      | Утилиты общего назначения. <br>‣ `ledger_decorator.py` (авто-журнал), `kafka_producer.py`.                                                                                                                               |
| **`onfine/tasks/`**      | Скрипты/таски, которые вызываются по cron или Celery-beat. <br>‣ `round_cron.py` — ① тянет доход пула, ② делит по раундам.                                                                                               |
| **`migrations/`**        | Alembic автогенерирует сюда ревизии.                                                                                                                                                                                     |
| **`docker-compose.yml`** | Сервисы: `api`, `db`, `redis`, `kafka`(+controller), …                                                                                                                                                                   |

---

### 2. Запуск Dev-стека

```bash
# 1) собрать и поднять
docker compose up -d --build

# 2) health-проверка
docker compose ps          # все контейнеры Up/healthy
docker compose logs -f api # Gunicorn запустился без ошибок
```

*API доступен на [http://localhost:5000](http://localhost:5000), Swagger-UI — `/api/docs`.*

---

### 3. Файл `.env` (мин. набор)

```dotenv
POSTGRES_USER=onfine
POSTGRES_PASSWORD=onfine
POSTGRES_DB=onfine
FERNET_KEY=<44-символов Fernet>      # для шифрования priv-keys
KAFKA_BOOTSTRAP=kafka:9092
REF_MIN_PAYOUT=10
EMCD_KEY=...
EMCD_SECRET=...
```

---

### 4. Миграции (Alembic)

| Когда делать                      | Команды                                                                                                                                                                  |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Добавили/изменили модель          | `docker compose exec api flask db migrate -m "Добавление миграций"`, `docker compose exec api flask db upgrade`   
| Изменили **только** Python-логику | миграция **не нужна**, достаточно `docker compose up -d --build api`                                                                                                     |
| Не уверены                        | Запустите `migrate`; если увидите *“No changes detected”* — ничего применять не будет.                                                                                   |

---

### 5. Cron / Celery-beat задачи

| Скрипт                           | Период (пример)       | Что делает                                                                                                                                                          |
| -------------------------------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`onfine/tasks/round_cron.py`** | каждый день 03:00 UTC | 1) `emcd_client`: доход пула → `RoundIncome` <br>2) для каждого `FundingRound(state=MINING)` — распределяет `distributable` по инвесторам и кладёт людям на баланс. |

*Добавьте в `crontab` контейнера или настройте Celery-beat:*

```cron
0 3 * * * docker compose exec api python -m onfine.tasks.round_cron
```

---

### 6. Поток данных по раундам

1. **Инвестор** → `POST /rounds/invest`
   *Если текущий OPEN-раунд забит до `cap_usdt`, он переводится в `CLOSED`.*
2. **Админ** после покупки оборудования:

   ```sql
   UPDATE funding_rounds SET state='MINING' WHERE id=...;
   ```
3. **round\_cron**:

   * тянет доход пула, режет opex 7 %, раскладывает по MINING-раундам;
   * внутри каждого MINING-раунда делит между участниками (`Transaction: profit`).
4. Пользователь видит профит в `/wallets/balance` и может вывести.

---

### 7. Команда быстрого сидирования (dev)

```bash
# создать первый раунд 80k и сразу закрыть
docker compose exec api psql -U onfine onfine \
  -c "INSERT INTO funding_rounds(id,cap_usdt,collected_usdt,state) VALUES (1,80000,80000,'MINING');"
```

---

### 8. Основные REST-эндпоинты

| Метод | URL                         | Описание                                         |
| ----- | --------------------------- | ------------------------------------------------ |
| POST  | `/rounds/invest`            | тело `{amount}` — вложиться в текущий OPEN-раунд |
| GET   | `/rounds/`                  | все раунды с cap/collected/state                 |
| GET   | `/wallets/balance`          | базовый баланс пользователя                      |
| GET   | `/wallets/referral_balance` | накопленные реф-USDT                             |
| POST  | `/wallets/withdraw`         | вывод средств                                    |

(Swagger показывает полную схему Body/Response).

---

### 9. Частые ошибки

| Сообщение                            | Причина                                                          | Фикс                                                          |
| ------------------------------------ | ---------------------------------------------------------------- | ------------------------------------------------------------- |
| `Round overflow – wait next`         | сумма вклада > свободный лимит OPEN-раунда                       | дождитесь, пока админ откроет новый раунд                     |
| `Insufficient balance`               | пользователь пытается инвестировать/вывести больше, чем на счёте | пополнить баланс или дождаться прибыли                        |
| `librdkafka/rdkafka.h: No such file` | в Dockerfile ещё осталась `confluent-kafka`                      | либо `apk add librdkafka-dev`, либо переход на `kafka-python` |

---

### 10. Обновление зависимостей

```bash
# редактируем requirements.txt
docker compose build api
docker compose up -d api
```

---

### 11. TL;DR для нового девелопера

```bash
git clone …
cd onfine-back
cp .env.example .env        # заполните ключи
docker compose up -d --build
docker compose exec api flask --app onfine.app_factory:create_app db upgrade
open http://localhost:5000/api/docs
```

Вы готовы тестировать: создавайте пользователя, инвестируйте, запускайте
`round_cron` вручную и проверяйте, как приходят профиты.
