"""Small shared UI helpers."""
from __future__ import annotations
from decimal import Decimal
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor, QBrush
from PySide6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QMessageBox,
    QLineEdit, QDoubleSpinBox, QSpinBox,
)

NAVY = QColor("#0B2545")
ACCENT = QColor("#C5363A")
LIGHT = QColor("#F2F4F8")


def money_item(value: Decimal | float) -> QTableWidgetItem:
    d = Decimal(str(value))
    item = QTableWidgetItem(f"${d:,.2f}")
    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return item


def ro(text: str = "") -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    return item


def make_table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setAlternatingRowColors(True)
    hh = t.horizontalHeader()
    hh.setStretchLastSection(True)
    hh.setSectionResizeMode(QHeaderView.Interactive)
    return t


def confirm(parent, title: str, message: str) -> bool:
    return QMessageBox.question(parent, title, message,
        QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes


def info(parent, title: str, message: str) -> None:
    QMessageBox.information(parent, title, message)


def warn(parent, title: str, message: str) -> None:
    QMessageBox.warning(parent, title, message)


def dollars_spinbox(maximum: float = 1_000_000) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setDecimals(2)
    s.setMinimum(0)
    s.setMaximum(maximum)
    s.setSingleStep(1.00)
    s.setPrefix("$ ")
    return s


def qty_spinbox() -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setDecimals(2)
    s.setMinimum(0.01)
    s.setMaximum(999)
    s.setValue(1)
    s.setSingleStep(1)
    return s
