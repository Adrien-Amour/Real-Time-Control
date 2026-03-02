from decimal import Decimal, getcontext
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QValidator
from PyQt5.QtWidgets import QSpinBox, QDoubleSpinBox, QApplication, QWidget, QVBoxLayout, QLabel

getcontext().prec = 50  # high precision for Decimal math

def _digit_positions(clean_text):
    """
    Build a map from char index -> digit ordinal k (0..N-1 over digits only),
    and return (index_to_k, k_to_index, int_digits, dec_index).
    dec_index is the index of the decimal separator in clean_text, or len(clean_text) if none.
    int_digits counts digits before the decimal separator.
    """
    dec_index = clean_text.find('.')
    if dec_index < 0:
        dec_index = len(clean_text)

    index_to_k = {}
    k_to_index = []
    k = 0
    for i, ch in enumerate(clean_text):
        if ch.isdigit():
            index_to_k[i] = k
            k_to_index.append(i)
            k += 1
    # count digits before decimal point
    int_digits = sum(1 for i, ch in enumerate(clean_text[:dec_index]) if ch.isdigit())
    return index_to_k, k_to_index, int_digits, dec_index

def _nearest_digit_k(clean_text, cursor_pos, left=True):
    """
    Find the digit ordinal k under the caret (left=True means digit to the left of caret,
    left=False means the one to the right). Returns k or None if no digits.
    """
    index_to_k, k_to_index, _, _ = _digit_positions(clean_text)
    if not k_to_index:
        return None

    # clamp cursor to [0, len]
    cursor_pos = max(0, min(cursor_pos, len(clean_text)))

    if left:
        # search left-of-caret
        i = cursor_pos - 1
        while i >= 0:
            if i in index_to_k:
                return index_to_k[i]
            i -= 1
        # fallback to first digit
        return 0
    else:
        # search right-of-caret
        i = cursor_pos
        while i < len(clean_text):
            if i in index_to_k:
                return index_to_k[i]
            i += 1
        # fallback to last digit
        return len(k_to_index) - 1

def _exponent_for_k(clean_text, k):
    """
    Given clean_text and the digit ordinal k (over digits only), compute the 10^exponent
    place value exponent (int can be >=0, float can be <0).
    """
    index_to_k, k_to_index, int_digits, _ = _digit_positions(clean_text)
    total_digits = len(k_to_index)
    if total_digits == 0 or k < 0 or k >= total_digits:
        return 0
    # k from 0..int_digits-1 are integer part, left to right
    if k < int_digits:
        # exponent for integer digit
        return int_digits - 1 - k
    else:
        # exponent for fractional digit
        frac_index = k - int_digits  # 0 => tenths => -1, 1 => hundredths => -2, ...
        return -(frac_index + 1)

class CursorIntSpinBox(QSpinBox):
    """
    Integer spinbox that steps the digit under the caret with Up/Down.
    Hold Shift to step the digit to the right of the caret.
    """
    def stepBy(self, steps: int) -> None:
        le = self.lineEdit()
        text = le.text()
        # remove prefix/suffix and group separators by using cleanText if needed
        clean = self.cleanText()
        # keep a plain integer string (with optional leading '-')
        # QSpinBox shouldn't include decimals, but sanitize anyway
        if '.' in clean:
            clean = clean.split('.', 1)[0]
        sign = '-' if clean.startswith('-') else ''
        digits = ''.join(ch for ch in clean if ch.isdigit())
        if not digits:
            digits = '0'

        # determine target digit via caret and Shift modifier
        left = not (QApplication.keyboardModifiers() & Qt.ShiftModifier)
        # map cursor in displayed text (not clean) to clean index by stripping prefix/suffix only
        # Easier approach: rebuild clean with sign and digits only, and approximate caret mapping.
        # We'll use the displayed cursor but operate on the clean string by best effort.
        cursor_pos = le.cursorPosition()
        # approximate: clamp within [len(sign), len(sign)+len(digits)]
        cmin = len(sign)
        cmax = len(sign) + len(digits)
        approx_cursor = max(cmin, min(cursor_pos, cmax))
        k = _nearest_digit_k(sign + digits, approx_cursor, left=left)
        if k is None:
            k = 0
        exp = _exponent_for_k(sign + digits, k)
        if exp < 0:
            # integer cannot step fractional places; default to ones place
            exp = 0

        factor = 10 ** exp
        new_val = self.value() + steps * factor
        # clamp to range
        new_val = max(self.minimum(), min(self.maximum(), new_val))

        # adjust cursor for sign flip
        had_minus = self.value() < 0
        self.setValue(new_val)
        has_minus = new_val < 0
        if has_minus != had_minus:
            delta = 1 if has_minus and not had_minus else -1
            le.setCursorPosition(max(0, le.cursorPosition() + delta))

