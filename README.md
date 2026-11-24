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

## Сенсорний екран

Дисплей із сенсором вмикається в програмі: **Дисплей…** → модель (напр. «3.2" … з сенсором»)
і блок **«Сенсорний екран»** — XPT2046 (резистивний, SPI: потрібен пін MISO) або CST816S
(ємнісний, I2C). Інші налаштування сторінки від сенсора не залежать.

### Процедури на натискання

1. У редакторі виділіть елемент-кнопку (будь-який: прямокутник, коло, картинка, текст) і в полі
   **«При натиску»** впишіть **назву процедури**, напр. `on_button`. Більше в редакторі нічого
   не треба.
2. У коді проєкту напишіть процедуру з такою назвою і передайте мапу «назва → процедура» у
   `draw()`; `listen_touch()` вмикає обробку дотиків у фоні — циклу не треба:

```python
from ui.main import ui_display, ui_main


def on_button():                    # виконується один раз на кожне натискання
    p["count"] += 1                 # після процедури сторінка сама перемалює змінене


display = ui_display.create()
ui = ui_main.UI(display)
p = dict(ui_main.DEFAULTS)
ui.draw(p, actions={"on_button": on_button})   # назва з редактора → процедура
ui.listen_touch()                               # далі натискання обробляються у фоні
```

- `actions` потрібен лише для натискань; передається один раз (наступні `draw()` / `update()` —
  без нього). Можна й `actions=globals()`. Якщо якоїсь процедури з редактора в мапі немає,
  `draw()` одразу скаже, якої саме.
- Натискання ловить верхній елемент із «При натиску»; схований умовою — не ловить; текст поверх
  кнопки не заважає.
- Процедури мають бути короткими: поки одна виконується, сенсор не читається.
- `ui.stop_touch()` — перестати слухати; `ui.poll_touch()` — обробити дотики у власному циклі
  замість фону.

### Координати дотику

```python
touch = ui_display.create_touch(display)   # або: touch = ui.listen_touch()

point = touch.read()        # (x, y) у координатах екрана поточної орієнтації, або None
if point:
    x, y = point
    print("дотик", x, y, "елемент:", ui.hit(x, y))   # id елемента з «При натиску» або None
```

- `read()` повертає точку весь час, поки палець на екрані; момент натискання — перехід від `None`
  до точки.
- Якщо одночасно працює `listen_touch()`, читайте сенсор усередині `with ui_draw.Busy():`
  (`import ui_draw`) — так само загортайте й інші свої пристрої на тій самій шині SPI.
- XPT2046: `touch.raw()` дає сирі значення `(x, y, тиск)`.

### Калібрування (XPT2046)

Якщо дотик потрапляє не туди — відкалібруйте сенсор на самій платі (після генерації сторінки):

```python
from ui.main import ui_display     # ваша тека сторінки

ui_display.calibrate_touch()       # 4 хрестики по черзі — торкніться кожного
# друкує: ESPUI-CAL x_min=3810 x_max=290 y_min=240 y_max=3705 swap_xy=1
```

Скопіюйте надрукований рядок у **Дисплей → Сенсорний екран → «З плати»** — значення
калібрування й «Осі X і Y переставлені» заповняться самі; перегенеруйте сторінку. Код для
плати копіює кнопка **«Код калібрування»** там само. Ємнісний CST816S калібрування не потребує.

### Перевірка в редакторі

- **Вигляд → Зони натиску** (Ctrl+Shift+T): де елементи з «При натиску» ловлять дотик і яка
  процедура — зелені; **помаранчеві** — замалі для пальця (менше 36 px); сірі — сховані умовою.
- **▶ Перегляд** (F5, на панелі інструментів): клацання по сторінці — це натиск, як на платі; у
  статусі видно координати й процедуру, яка спрацює (з урахуванням умов і тестових значень).
  Нічого не виділяється й не рухається; Esc — назад до редагування.
- Поради: замала кнопка, кнопка під іншою, «При натиску» без сенсора — під полем «При натиску»
  і в попередженнях після генерації. Генерувати вони не заважають.

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
