"""Built-in help ("Довідка", F1): short topics, a search, "?" buttons open the right one."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from espui.i18n import tr

TOPICS: dict[str, tuple[str, str]] = {
    "start": (
        tr("Як почати"),
        tr("""
1. **Дисплей…** — виберіть модуль (або плату CYD), чип і піни, як підключено.
2. Перетягніть елементи з панелі «Елементи» на сторінку.
3. У «Параметрах» додайте значення, які міняє ваш код (температура, стан…), і прив'яжіть
   до них елементи: «Дані з параметра», умови.
4. **▶ Згенерувати…** (Ctrl+G) — виберіть теку: у ній з'явиться тека з назвою сторінки.
   Залийте її на плату (MicroPico) у `/ui/` і підключіть у `main.py`:

```python
from ui.main import ui_display, ui_main

ui = ui_main.UI(ui_display.create())
p = dict(ui_main.DEFAULTS)
ui.draw(p)              # усе сторінки
p["temperature"] = 21.5
ui.update(p)            # лише те, що змінилося
```
"""),
    ),
    "canvas": (
        tr("Полотно: виділення й переміщення"),
        tr("""
- **Клік** — вибрати елемент; **Shift+клік** — додати або прибрати з виділення.
- **Рамка мишею** по порожньому місцю сторінки — виділити все, чого вона торкається
  (з Shift — додати). Перетягування поза сторінкою прокручує полотно.
