# ESP UI Builder (`espui`)

A desktop app for designing ESP32 display screens with the mouse. It generates ready-to-run
**MicroPython** code: no C, no compiling, no LVGL build. You flash stock MicroPython and copy the
files to the board.

Supported displays: ST7789, ILI9341, ILI9488 and GC9A01 panels, the ESP32 "Cheap Yellow
Display" (CYD), and custom sizes. Optional touch panels are XPT2046 and CST816S.

Each page becomes a `ui_<page>.py` module with a `UI` class. The app also generates:

- a display driver;
- bitmap fonts with Cyrillic glyphs;
- the page's pictures converted for the board.

**Website:** <https://vestalk.github.io/esp-ui-builder/>: screenshots, features and supported hardware.

**Documentation:** [`docs/overview.md`](docs/overview.md): features, displays, wiring, getting
started and the code on the board.

**Interactive mockup:** <https://vestalk.github.io/esp-ui-builder/plan.html>. This is an HTML
mockup of the editor; its source is [`docs/plan.html`](docs/plan.html).

> The interface is available in **English** and **Ukrainian**: **View → Мова / Language**. On
> first start the app follows the system language.

## Quick start

Requires Python 3.11 or newer (`python3 --version`).

### 1. Install (once)

```sh
cd esp-ui-builder
python3 -m venv .venv                 # a separate environment for the project
source .venv/bin/activate             # Windows: .venv\Scripts\activate
pip install -e .                      # the app and its dependencies (PySide6, Pillow, FreeType…)
```

Optional extras:

```sh
pip install -e ".[video]"             # add videos (MP4, WebM) as animations
pip install -e ".[dev]"               # tests and developer tools
```

### 2. Run the app

```sh
source .venv/bin/activate             # in every new terminal
espui gui                             # open the app
espui gui examples/weather.espui      # open it with an example
```

Without activating the environment: `.venv/bin/espui gui` (Windows: `.venv\Scripts\espui gui`)
or `python -m espui gui`.

To make a screen, follow these steps:

1. The start window offers a new project, recent files and the examples.
2. Edit the screen with the mouse on the canvas.
3. Click **▶ Generate**. In the folder you choose, the app creates a folder named
   after the page, with the files for the board.

Projects are saved automatically.

### 3. Generate from the command line

```sh
espui generate examples/weather.espui -o out/   # all pages; --page main for just one
```

### 4. Run on the board

Open the generated folder in VS Code and run the MicroPico command **"Upload project to Pico"**,
then **Run** `main.py`. Or use `mpremote`:

```sh
cd out
mpremote cp *.py :                    # code to the root of the board
mpremote cp -r img :                  # pictures, if there is an img/ folder
mpremote run main.py
```

