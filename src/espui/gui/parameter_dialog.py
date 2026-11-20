"""Dialog "Новий параметр" / editing a parameter: fields per type, validated by ``core``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from espui.core.checks import check_parameter
from espui.core.evaluate import SeriesParseError, parse_series, series_to_text
from espui.core.issues import Issue, issues_from_validation_error
from espui.core.models import (
    PARAMETER_TYPES,
    EnumParameter,
    FloatParameter,
    IntParameter,
    Parameter,
    SeriesParameter,
    StrParameter,
)

TYPE_TITLES = {
    "float": "float — дробове число",
    "int": "int — ціле число",
    "bool": "bool — так / ні",
    "str": "str — рядок",
    "enum": "enum — варіанти",
    "series": "series — список {x: y}",
}
CHARSET_TITLES = {"latin_uk": "латиниця + українська", "latin": "латиниця", "digits": "цифри"}


def _spin(lo: float, hi: float, decimals: int = 2) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(lo, hi)
    spin.setDecimals(decimals)
    return spin


class ParameterDialog(QDialog):
    """Returns a valid ``Parameter`` from :meth:`parameter`; OK only when there are no errors."""

    def __init__(
        self,
        param: Parameter | None = None,
        name_problem: Callable[[Parameter], str | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.editing = param is not None
        self.setWindowTitle("Редагувати параметр" if self.editing else "Новий параметр")
        self.name_problem = name_problem or (lambda _p: None)
        self.errors: dict[str, QLabel] = {}

        self.name = QLineEdit()
        self.type = QComboBox()
        for kind in PARAMETER_TYPES:
            self.type.addItem(TYPE_TITLES[kind], kind)
        self.form = QFormLayout()
        self._row("Назва", self.name, "name")
        self._row("Тип", self.type, "type")

        self.pages = QStackedWidget()
        self.fields: dict[str, dict[str, QWidget]] = {}
        for kind in PARAMETER_TYPES:
            self.pages.addWidget(self._type_page(kind))

        buttons = QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        self.buttons = QDialogButtonBox(buttons)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Зберегти зміни" if self.editing else "Додати"
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.pages)
        layout.addWidget(self.buttons)

        if param is not None:
            self.load(param)
        else:
            self.name.setText("param")
        self.type.currentIndexChanged.connect(self._type_changed)
        self.name.textChanged.connect(self.validate)
        self._type_changed()

    # ------------------------------------------------------------------ layout
    def _row(self, title: str, widget: QWidget, key: str, form: QFormLayout | None = None) -> None:
        error = QLabel()
        error.setObjectName(f"error_{key}")
        error.setStyleSheet("color: #c0392b")
        error.setWordWrap(True)
        error.setVisible(False)
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        layout.addWidget(widget)
        layout.addWidget(error)
        (form or self.form).addRow(title, box)
        self.errors[key] = error

    def _type_page(self, kind: str) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        f: dict[str, QWidget] = {}
        if kind in ("float", "int", "series"):
            decimals = 0 if kind == "int" else 2
            f["min"] = _spin(-1e9, 1e9, decimals)
            f["max"] = _spin(-1e9, 1e9, decimals)
            self._row("Мін" if kind != "series" else "Y мін", f["min"], f"{kind}.min", form)
            self._row("Макс" if kind != "series" else "Y макс", f["max"], f"{kind}.max", form)
        if kind in ("float", "int"):
            f["default"] = _spin(-1e9, 1e9, 0 if kind == "int" else 2)
        elif kind == "bool":
            f["default"] = QCheckBox("true")
        elif kind == "str":
            f["max_len"] = QSpinBox()
            f["max_len"].setRange(2, 128)  # type: ignore[attr-defined]
            self._row("Макс. довжина", f["max_len"], "str.max_len", form)
            f["default"] = QLineEdit()
            f["charset"] = QComboBox()
            for key, title in CHARSET_TITLES.items():
                f["charset"].addItem(title, key)  # type: ignore[attr-defined]
            f["extra_chars"] = QLineEdit()
            f["extra_chars"].setPlaceholderText("додаткові символи, напр. №°")  # type: ignore[attr-defined]
        elif kind == "enum":
            f["values"] = QPlainTextEdit()
            f["values"].setPlaceholderText("по одному варіанту в рядку")  # type: ignore[attr-defined]
            f["values"].setMaximumHeight(90)
            self._row("Варіанти", f["values"], "enum.values", form)
            f["default"] = QComboBox()
        elif kind == "series":
            f["max_points"] = QSpinBox()
            f["max_points"].setRange(2, 256)  # type: ignore[attr-defined]
            self._row("Макс. точок", f["max_points"], "series.max_points", form)
            f["x_kind"] = QComboBox()
            f["x_kind"].addItem("число", "number")  # type: ignore[attr-defined]
            f["x_kind"].addItem("мітка до 7 символів", "label")  # type: ignore[attr-defined]
            self._row("Ключ X", f["x_kind"], "series.x_kind", form)
            f["default"] = QLineEdit()
            f["default"].setPlaceholderText("x:y; x:y")  # type: ignore[attr-defined]
        self._row("За замовчуванням", f["default"], f"{kind}.default", form)
        if kind == "str":
            self._row("Символи на платі", f["charset"], "str.charset", form)
            self._row("Ще символи", f["extra_chars"], "str.extra_chars", form)
        for widget in f.values():
            for signal in ("valueChanged", "textChanged", "toggled", "currentIndexChanged"):
                if hasattr(widget, signal):
                    getattr(widget, signal).connect(self.validate)
                    break
        if kind == "enum":
            f["values"].textChanged.disconnect()  # type: ignore[attr-defined]
            f["values"].textChanged.connect(self._enum_values_changed)  # type: ignore[attr-defined]
        self.fields[kind] = f
        return page

    @property
    def kind(self) -> str:
        return str(self.type.currentData())

    def _type_changed(self) -> None:
        self.pages.setCurrentIndex(PARAMETER_TYPES.index(self.kind))
        defaults = {"float": (0, 100, 50), "int": (0, 100, 50), "series": (0, 10, None)}
        f = self.fields[self.kind]
        if self.kind in defaults and f["min"].value() == f["max"].value() == 0:  # type: ignore[attr-defined]
            lo, hi, default = defaults[self.kind]
            f["min"].setValue(lo)  # type: ignore[attr-defined]
            f["max"].setValue(hi)  # type: ignore[attr-defined]
            if default is not None:
                f["default"].setValue(default)  # type: ignore[attr-defined]
        if self.kind == "str" and f["max_len"].value() == 2:  # type: ignore[attr-defined]
            f["max_len"].setValue(32)  # type: ignore[attr-defined]
        if self.kind == "series" and f["max_points"].value() == 2:  # type: ignore[attr-defined]
            f["max_points"].setValue(24)  # type: ignore[attr-defined]
        if self.kind == "enum" and not f["values"].toPlainText():  # type: ignore[attr-defined]
            f["values"].setPlainText("OK\nУвага\nПомилка")  # type: ignore[attr-defined]
        self.validate()

    def _enum_values_changed(self) -> None:
        combo: QComboBox = self.fields["enum"]["default"]  # type: ignore[assignment]
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(self._enum_values())
        index = combo.findText(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)
        self.validate()

    def _enum_values(self) -> list[str]:
        text = self.fields["enum"]["values"].toPlainText()  # type: ignore[attr-defined]
        return [line.strip() for line in text.splitlines() if line.strip()]

    # ------------------------------------------------------------------ load / read
    def load(self, param: Parameter) -> None:
        self.name.setText(param.name)
        self.type.setCurrentIndex(PARAMETER_TYPES.index(param.type))
        f = self.fields[param.type]
        if isinstance(param, FloatParameter | IntParameter | SeriesParameter):
            f["min"].setValue(param.min)  # type: ignore[attr-defined]
            f["max"].setValue(param.max)  # type: ignore[attr-defined]
        if isinstance(param, FloatParameter | IntParameter):
            f["default"].setValue(param.default)  # type: ignore[attr-defined]
        elif isinstance(param, StrParameter):
            f["max_len"].setValue(param.max_len)  # type: ignore[attr-defined]
            f["default"].setText(param.default)  # type: ignore[attr-defined]
            f["charset"].setCurrentIndex(f["charset"].findData(param.charset))  # type: ignore[attr-defined]
            f["extra_chars"].setText(param.extra_chars)  # type: ignore[attr-defined]
        elif isinstance(param, EnumParameter):
            f["values"].setPlainText("\n".join(param.values))  # type: ignore[attr-defined]
            self._enum_values_changed()
            f["default"].setCurrentText(param.default)  # type: ignore[attr-defined]
        elif isinstance(param, SeriesParameter):
            f["max_points"].setValue(param.max_points)  # type: ignore[attr-defined]
            f["x_kind"].setCurrentIndex(f["x_kind"].findData(param.x_kind))  # type: ignore[attr-defined]
            f["default"].setText(series_to_text(param.default))  # type: ignore[attr-defined]
        else:
            f["default"].setChecked(bool(param.default))  # type: ignore[attr-defined]

    def data(self) -> dict[str, Any]:
        kind = self.kind
        f = self.fields[kind]
        out: dict[str, Any] = {"name": self.name.text().strip(), "type": kind}
        if kind in ("float", "int", "series"):
            cast_ = int if kind == "int" else float
            out["min"] = cast_(f["min"].value())  # type: ignore[attr-defined]
            out["max"] = cast_(f["max"].value())  # type: ignore[attr-defined]
        if kind in ("float", "int"):
            out["default"] = (int if kind == "int" else float)(f["default"].value())  # type: ignore[attr-defined]
        elif kind == "bool":
            out["default"] = f["default"].isChecked()  # type: ignore[attr-defined]
        elif kind == "str":
            out["max_len"] = f["max_len"].value()  # type: ignore[attr-defined]
            out["default"] = f["default"].text()  # type: ignore[attr-defined]
            out["charset"] = f["charset"].currentData()  # type: ignore[attr-defined]
            out["extra_chars"] = f["extra_chars"].text()  # type: ignore[attr-defined]
        elif kind == "enum":
            out["values"] = self._enum_values()
            out["default"] = f["default"].currentText()  # type: ignore[attr-defined]
        elif kind == "series":
            out["max_points"] = f["max_points"].value()  # type: ignore[attr-defined]
            out["x_kind"] = f["x_kind"].currentData()  # type: ignore[attr-defined]
            out["default"] = []
        return out

    def parameter(self) -> tuple[Parameter | None, list[Issue]]:
        """The parameter, or None and the problems (path relative to the parameter)."""
        from pydantic import TypeAdapter

        from espui.core.models import Parameter as ParameterType

        data = self.data()
        try:
            param: Parameter = TypeAdapter(ParameterType).validate_python(data)
        except ValidationError as error:
            return None, issues_from_validation_error(error)
        if isinstance(param, SeriesParameter):
            text = self.fields["series"]["default"].text().strip()  # type: ignore[attr-defined]
            if text:
                try:
                    param = param.model_copy(update={"default": parse_series(text, param)})
                except SeriesParseError as error:
                    return None, [Issue("default", str(error))]
        issues = check_parameter(param, ())
        if not issues and (problem := self.name_problem(param)):
            issues = [Issue("name", problem)]
        return (param if not issues else None), issues

    # ------------------------------------------------------------------ validation
    def validate(self) -> bool:
        for label in self.errors.values():
            label.setVisible(False)
        param, issues = self.parameter()
        for issue in issues:
            field = issue.path.split(".")[0].split("[")[0] or "name"
            key = field if field in ("name", "type") else f"{self.kind}.{field}"
            label = self.errors.get(key) or self.errors["name"]
            label.setText(issue.message)
            label.setVisible(True)
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(param is not None)
        return param is not None
