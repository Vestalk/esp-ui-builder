# ESP UI Builder: documentation

ESP UI Builder is a desktop app for Windows, macOS and Linux. You design the screen of an ESP32
display with the mouse, and the app generates ready **MicroPython** code for the board.

- **Nothing to compile.** Use stock MicroPython firmware and copy the files to the board as they
  are, with MicroPico in VS Code or with `mpremote`.
- **Interface language:** English or Ukrainian, **View → Мова / Language** (the app restarts to
  apply it). On first start it follows the system language.

[Interactive mockup](https://vestalk.github.io/esp-ui-builder/plan.html): an HTML mockup of the
editor.

## Features

### Building a screen

- **Widgets:** rectangle, circle, line, text, number, progress bar, arc, picture (including
  animations from GIF), chart. Each has layers, opacity and rotation around any point.
- **Parameters:** the values your code changes on the board (temperature, state, a label…).
- **Conditions and mappings:**
  - set colour, text, visibility, opacity, angle, x or y, e.g. "if `t > 30`" or "if `t` is in
    the range 18…25";
  - drive a property smoothly from a value, e.g. a gauge needle angle;
  - **test values** show the result in the app right away.
- **Several pages** in one project.
- **Fonts with Cyrillic glyphs** (Literata, JetBrains Mono, Press Start 2P, 8–72 px). Only the
  characters and sizes in use go to the board.
- **Progress bar and arc:** separate fill and track colours; the track and the number can each
  be shown or hidden.

### On the board

- **Fast redraw:** only what changed is redrawn.
- **Display → Memory** sets the area buffer and the picture cache for your
  board. With PSRAM, changes appear at once, without visible strips.
- **Checks before generation:**
  - project errors;
  - pins that are taken or used twice;
  - a flash and RAM estimate.

### Editing

- **Several widgets at once:**
  - **selecting:** Shift+click, a frame dragged over an empty part of the page (with Shift it
    adds to the selection), Shift or Ctrl(⌘)+click in **Layers**;
  - **acting on all of them:** drag, nudge with the arrows, delete, copy, colour and opacity.
- **Groups** in **Arrange**:
  - group with Ctrl+Shift+G, ungroup with Ctrl+Shift+U;
  - a click selects the whole group; Ctrl(⌘)+click selects one widget of it;
  - editor only.
- **Arrange:**
  - align left, centre, right, top, middle or bottom;
  - distribute with equal gaps;
  - several widgets align to the selection, a single one to the screen.
- **👁 and 🔒 in Layers:**
  - 👁 hides a widget in the editor, to reach what lies below it;
  - 🔒 locks it, so the canvas can't select or move it (e.g. a background);
  - both are editor only: the board draws the same page;
  - also in **Edit**: Ctrl+Shift+H, Ctrl+Shift+L, "show and unlock everything".
- **Copy / paste / duplicate** (Ctrl+C / Ctrl+V / Ctrl+D) on the canvas or in Layers, including
  onto another page. The parameters a widget needs are copied with it.
- **Project colours:**
  - swatches under the colour field show the project palette and the colours already on the
    page;
  - ＋ adds a colour, right-click removes it;
  - the palette is saved in the project.
- **Property blocks:**
  - they collapse, with a summary in the header;
  - "collapse all / expand all" buttons;
  - **On tap** has its own block.
- **Autosave**, undo and redo, and recovery after a crash.

### Touch in the editor

- **Tap zones:** Ctrl+Shift+T.
- **▶ Preview** (F5): a click works like a finger tap and shows which procedure would
  run.
- **Advice** about buttons that are too small or covered by another one.
- **XPT2046 calibration** on the board (`ui_display.calibrate_touch()`). Paste the result into
  **Display…**.

### Getting around

- **Start window:**
  - new project (the display dialog opens right away), open, recent projects, examples;
  - reopen it with **File → Start window…**.
- **Help:**
  - topics with a search;
  - F1 opens the topic for where the cursor is;
  - "?" in the block headers.

## Displays and boards

| Display | Size | Controller | Touch |
|---|---|---|---|
| GMT020-02-8B 2.0" | 240×320 | ST7789 | — |
| 3.2" TFT with touch | 240×320 | ILI9341 | XPT2046 |
| 3.2" IPS with touch | 240×320 | ST7789 | XPT2046 |
| ESP32 CYD 2.8" (ESP32-2432S028R; the 2-USB version uses ST7789) | 240×320 | ILI9341 / ST7789 | XPT2046 on its own pins |
| 3.5" IPS HD | 480×320 | ILI9488 (18-bit colour over SPI) | — |
| 1.28" round IPS | 240×240 | GC9A01 | — |
| Custom size | 16…800 px | ST7789 / ILI9341 / ILI9488 / GC9A01, memory offset, RGB/BGR | any |

3.2" modules come with either ILI9341 or ST7789. Check the label on the back, or try both
profiles. Profiles with touch suggest the XPT2046 right away; you can switch it off.

**ESP32 CYD** is a board with the display built in. Choose a CYD profile, and the app sets the
chip and pins as wired on the board:

| Part | Pins |
|---|---|
| Chip | ESP32 |
| Display | SCK 14, MOSI 13, CS 15, DC 2, backlight 21 |
| Touch (its own bus) | T_CLK 25, T_DIN 32, T_DO 39, T_CS 33, T_IRQ 36 |

Calibrate the touch panel for your board in **Display… → Touch screen**.

**Boards:**

- **ESP32-S3** (recommended), ESP32, ESP32-C3.
- Optional **touch panel:** XPT2046 (SPI) or CST816S (I2C).

## Wiring (ESP32-S3, defaults)

| Display | GPIO | | Touch | GPIO |
|---|---|---|---|---|
| VCC / GND | 3V3 / GND | | MISO (T_DO) | 13 |
| SCL (SCK) | 12 | | T_CS / T_IRQ (XPT2046) | 14 / 15 |
| SDA (MOSI) | 11 | | CST816S SDA / SCL / INT | 16 / 17 / 18 |
| DC | 9 | | | |
| CS | 10 (optional) | | | |
| RES | 8 (optional) | | | |
| BLK | 7 (optional) | | | |

**Touch bus.** By default the XPT2046's T_CLK and T_DIN share the display's SCL and SDA GPIOs.
Alternatively, give it pins of its own (T_CLK / T_DIN / T_DO), as on the CYD.

**GPIOs to avoid:**

- 19–20 (USB);
- 26–37 (flash and PSRAM);
- 0, 3, 45, 46 (boot mode).

Choose other pins in **Display…**; it tells you if a pin is taken.

## Getting started

1. **Install** (Python ≥ 3.11):
   ```sh
   python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -e .
   espui gui                                            # or: python -m espui gui
   ```
2. **Flash the board.** Get MicroPython for your chip from
   [micropython.org/download](https://micropython.org/download/). For an ESP32-S3 with PSRAM,
   take the `SPIRAM_OCT` variant.
   ```sh
   esptool.py --chip esp32s3 --port <PORT> erase_flash
   esptool.py --chip esp32s3 --port <PORT> write_flash -z 0 <firmware>.bin
   ```
3. **Design the screen:**
   1. In **Display…**, set the model, pins and memory.
   2. Place widgets on the page.
   3. Add parameters and conditions.
4. **▶ Generate**:
   1. Pick a folder.
   2. The app asks to confirm where it writes, and whether it replaces existing files.
   3. A folder named after the page appears in it.
5. **To the board:**
   1. Upload the folder with MicroPico ("Upload project") or `mpremote cp -r <folder> :`.
   2. Import the page in your own `main.py`.

## Code on the board

```python
import time

from ui.main import ui_display, ui_main   # the page folder on the board: /ui/main

display = ui_display.create()
ui = ui_main.UI(display)
p = dict(ui_main.DEFAULTS)                # every parameter with its default value
ui.draw(p)                                # full redraw

while True:
    p["temperature"] = read_sensor()      # your code
    ui.update(p)                          # redraws only what changed
    time.sleep(1)
```

### Animations

Animated pictures (GIF, video, several frames) **play by themselves** after `ui.draw()`; you
don't need a loop for them.

- **Once or in a loop.** By default an animation plays **once** and stops on its last frame.
  Tick **Play in a loop** in the picture's properties to repeat it.
- **Play again from your code:** `ui.play_<id>()` or `ui.play("<id>")` starts it from the
  first frame. `ui.playing("<id>")` tells whether it is still running.
- **Frame by frame:** call `ui.draw(p, animate=False)`, then call `ui.tick()` yourself whenever
  the next frames are due.
- **Stopping:**
  - `ui.stop_animations()` stops them;
  - `ui.stop()` stops all background work (animations and touch), e.g. before showing another
    page.

The background work uses one hardware timer, `Timer(0)`, shared with the touch panel. Once every
"once" animation has finished, the timer stops.

Touch, if enabled in **Display…**:

```python
touch = ui_display.create_touch(display)
point = touch.read()                      # (x, y) on the screen, or None
```

### Tapping widgets

In the editor, a button only gets a **procedure name**: the **On tap** field,
e.g. `start_pump`. The procedures themselves live in your project's code. Pass a
"name → function" map to `draw()`, and the touch panel is read in the background, with no loop:

```python
from ui.main import ui_display, ui_main

def start_pump():                         # called once per tap
    p["status"] = "Running"

def stop_pump():
    p["status"] = "Stopped"

display = ui_display.create()
ui = ui_main.UI(display)
p = dict(ui_main.DEFAULTS)
ui.draw(p, actions={"start_pump": start_pump, "stop_pump": stop_pump})
ui.listen_touch()                         # taps are handled in the background from now on
```

**How taps work:**

- **Missing procedures.** If a procedure named in the editor is missing from the map, `draw()`
  tells you which one.
- **Redraw.** After a procedure runs, the page redraws whatever changed in `p`.
- **Which widget gets the tap.** The topmost widget with **On tap** catches it; one hidden by
  a condition doesn't.
- **Keep functions short.** The panel isn't read while one runs.
- **Your own devices on the same SPI bus** (e.g. an SD card you wired yourself): wrap their code
  in `with ui_draw.Busy():`, so a tap can't cut into it.
- **Other calls:**
  - `ui.stop_touch()` stops listening;
  - `ui.hit(x, y)` gives the id of the widget under a point.

**Where the page lives on the board.** The generated folder can lie anywhere on the board and
is imported as a package (`from ui.main import …`). Copied to the root of the board, its files
can also be imported directly (`import ui_display`). Generating into the same folder again
replaces the page's files.

## Troubleshooting

- **Black screen:**
  - the pins in **Display…** don't match the wiring;
  - or another program holds the port.
- **A "negative" image, or red and blue swapped:** change **colour inversion** or the colour
  order (RGB/BGR).
- **A grey rectangle instead of a picture:** the `img/` folder wasn't uploaded to the board.
- **`MemoryError`:**
  - reduce the area buffer and the picture cache in **Display → Memory**;
  - or use smaller animations, or fewer font sizes.
- **The board keeps rebooting:** `main.py` fails before drawing. Interrupt the start with
  Ctrl+C in the console and read the message.