class CursorDoubleSpinBox(QDoubleSpinBox):
    """
    Floating spinbox using Decimal arithmetic.
    Up/Down step the digit under the caret; Shift+Up/Down step the digit to its right.
    Respects min/max. Locale decimal point is supported.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDecimals(12)  # display precision; internal math uses Decimal

    def stepBy(self, steps: int) -> None:
        le = self.lineEdit()
        text = le.text()
        # normalize to '.' decimal for clean processing
        dec_char = self.locale().decimalPoint()
        clean = self.cleanText().replace(dec_char, '.')
        # keep sign + digits + optional single '.'
        # if multiple dots slipped in, keep first only
        if clean.count('.') > 1:
            parts = clean.split('.')
            clean = parts[0] + '.' + ''.join(parts[1:])

        sign = '-' if clean.startswith('-') else ''
        body = clean[1:] if sign else clean
        filtered = []
        dot_used = False
        for ch in body:
            if ch.isdigit():
                filtered.append(ch)
            elif ch == '.' and not dot_used:
                filtered.append('.')
                dot_used = True
        clean2 = sign + (''.join(filtered) if filtered else '0')

        # determine target digit using caret and Shift modifier
        left = not (QApplication.keyboardModifiers() & Qt.ShiftModifier)
        cursor_pos = le.cursorPosition()
        # Build a mirror string that matches clean2 layout for position mapping
        mirror = clean2
        k = _nearest_digit_k(mirror, cursor_pos, left=left)
        if k is None:
            k = 0
        exp = _exponent_for_k(mirror, k)
        factor = Decimal(10) ** Decimal(exp)

        try:
            current = Decimal(clean2)
        except Exception:
            current = Decimal(0)

        new_val = current + Decimal(steps) * factor
        # clamp to range
        min_d = Decimal(str(self.minimum()))
        max_d = Decimal(str(self.maximum()))
        if new_val < min_d:
            new_val = min_d
        if new_val > max_d:
            new_val = max_d

        # set and try to keep caret position stable on sign change
        had_minus = current < 0
        self.setValue(float(new_val))
        has_minus = new_val < 0
        if has_minus != had_minus:
            delta = 1 if has_minus and not had_minus else -1
            le.setCursorPosition(max(0, le.cursorPosition() + delta))

class CursorBinarySpinBox(QSpinBox):
    """
    16-bit binary spinbox. Displays a fixed-width binary string.
    Up/Down toggle the bit under the caret by +/-1 step in that bit position.
    Hold Shift to target the bit to the right of the caret.
    """
    def __init__(self, bits=16, parent=None):
        super().__init__(parent)
        self.bits = bits
        self.setRange(0, (1 << bits) - 1)
        # Ensure the editor can hold exactly <bits> characters
        self.lineEdit().setMaxLength(bits)
        # Disable built-in keyboard tracking to avoid intermediate invalid states
        self.setKeyboardTracking(False)

    def textFromValue(self, value: int) -> str:
        return format(int(value), '0{}b'.format(self.bits))

    def valueFromText(self, text: str) -> int:
        s = ''.join(ch for ch in text if ch in '01')[:self.bits]
        if not s:
            return 0
        try:
            return int(s, 2)
        except Exception:
            return 0

    def validate(self, text: str, pos: int):
        s = ''.join(ch for ch in text if ch in '01')
        if len(s) <= self.bits:
            return (QValidator.Acceptable, text, pos)
        return (QValidator.Invalid, text, pos)

    def stepBy(self, steps: int) -> None:
        le = self.lineEdit()
        text = self.text()  # already 0/1 string width == bits
        if not text:
            text = '0' * self.bits

        cursor_pos = le.cursorPosition()
        # find target digit index (0..bits-1) under or to the right/left
        shift = QApplication.keyboardModifiers() & Qt.ShiftModifier
        if shift:
            # bit to the right of caret
            target_idx = min(cursor_pos, self.bits - 1)
        else:
            # bit to the left of caret
            target_idx = max(0, min(cursor_pos - 1, self.bits - 1))

        # map digit index to bit position (MSB at index 0)
        bit_pos = (self.bits - 1) - target_idx

        if bit_pos < 0 or bit_pos >= self.bits:
            return

        delta = steps * (1 << bit_pos)
        new_val = self.value() + delta
        new_val = max(self.minimum(), min(self.maximum(), new_val))
        self.setValue(new_val)

