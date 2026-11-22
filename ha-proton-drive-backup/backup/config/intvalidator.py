from .validator import Validator
from ..logger import getLogger

logger = getLogger(__name__)


class IntValidator(Validator):
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
            value = int(value)
        except (ValueError, OverflowError):  # int(float("nan")) and int(float("inf"))
            self.raiseForValue(given)

        if self.max is not None and value > self.max:
            self.raiseForValue(given)
        if self.min is not None and value < self.min:
            self.raiseForValue(given)
        return value
