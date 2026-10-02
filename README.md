# Internet Speed Meter

Python-скрипт скачивает файл по URL **10 раз последовательно** и выводит среднее время запроса, общий объём данных и скорость в **Мбит/с**.

## Запуск

Python 3.10+, без сторонних зависимостей.

```bash
git clone https://github.com/Stepanda1/internet-speed-meter.git
cd internet-speed-meter
python speed_meter.py "https://speed.cloudflare.com/__down?bytes=1000000"
```

Можно передать свой URL картинки или файла. Таймаут операции сокета: `--timeout 60` (по умолчанию 30 секунд).

Скорость = суммарные байты × 8 / суммарное время / 1 000 000. Результат зависит от выбранного сервера. При ошибке скачивания замер прекращается.

## Тесты

```bash
python -m unittest discover -s tests -v
```
