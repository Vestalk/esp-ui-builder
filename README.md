# ESP32 UI Builder (`espui`)

Десктопна програма для візуального конструювання інтерфейсу дисплея ESP32
(ST7789, ILI9488, GC9A01 та дисплеї свого розміру).
Екран збирається мишею, а на виході — готовий код MicroPython: модуль `ui_<сторінка>.py` з класом `UI`
для кожної сторінки, драйвер, шрифти з українською абеткою і картинки для плати.

**Документація:** [`docs/overview.md`](docs/overview.md) — можливості, дисплеї, підключення, як почати
й код на платі.

**Макет інтерфейсу:** <https://vestalk.github.io/esp-ui-builder/plan.html> — інтерактивний HTML-макет
(джерело — [`docs/plan.html`](docs/plan.html)); показує початковий задум, частини сьогоднішніх
можливостей у ньому ще немає.

## Як запустити проєкт

Потрібен Python 3.11 або новіший (`python3 --version`). Готові збірки для Windows, macOS і Linux
можна зібрати з вихідного коду (розділ «Збірки»); нижче — запуск з вихідного коду.

### 1. Встановлення (один раз)

```sh
cd esp-ui-builder
python3 -m venv .venv                 # окреме середовище для проєкту
source .venv/bin/activate             # Windows: .venv\Scripts\activate
pip install -e .                      # програма і її залежності (PySide6, Pillow, FreeType…)
```

Додатково, за потреби:

```sh
pip install -e ".[video]"             # додавати відео (MP4, WebM) як анімації
pip install -e ".[dev]"               # тести й інструменти розробника
```

### 2. Запуск програми

```sh
source .venv/bin/activate             # у кожному новому терміналі
espui gui                             # відкрити програму
espui gui examples/weather.espui      # одразу з прикладом
```

Без активації середовища: `.venv/bin/espui gui` (Windows: `.venv\Scripts\espui gui`)
або `python -m espui gui`.

У програмі: **Файл → Відкрити…** → проєкт з `examples/`, правки мишею на полотні,
**▶ Згенерувати** → у вибраній папці створюється тека з назвою сторінки з файлами для плати. Проєкт зберігається автоматично.

### 3. Генерація без вікна (командний рядок)

```sh
espui generate examples/weather.espui -o out/
```

### 4. Запуск на платі

Згенеровану папку відкрийте у VS Code і виконайте команду MicroPico **«Upload project to Pico»**,
потім **Run** для `main.py`. Або через `mpremote`:

```sh
cd out
mpremote cp *.py :                    # код у корінь плати
mpremote cp -r img :                  # картинки, якщо папка img/ є
mpremote run main.py
```

Плата має бути прошита MicroPython, дисплей — підключений (типові піни й прошивка —
у [документації](docs/overview.md#підключення-esp32-s3-типово)).

### 5. Тести (для розробників)

```sh
pip install -e ".[dev]"
pytest                                # усі тести; GUI-тести працюють і без екрана
```

## Генерація коду для плати

```sh
espui generate examples/weather.espui -o out/   # усі сторінки; --page main — лише одну
cd out && mpremote cp *.py :    # або MicroPico «Upload project to Pico»
mpremote cp -r img :            # якщо є картинки
mpremote run main.py
```

У папці `out/` будуть `ui_display.py` (піни й SPI з проєкту), драйвер дисплея, `ui_draw.py`,
`ui_<сторінка>.py` з класом `UI` і приклад `main.py`:

```python
ui = ui_main.UI(ui_display.create())
p = dict(ui_main.DEFAULTS)
ui.draw(p)  # повна перемальовка
p["temperature"] = 23.4
ui.update(p)  # лише змінені елементи
ui.set_temperature(22)  # set_<параметр>() для кожного параметра
```

Приклади (`examples/*.espui`) і згенеровані з них папки:
[`examples/weather_mpy/`](examples/weather_mpy) (метеостанція з макета: базові елементи й умови),
[`examples/sensors_mpy/`](examples/sensors_mpy) (дашборд датчиків зі стрілкою),
[`examples/transforms_mpy/`](examples/transforms_mpy) (прозорість, поворот, позиція від параметра)
[`examples/chart_mpy/`](examples/chart_mpy) (графіки `series`: лінія, точки, стовпці),
[`examples/images_mpy/`](examples/images_mpy) (картинки й анімації)
і [`examples/pages_mpy/`](examples/pages_mpy) (дві сторінки з налаштуваннями, `show()` у `main.py`).

## Збірки

```sh
pip install -e ".[build]"
cd packaging && pyinstaller espui.spec      # dist/: ESP UI Builder.app (macOS) або espui/ (Windows, Linux)
```

Збірка містить шрифти, профіль дисплея, шаблони й runtime для плати. Той самий файл без аргументів
відкриває програму, з аргументами — це CLI (`espui generate …`). Збірка робиться на тій системі, для якої вона потрібна (Windows, macOS або Linux).

## Розробка

```sh
python3 -m venv .venv            # Python ≥ 3.11
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

ruff check . && ruff format --check .
mypy
pytest
```

Тести в `tests/mpy` виконують код на unix-порті MicroPython. Без нього вони пропускаються.
Шлях до бінарника задається змінною `ESPUI_MICROPYTHON` або береться з `micropython` у `PATH`.

## Структура

```
src/espui/        пакет: core, displays, assets, generators/micropython, gui, cli
tests/unit        тести на CPython
tests/mpy         тести на unix-порті MicroPython
tests/gui         тести GUI (pytest-qt)
tools/            скрипти для плати: hw_smoke.py, hw_driver_check.py, bench_display.py
examples/         приклади проєктів .espui
```

Підключення дисплея, сенсора й SD-карти — у [`docs/overview.md`](docs/overview.md).

Runtime для плати (адаптер `ui_display.py` і драйвери) лежить у `src/espui/generators/micropython/runtime/`.
