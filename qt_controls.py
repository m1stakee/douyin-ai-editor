"""Shared Qt selectors with an explicit arrow and readable popup sizing."""
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QPalette
from PySide6.QtWidgets import QComboBox as BaseComboBox, QLineEdit as BaseLineEdit, QStyle, QStyleOptionComboBox, QStylePainter, QStyledItemDelegate, QStyleOptionViewItem, QListView
from qt_theme import DROPDOWN_LIST_STYLE


class PlainSelectionDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(42, option.fontMetrics.height() + 16))
        return size

    def paint(self, painter, option, index):
        plain = QStyleOptionViewItem(option)
        if plain.state & QStyle.StateFlag.State_Selected:
            plain.palette.setColor(QPalette.ColorRole.Text, QColor('#65319a'))
        plain.state &= ~(QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_HasFocus)
        plain.rect.adjust(7, 0, -7, 0)
        super().paint(painter, plain, index)


class LineEdit(BaseLineEdit):
    def __init__(self, text=''):
        super().__init__(text)
        self.textChanged.connect(self.updateGeometry)

    def sizeHint(self):
        hint = super().sizeHint()
        text = self.displayText() or self.placeholderText()
        hint.setWidth(max(hint.width(), min(420, self.fontMetrics().horizontalAdvance(text) + 42)))
        return hint


class ComboBox(BaseComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaxVisibleItems(12)
        self.setSizeAdjustPolicy(BaseComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(5)
        self.setItemDelegate(PlainSelectionDelegate(self))
        self.view().setStyleSheet(DROPDOWN_LIST_STYLE)
        self.currentTextChanged.connect(self.updateGeometry)

    def setEditable(self, editable):
        super().setEditable(editable)
        if editable:
            popup = self.completer().popup()
            if popup is None:
                self.completer().setPopup(QListView())
                popup = self.completer().popup()
            popup.setStyleSheet(DROPDOWN_LIST_STYLE)
            popup.setItemDelegate(PlainSelectionDelegate(popup))

    def sizeHint(self):
        hint = super().sizeHint()
        width = self.fontMetrics().horizontalAdvance(self.currentText()) + 52
        hint.setWidth(max(hint.width(), min(420, width)))
        return hint

    def paintEvent(self, event):
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.state &= ~(QStyle.StateFlag.State_HasFocus | QStyle.StateFlag.State_Selected)
        base_painter = QStylePainter(self)
        base_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        base_painter.setBrush(QColor('white' if self.isEnabled() else '#f4f5f7'))
        base_painter.setPen(QPen(QColor('#70429d' if self.hasFocus() else '#dedce9'), 1))
        base_painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5), 7, 7)
        if not self.isEditable():
            field = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                                QStyle.SubControl.SC_ComboBoxEditField, self)
            base_painter.fillRect(field, QColor('white' if self.isEnabled() else '#f4f5f7'))
            base_painter.setPen(QColor('#272d3a' if self.isEnabled() else '#858b98'))
            text = self.fontMetrics().elidedText(self.currentText(), Qt.TextElideMode.ElideRight, field.width())
            base_painter.drawText(field, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        base_painter.end()
        rect = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                           QStyle.SubControl.SC_ComboBoxArrow, self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#e4dfed'), 1))
        painter.drawLine(rect.left(), 1, rect.left(), self.height()-2)
        painter.setPen(QPen(QColor('#70429d' if self.isEnabled() else '#b4adbe'), 1.8,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        center = rect.center()
        painter.drawLine(QPointF(center.x()-4, center.y()-2), QPointF(center.x(), center.y()+2))
        painter.drawLine(QPointF(center.x(), center.y()+2), QPointF(center.x()+4, center.y()-2))

    def showPopup(self):
        view = self.view()
        metrics = view.fontMetrics()
        width = max([self.width()] + [metrics.horizontalAdvance(self.itemText(i)) + 28 for i in range(self.count())])
        screen_width = self.screen().availableGeometry().width() if self.screen() else 1000
        view.setMinimumWidth(min(width, max(self.width(), min(720, screen_width-40))))
        view.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        super().showPopup()
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
