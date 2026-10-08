# TG-Sender

Система массовой рассылки сообщений по личным контактам в Telegram.

## Установка зависимостей

```bash
uv sync
```

## Основные команды

### 1. Управление аккаунтами

#### Импорт TData (папки, zip-архивы, вложенные zip-архивы)

Положите архивы или папки с `tdata` в `data/tdata_inbox/` (поддерживаются вложенные архивы любой глубины, папки с tdata, а также автоопределение `proxy.txt` рядом с аккаунтом):

```bash
uv run tg-sender accounts import-tdata
```

С автоматической очисткой inbox после успешного импорта:

```bash
uv run tg-sender accounts import-tdata --clean
```

Или указать произвольную папку:

```bash
uv run tg-sender accounts import-tdata --path /path/to/my/archives
```

#### Автоматическая привязка прокси из файла

Поместите список ваших прокси в `data/proxies.txt` (по одному прокси на строку):

- `host:port:username:password`
- `socks5://user:pass@host:port`
- `http://user:pass@host:port`
- `host:port`

При первом запуске (`send`, `check`, `list` или `import-tdata`) система автоматически привяжет каждому аккаунту без прокси свой уникальный прокси из `data/proxies.txt` и сохранит его в базу SQLite.

Вы также можете запустить привязку вручную или указать кастомный файл:

```bash
uv run tg-sender accounts assign-proxies
uv run tg-sender accounts assign-proxies --file path/to/my_proxies.txt
```

#### Проверка состояния аккаунтов

Проверка доступности и авторизации всех аккаунтов:

```bash
uv run tg-sender accounts check
```

Проверка аккаунтов напрямую без прокси:

```bash
uv run tg-sender accounts check --no-proxy
```

Проверка аккаунтов через конкретный прокси:

```bash
uv run tg-sender accounts check --proxy socks5://127.0.0.1:9050
```

Список подключенных аккаунтов:

```bash
uv run tg-sender accounts list
```

### 2. Импорт контактов

Импорт базы из CSV, XLSX или TXT:

```bash
uv run tg-sender contacts import data/sample_contacts.csv
```

Просмотр очереди контактов:

```bash
uv run tg-sender contacts list --status PENDING
```

Очистка контактов:

```bash
uv run tg-sender contacts clear
```

### 3. Предпросмотр шаблона и Spintax

```bash
uv run tg-sender preview --template data/templates/sample_message.txt --count 3
```

### 4. Тестовый запуск (Dry-Run)

Проверка логики рассылки без реальной отправки сообщений:

```bash
uv run tg-sender send --template data/templates/sample_message.txt --dry-run
```

### 5. Боевой запуск рассылки

Стандартный запуск (с индивидуальными прокси каждого аккаунта):

```bash
uv run tg-sender send --template data/templates/sample_message.txt
```

Запуск **без прокси** (прямое подключение для всех аккаунтов):

```bash
uv run tg-sender send --template data/templates/sample_message.txt --no-proxy
```

Запуск с принудительным переопределением общего прокси для всех аккаунтов:

```bash
uv run tg-sender send --template data/templates/sample_message.txt --proxy socks5://user:pass@host:port
```

Параметры запуска:

- `--template` / `-t`: Текст сообщения или путь к файлу шаблона.
- `--media` / `-m`: Путь к прикрепляемому файлу (изображение, документ).
- `--limit` / `-l`: Ограничение количества контактов на запуск.
- `--min-delay` / `--max-delay`: Пользовательский диапазон задержки между сообщениями.
- `--concurrency` / `-c`: Количество параллельно работающих аккаунтов-воркеров (по умолчанию работают все доступные активные аккаунты).
- `--no-proxy`: Отключение любых прокси (прямое подключение).
- `--proxy` / `-p`: Принудительный единый прокси (socks5, socks4, http).
- `--dry-run`: Режим симуляции.

### 6. Статистика и экспорт отчетов

Просмотр статистики:

```bash
uv run tg-sender stats
```

Выгрузка отчета:

```bash
uv run tg-sender export data/report.xlsx
```
