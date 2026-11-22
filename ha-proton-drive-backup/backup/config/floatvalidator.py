import math

from .validator import Validator
from ..logger import getLogger

logger = getLogger(__name__)


class FloatValidator(Validator):
    def __init__(self, name, minimum=None, maximum=None):
        super().__init__(name)
        self.min = minimum
        self.max = maximum

    def validate(self, value):
        if value is None or (type(value) == str and len(value) == 0):
            return None
        given = value
        # True would be read as 1, and a list or dict raised a TypeError that
        # became an unexpected error without the setting's name.
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            self.raiseForValue(given)
        try:
            value = float(value)
        except (ValueError, OverflowError):  # OverflowError: an int too large for a float
            self.raiseForValue(given)
        # NaN passes every comparison below (they're all False), and infinity
        # breaks any date calculated from it.
        if not math.isfinite(value):
            self.raiseForValue(given)

        if self.max is not None and value > self.max:
            self.raiseForValue(given)
        if self.min is not None and value < self.min:
            self.raiseForValue(given)
        return value