- **Перетягування** — рух (прив'язка до сітки 4 px; Alt — без неї); маркери — розмір;
  круглий маркер — точка повороту.
- **Стрілки** — зсув на 1 px, з Shift — на 10 px. **Delete** — видалити.
- **Ctrl+C / Ctrl+V / Ctrl+D** — копіювати, вставити, дублювати (разом із параметрами).
- Колесо — прокрутка, **Ctrl+колесо** — масштаб.
"""),
    ),
    "arrange": (
        tr("Розташування, групи, шари"),
        tr("""
- **Розташування** → вирівняти (ліво, центр, право, верх, середина, низ) і розподілити з
  рівними проміжками. Кілька елементів — відносно виділення, один — відносно екрана.
- **Групи** (Ctrl+Shift+G, розгрупувати — Ctrl+Shift+U): клік по будь-якому елементу групи
  виділяє всю групу; **Ctrl(⌘)+клік** — один елемент усередині. На плату групи не впливають.
- **Шари**: верхній рядок малюється поверх інших; порядок — перетягуванням, ↑/↓ або
  Ctrl+↑/↓. **👁** — сховати в редакторі, **🔒** — заблокувати на полотні (напр. фон).
"""),
    ),
    "properties": (
        tr("Властивості елемента"),
        tr("""
- **id** — ім'я елемента в коді (латиниця, цифри, `_`).
- **Дані з параметра** — елемент показує значення параметра; **Формат** — `%d`, `%.1f °C`…
- **Колір** — кнопка, поле `#rrggbb` або квадратик **палітри проєкту** (＋ — додати поточний
  колір, правий клік — прибрати).
- Блоки згортаються кліком по заголовку; «Згорнути всі / Розгорнути всі» — угорі панелі.
- Кілька виділених елементів: спільні колір, непрозорість і розташування.
"""),
    ),
    "rules": (
        tr("Умови"),
        tr("""
Умова міняє властивість елемента залежно від параметра, наприклад:

- `temperature > 30` → колір `#ff0000`;
- `level` **у діапазоні** 20…80 → видимий;
- **Залежність** (map): параметр 0…100 → кут 0…270° або x 10…200 — плавно.

Умови перевіряються згори вниз; спрацьовує остання, що підходить. Перевірити — у панелі
«Тестові значення».
"""),
    ),
    "parameters": (
        tr("Параметри і тестові значення"),
        tr("""
Параметри — це значення, які задає код на платі: `p["назва"] = значення`, потім
`ui.update(p)`. Типи: float, int, bool, str, enum, series (для графіка).

**Тестові значення** — що показати в редакторі зараз, щоб побачити сторінку в різних станах.
На плату вони не потрапляють (там — значення «за замовчуванням»).
"""),
    ),
    "display": (
        tr("Дисплей і піни"),
        tr("""
- **Модель**: готові профілі (GMT020, ILI9341, ST7789, ILI9488, GC9A01, плата CYD) або
  свій розмір. Плата CYD сама ставить чип і піни.
- **Піни**: SCK, MOSI, DC обов'язкові; CS, RST, підсвітка — якщо є на модулі.
- **Пам'ять**: розмір буфера й кеш картинок — для плавності на платах із PSRAM.
- Якщо кольори навпаки — «Інверсія кольорів».
"""),
    ),
    "touch": (
        tr("Сенсор і натиски"),
        tr("""
1. **Дисплей → Сенсорний екран**: XPT2046 (резистивний, SPI) або CST816S (ємнісний, I2C).
2. Елементу задайте **«При натиску»** — назву процедури, напр. `start_pump`.
3. На платі передайте процедури у `draw()`:

```python
def start_pump():
    p["status"] = "Працює"

ui.draw(p, actions={"start_pump": start_pump})
ui.listen_touch()      # натиски обробляються у фоні
```

- **Вигляд → Зони натиску** — де елементи ловлять дотик (помаранчеві — замалі).
- **▶ Перегляд** (F5) — клацання як натиск: видно, яка процедура спрацює. Esc — назад.
- **Калібрування** XPT2046: на платі `ui_display.calibrate_touch()`, торкніться 4 хрестиків,
  вставте надрукований рядок `ESPUI-CAL …` у «Дисплей → Сенсорний екран → З плати».
"""),
    ),
    "images": (
        tr("Картинки й анімація"),
        tr("""
Картинка — PNG/JPG, перетворюється у файл для плати (`img/…`). Кілька кадрів (GIF, відео) —
анімація з затримкою. Великі картинки займають пам'ять: дивіться оцінку в «Генерації».

**Анімація на платі програється сама** після `ui.draw()` — один раз (зупиняється на
останньому кадрі) або циклічно, якщо стоїть галочка **«Програвати циклічно»**.

```python
ui.play_icon()                # знову з першого кадру (або ui.play("icon"))
ui.draw(p, animate=False)     # покадрово: далі кадри перемикає ваш ui.tick()
ui.stop()                     # зупинити фонову роботу (напр. перед іншою сторінкою)
```

Картинки заливайте на плату окремо (mpremote), якщо MicroPico не впорається з bin-файлами.
"""),
    ),
    "generate": (
        tr("Генерація і плата"),
        tr("""
**▶ Згенерувати…** створює у вибраній теці теку з назвою сторінки; наявні файли
замінюються (програма перепитає). Тека — це пакет:

```python
from ui.main import ui_display, ui_main
```

Згенерований `main.py` — лише приклад, свій `main.py` пишете ви. Поради й попередження
(напр. замалі кнопки) — у вікні після генерації.
"""),
    ),
    "keys": (
        tr("Гарячі клавіші"),
        tr("""
| Дія | Клавіші |
|---|---|
| Згенерувати | Ctrl+G |
| Скасувати / Повторити | Ctrl+Z / Ctrl+Shift+Z (Ctrl+Y) |
| Копіювати / Вставити / Дублювати | Ctrl+C / Ctrl+V / Ctrl+D |
| Шар вище / нижче | Ctrl+↑ / Ctrl+↓ |
| Згрупувати / Розгрупувати | Ctrl+Shift+G / Ctrl+Shift+U |
| Сховати / Заблокувати | Ctrl+Shift+H / Ctrl+Shift+L |
| Зони натиску | Ctrl+Shift+T |
| Перегляд | F5 (Esc — вийти) |
| Сітка | Ctrl+' |
| Довідка | F1 |

На macOS замість Ctrl — ⌘.
"""),
    ),
}


class HelpDialog(QDialog):
    """Topics on the left (with a search), the text on the right; stays open beside the work."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Довідка — ESP UI Builder"))
        self.resize(820, 560)
        self.search = QLineEdit()
        self.search.setObjectName("help_search")
        self.search.setPlaceholderText(tr("Пошук у довідці…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.topics = QListWidget()
        self.topics.setObjectName("help_topics")
        self.topics.setMaximumWidth(240)
        for key, (title, _text) in TOPICS.items():
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.topics.addItem(item)
        self.topics.currentItemChanged.connect(self._show)
        self.text = QTextBrowser()
        self.text.setObjectName("help_text")
        self.text.setOpenExternalLinks(True)
        left = QVBoxLayout()
        left.addWidget(self.search)
        left.addWidget(self.topics, 1)
        layout = QHBoxLayout(self)
        layout.addLayout(left)
        layout.addWidget(self.text, 1)
        self.open_topic("start")

    @property
    def topic(self) -> str | None:
        item = self.topics.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def open_topic(self, key: str) -> None:
        for i in range(self.topics.count()):
            item = self.topics.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == key:
                item.setHidden(False)
                self.topics.setCurrentItem(item)
                return

    def _show(self, item: QListWidgetItem | None) -> None:
        if item is None:
            self.text.clear()
            return
        title, text = TOPICS[item.data(Qt.ItemDataRole.UserRole)]
        self.text.setMarkdown(f"# {title}\n{text}")

    def _filter(self, query: str) -> None:
        """Topics whose title or text has every word of the query."""
        words = query.lower().split()
        first = None
        for i in range(self.topics.count()):
            item = self.topics.item(i)
            title, text = TOPICS[item.data(Qt.ItemDataRole.UserRole)]
            haystack = f"{title}\n{text}".lower()
            shown = all(w in haystack for w in words)
            item.setHidden(not shown)
            if shown and first is None:
                first = item
        current = self.topics.currentItem()
        if first is not None and (current is None or current.isHidden()):
            self.topics.setCurrentItem(first)
        elif first is None:
            self.text.setMarkdown(tr("Нічого не знайдено."))


_dialog: HelpDialog | None = None


def show_help(topic: str = "start", parent: QWidget | None = None) -> HelpDialog:
    """Open (or bring up) the help window on ``topic``."""
    global _dialog
    if _dialog is None or (parent is not None and _dialog.parent() is not parent.window()):
        _dialog = HelpDialog(parent.window() if parent is not None else None)
    _dialog.search.clear()
    _dialog.open_topic(topic)
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()
    return _dialog
