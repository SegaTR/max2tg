# max2tg - Проектная схема и документация

## Общая структура проекта

```
max2tg/
├── app/
│   ├── __init__.py              # Маркер пакета Python
│   ├── config.py                # Загрузка и валидация конфигурации
│   ├── main.py                  # Точка входа приложения
│   ├── max_client.py            # Клиент WebSocket для Max
│   ├── max_listener.py          # Слушатель и форвардер сообщений Max
│   ├── resolver.py              # Разрешение ID контактов и пользователей
│   ├── tg_sender.py             # Отправка сообщений в Telegram
│   └── tg_handler.py            # Обработчик Telegram-бота для ответов
├── .dockerignore
├── .env.example                # Шаблон переменных окружения
├── .gitignore
├── docker-compose.yml          # Docker-оркестрация
├── Dockerfile                  # Многоэтапный Docker-билд
├── pytest.ini                 # Конфигурация тестов
├── requirements.txt            # Python-зависимости
└── README.md                   # Документация
```

## Основные компоненты

### 1. Конфигурационная система (`config.py`)
- **Тип**: Использует dataclasses для type-safe настроек
- **Функции**:
  - Валидация обязательных переменных окружения
  - Нормализация прокси-соединений
  - Форматирование URL-адресов
  - Поддержка режима отладки и ответов
- **Ключевые поля**:
  - `max_token`, `max_device_id` - авторизация Max
  - `tg_bot_token`, `tg_chat_id` - Telegram-бот
  - `debug`, `reply_enabled` - флаги режима

### 2. Основное приложение (`main.py`)
- **Точка входа**: `async def main()`
- **Функции**:
  - Настройка логирования с ротацией файлов
  - Управление потоком выполнения (ThreadPoolExecutor)
  - Координация Max-клиента и Telegram-бота
  - Обработка сигналов завершения работы
- **Особенности**:
  - `threading.stack_size(524288)` для низких ресурсов
  - `_SyncExecutor` для синхронного выполнения без потоков
  - Настройка логгеров для разных компонентов

### 3. Max-клиент (`max_client.py`)
- **Соединение**: WebSocket к `wss://ws-api.oneme.ru/websocket`
- **Классы**:
  - `OpCode` - перечисление операций WebSocket
  - `MaxMessage` - dataclass для сообщений Max
  - `MaxClient` - основной клиент с heartbeat и reconnect
- **Ключевые методы**:
  - `cmd()` - отправка команд WebSocket
  - `download_file()` - загрузка медиафайлов
  - `resolve_user()` - разрешение имен пользователей

### 4. Слушатель Max (`max_listener.py`)
- **Функции**:
  - Парсинг входящих сообщений Max
  - Форматирование заголовков для Telegram
  - Обработка вложений (фото, видео, файлы)
  - Управление клавиатурой ответов
- **Вспомогательные функции**:
  - `_header()` - создание заголовков сообщений
  - `_extract_photo_url()`, `_extract_file_url()` - извлечение URL
  - `_guess_media_kind()` - определение типа медиа

### 5. Telegram-отправитель (`tg_sender.py`)
- **Класс**: `TelegramSender`
- **Функции**:
  - Отправка текстовых сообщений, фото, видео, документов
  - Обработка повторов и rate limiting
  - Поддержка прокси-соединений
  - Truncation длинных сообщений
- **Особенности**:
  - `MAX_RETRIES = 3` для надежности
  - Обработка `RetryAfter` и `TimedOut` исключений
  - Настройка HTTPXRequest с таймаутами

### 6. Telegram-обработчик (`tg_handler.py`)
- **Класс**: `Application` от python-telegram-bot
- **Обработчики**:
  - `CallbackQueryHandler` - обработка нажатий кнопок
  - `MessageHandler` - обработка текстовых ответов
  - `CommandHandler` - обработка команд (/start, /cancel)
- **Функции**:
  - Управление состоянием ответов (`PENDING_REPLY_KEY`)
  - Пересылка ответов обратно в Max
  - Проверка разрешенных чатов

## Поток данных

```
Max Messenger
    ↓ (WebSocket)
MaxClient → MaxListener → TelegramSender → Telegram
    ↑ (HTTP API)                ↑
Telegram Bot ← tg_handler ← User Reply
```

## Ключевые возможности

### 1. Полная поддержка типов сообщений
- ✅ Текстовые сообщения
- ✅ Фотографии
- ✅ Видео
- ✅ Файлы
- ✅ Аудио
- ✅ Стикеры
- ✅ Контакты
- ✅ Геолокация
- ✅ Ссылки

### 2. Двусторонняя связь
- Пересылка из Max → Telegram
- Пересылка из Telegram → Max (через inline-кнопки)