The board must run MicroPython and the display must be wired. Default pins and firmware are
described in the [documentation](docs/overview.md#wiring-esp32-s3-defaults).

## The generated code

`out/` contains the following files:

- `ui_display.py`: pins and SPI settings from the project;
- the display driver and `ui_draw.py`;
- `ui_<page>.py` with the `UI` class;
- an example `main.py`.

Use the page like this:

```python
ui = ui_main.UI(ui_display.create())
p = dict(ui_main.DEFAULTS)
ui.draw(p)               # full redraw
p["temperature"] = 23.4
ui.update(p)             # redraws only what changed
ui.set_temperature(22)   # a set_<parameter>() for every parameter
```

Animated pictures play by themselves after `ui.draw()`: once by default, or in a loop if you
tick **Play in a loop** in the editor. `ui.play_<id>()` plays one again from your code. For
frame-by-frame control, use `ui.draw(p, animate=False)` and call `ui.tick()` yourself.

The generated folder also works as a package, wherever it lies on the board:
`from ui.main import ui_display, ui_main`.

### Examples

The example projects are `examples/*.espui`, and each has a generated folder next to it:

| Folder | What it shows |
|---|---|
| [`examples/weather_mpy/`](examples/weather_mpy) | Weather station: basic widgets and conditions |
| [`examples/sensors_mpy/`](examples/sensors_mpy) | Sensor dashboard with a gauge needle |
| [`examples/transforms_mpy/`](examples/transforms_mpy) | Opacity, rotation, position driven by a parameter |
| [`examples/chart_mpy/`](examples/chart_mpy) | `series` charts: line, dots, bars |
| [`examples/images_mpy/`](examples/images_mpy) | Pictures and animations |
| [`examples/pages_mpy/`](examples/pages_mpy) | Two pages switched with `show()` in `main.py` |

## Touch screen

To turn the touch panel on, open **Display…**, pick a model with touch, for example a
3.2" module or the CYD, and set up the **Touch screen** block. Two panels
are supported:

- **XPT2046**: resistive, on SPI;
- **CST816S**: capacitive, on I2C.

The rest of the page doesn't depend on the touch panel.

### Tap procedures

1. **In the editor:** select any widget that should act as a button (rectangle, circle, picture,
   text). In **On tap**, type the **name of a procedure**, e.g. `on_button`.
   Nothing else is needed in the editor.
2. **In your code:** write a function with that name and pass a "name → function" map to
   `draw()`. `listen_touch()` handles taps in the background, so you don't need a loop:

```python
from ui.main import ui_display, ui_main


def on_button():                    # runs once per tap
    p["count"] += 1                 # afterwards the page redraws what changed


display = ui_display.create()
ui = ui_main.UI(display)
p = dict(ui_main.DEFAULTS)
ui.draw(p, actions={"on_button": on_button})   # name from the editor → function
ui.listen_touch()                               # taps are handled in the background from now on
```

How taps behave:

- **`actions`** is only needed for taps.
  - Pass it once; later `draw()` and `update()` calls don't need it.
  - `actions=globals()` works too.
  - If a procedure named in the editor is missing from the map, `draw()` tells you which one.
- **Which widget gets the tap:**
  - the topmost widget with **On tap** under the finger;
  - a widget hidden by a condition doesn't catch taps;
  - text drawn over a button doesn't block it.
- **Keep procedures short.** The panel isn't read while one runs.
- **Stopping or polling yourself:**
  - `ui.stop_touch()` stops listening;
  - `ui.poll_touch()` handles taps in your own loop instead of the background.

### Touch coordinates

```python
touch = ui_display.create_touch(display)   # or: touch = ui.listen_touch()

point = touch.read()        # (x, y) in screen coordinates of the current rotation, or None
if point:
    x, y = point
    print("touch", x, y, "widget:", ui.hit(x, y))   # id of the widget with On tap, or None
```

- **`read()`** returns a point for as long as the finger is on the screen. A press is the change
  from `None` to a point.
- **Sharing the bus.** While `listen_touch()` runs, read the panel inside `with ui_draw.Busy():`
  (`import ui_draw`). Wrap your own devices on the same SPI bus the same way.
- **Raw values.** On the XPT2046, `touch.raw()` gives the raw `(x, y, pressure)`.

### Calibration (XPT2046)

If taps land in the wrong place, calibrate the panel on the board itself, after generating the
page:

```python
from ui.main import ui_display     # your page folder

ui_display.calibrate_touch()       # four crosses, one after another: touch each one
# prints: ESPUI-CAL x_min=3810 x_max=290 y_min=240 y_max=3705 swap_xy=1
```

Then apply it:

1. Paste the printed line into **Display… → Touch screen → From the board**. The
   calibration values and the swapped-axes checkbox fill in by themselves.
2. Generate the page again.

The **Calibration code** button next to that field copies the board code.
The capacitive CST816S needs no calibration.

### Checking taps in the editor

- **View → Tap zones** (Ctrl+Shift+T) shows where widgets with **On tap** catch taps, and which procedure each one runs:
  - **green**: fine;
  - **orange**: too small for a finger (under 36 px);
  - **grey**: hidden by a condition.
- **▶ Preview** (F5) treats a click on the page as a tap, the same way the board does.
  - The status bar shows the coordinates and the procedure that would run. Conditions and test
    values are taken into account.
  - Nothing gets selected or moved. Esc returns to editing.
- **Advice** appears under **On tap** and in the warnings after generation. It flags:
  - a button that is too small;
  - a button completely covered by another one;
  - **On tap** on a display without touch.

  None of it blocks generation.

## Language

The app speaks **English** and **Ukrainian**. On first start it follows the system language.

- **Switch it:** **View → Мова / Language**. The app offers to restart right away.
- **Set it per run:** `ESPUI_LANG=en espui gui` (or `uk`). This also applies to the messages of
  `espui generate`.

Project content stays as you wrote it: texts on the screens, parameter names and so on.

## Builds

```sh
pip install -e ".[build]"
cd packaging && pyinstaller espui.spec      # dist/: ESP UI Builder.app (macOS) or espui/ (Windows, Linux)
```

The build contains the fonts, display profiles, templates and the board runtime.

- **Two modes in one file:** without arguments it opens the app; with arguments it is the CLI
  (`espui generate …`).
- **Per system:** build on the system you need it for (Windows, macOS or Linux).

## Development

```sh
python3 -m venv .venv            # Python ≥ 3.11
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

ruff check . && ruff format --check .
mypy
pytest                           # GUI tests run without a screen too
```

**Translations.** User-facing texts are written in Ukrainian and wrapped in `tr()` from
`espui.i18n`. The English versions live in `src/espui/i18n_en.py`, keyed by the Ukrainian text.
Texts with values are templates: `tr("Вибрано {n}").format(n=3)`.
`tests/unit/test_i18n.py` fails if any text lacks a translation or a placeholder differs. The
tests themselves run in Ukrainian (`tests/conftest.py`).

The tests in `tests/mpy` run code on the MicroPython unix port and are skipped without it. Set
the binary with `ESPUI_MICROPYTHON`, or the tests use `micropython` from `PATH`.

## Project layout

```
src/espui/        the package: core, displays, assets, generators/micropython, gui, cli
tests/unit        tests on CPython
tests/mpy         tests on the MicroPython unix port
tests/gui         GUI tests (pytest-qt)
tools/            board scripts: hw_smoke.py, hw_driver_check.py, bench_display.py
examples/         example .espui projects and the code generated from them
```

The board runtime (the `ui_display.py` adapter and the drivers) lives in
`src/espui/generators/micropython/runtime/`.
