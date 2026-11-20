# Залізо: ESP32-S3 + GMT020-02-8B

> ⚠️ Заповнюється вручну після підключення плати. Значення з позначкою **TODO** потрібно перевірити або вписати.
> Піни мають збігатися з `PINS` у [`tools/hw_smoke.py`](../tools/hw_smoke.py).

## Плата

| Поле | Значення |
|---|---|
| Модуль / плата | TODO (напр. ESP32-S3-DevKitC-1 N16R8) |
| PSRAM | TODO (так / ні, обсяг) |
| Прошивка | `ESP32_GENERIC_S3` (або варіант `SPIRAM_OCT`, якщо модуль має octal PSRAM), версія TODO |
| `sys.implementation` | TODO (вивід у REPL: `import sys; print(sys.implementation)`) |
| Завантаження файлів | MicroPico TODO (стабільно / ні); запасний шлях: `mpremote` |

## Дисплей GMT020-02-8B ver 1.21

ST7789, 240×320, 4-wire SPI, RGB565.

| Пін модуля | Призначення | GPIO ESP32-S3 |
|---|---|---|
| GND | земля | GND |
| VCC | живлення | 3V3 |
| SCL | SPI SCK | **12** |
| SDA | SPI MOSI | **11** |
| RES | скидання | **8** |
| DC | дані / команда | **9** |
| CS | вибір чипа | **10** |
| BLK | підсвітка | **7** / немає — TODO |

- Пін BLK на модулі: TODO (є / немає; у частини модулів лише 7 пінів, тоді підсвітка ввімкнена завжди,
  у `hw_smoke.py` ставиться `"blk": None`).
- Заборонені піни: GPIO19/20 (USB), стрепи GPIO0, 3, 45, 46; GPIO26–32 (флеш/PSRAM), а на модулях з octal PSRAM також GPIO33–37.
- SPI: апаратний `SPI(2)`, 40 МГц.
- Інверсія кольорів (`INVERT` у `hw_smoke.py`): TODO (потрібна / ні).

## Фото / схема підключення

TODO: додати `docs/img/wiring.jpg` і посилання тут.

## Перевірка

1. Прошити плату:
   ```sh
   pip install esptool
   esptool.py --chip esp32s3 --port <PORT> erase_flash
   esptool.py --chip esp32s3 --port <PORT> write_flash -z 0 ESP32_GENERIC_S3-<версія>.bin
   ```
   Прошивка: <https://micropython.org/download/ESP32_GENERIC_S3/>.
2. VS Code → MicroPico: **Configure Project**, **Switch Stubs → ESP32**.
3. Відкрити `tools/hw_smoke.py` → **Run current file on Pico**, або `mpremote run tools/hw_smoke.py`.
4. Очікувано: червоний → зелений → синій → чорний, без смуг і зсувів; у REPL час заливки кожного кольору.

| Результат | Значення |
|---|---|
| Три кольори без артефактів | TODO |
| Час заливки екрана, мс | TODO |