### 3. Продвинутая обработка прокси
- SOCKS5-прокси для Max (`MAX_PROXY`)
- SOCKS5-прокси для Telegram (`TG_PROXY`)
- Нормализация URL прокси (socks5h:// → socks5://)

### 4. Режимы работы
- **Userbot**: Подключается к вашему аккаунту Max через WebSocket
- **Docker-ready**: Разворачивается одной командой
- **Low-resource**: Оптимизирован для серверов с ограниченными ресурсами

### 5. Безопасность и конфиденциальность
- **Предупреждение**: Не делитесь токенами и device_id
- **Конфиденциальность**: Программа предоставляется "как есть"
- **Ограничения**: Нет гарантий безопасности и соответствия законодательству

## Зависимости

### Python-пакеты (`requirements.txt`)
```
aiohttp>=3.9.0
aiohttp-socks>=0.10.0
python-telegram-bot>=21.0
python-dotenv>=1.0.0
httpx[socks]>=0.24.0
```

### Docker-образы
- **Builder**: `python:3.12-slim` с установленными зависимостями
- **Runtime**: `python:3.12-alpine` (миниатюрный)

## Конфигурация

### Переменные окружения (`.env.example`)

| Переменная | Обязательна | Описание |
|-------------|--------------|-----------|
| `MAX_TOKEN` | да | Токен авторизации Max |
| `MAX_DEVICE_ID` | да | ID устройства Max |
| `TG_BOT_TOKEN` | да | Токен Telegram-бота |
| `TG_CHAT_ID` | да | ID чата для пересылки |
| `MAX_CHAT_IDS` | нет | Список ID чатов Max |
| `MAX_PROXY` | нет | SOCKS5-прокси для Max |
| `TG_PROXY` | нет | SOCKS5-прокси для Telegram |
| `DEBUG` | нет | Включить подробное логирование |
| `REPLY_ENABLED` | нет | Разрешить ответы из Telegram |

### Пример конфигурации

```bash
MAX_TOKEN=your_max_token_here
MAX_DEVICE_ID=your_device_id_here
TG_BOT_TOKEN=your_telegram_bot_token
TG_CHAT_ID=your_telegram_chat_id
DEBUG=true
REPLY_ENABLED=true
```

## Развертывание

### Docker (рекомендуется)

```bash
git clone <repo> max2tg
cd max2tg
cp .env.example .env
# Редактируйте .env с вашими данными
docker-compose up -d
```

### Прямой Python

```bash
pip install -r requirements.txt
python -m app.main
```

## Типичные проблемы и решения

### 1. Ошибки прокси
- **Проблема**: `socks5h://` не поддерживается aiohttp-socks
- **Решение**: Нормализация в `config.py` → `socks5://`

### 2. Rate limiting Telegram
- **Проблема**: Ограничения на отправку сообщений
- **Решение**: Использование `RetryAfter` и `TimedOut` обработчиков

### 3. Низкие ресурсы сервера
- **Проблема**: Недостаточно памяти/CPU
- **Решение**: Использование `_SyncExecutor` вместо ThreadPoolExecutor

### 4. Дублирование медиафайлов
- **Проблема**: Медленные прокси вызывают повторную отправку
- **Решение**: Увеличение `TG_MEDIA_WRITE_TIMEOUT`

## Диагностика

### Логи
- **Файл**: `logs/max2tg.log`
- **Формат**: `%(asctime)s [%(name)s] %(levelname)s: %(message)s`
- **Уровни**: DEBUG, INFO, WARNING, ERROR

### Режим отладки
- Установите `DEBUG=true` в `.env`
- Включает JSON-dump в `debug/` директорию
- Подробное логирование всех операций

## Обслуживание

### Остановка
- Docker: `docker-compose down`
- Python: `Ctrl+C` или `SIGTERM`

### Обновление
- Docker: `docker-compose pull && docker-compose up -d`
- Python: `pip install -r requirements.txt && python -m app.main`

### Мониторинг
- Логи: `tail -f logs/max2tg.log`
- Docker: `docker-compose logs -f`

---

**Важно**: Этот проект является независимым и неофициальным. Авторы не несут ответственности за его использование. Всегда проверяйте код на безопасность перед развертыванием.

---

## Ссылки на ключевые файлы

- **Главный файл**: `app/main.py` - точка входа
- **Конфигурация**: `app/config.py` - настройки и валидация
- **Max-клиент**: `app/max_client.py` - WebSocket соединение
- **Telegram-отправитель**: `app/tg_sender.py` - отправка сообщений
- **Docker**: `docker-compose.yml` - оркестрация контейнеров
- **Dockerfile**: `Dockerfile` - сборка образов

## Контакты

Для вопросов и поддержки обратитесь к документации README.md или создайте issue в репозитории проекта.

---

*Этот файл создан для быстрого ориентирования в проекте при ограниченном контексте.*

---

## Дополнительная информация

### Версия проекта
- **Python**: 3.12+
- **Телеграм-бот**: python-telegram-bot >= 21.0
- **WebSocket**: aiohttp >= 3.9.0
- **Прокси**: aiohttp-socks >= 0.10.0

### Структура директорий
- **app/** - Основной код приложения
- **logs/** - Директория для логов (создается автоматически)
- **debug/** - Директория для отладочных данных (создается при DEBUG=true)

### Основные принципы
1. **Low-resource**: Оптимизирован для серверов с ограниченными ресурсами
2. **Docker-first**: Готов для контейнерного развертывания
3. **Backward-compatible**: Работает с Python 3.12+
4. **Secure**: Обеспечивает безопасность токенов и данных пользователей