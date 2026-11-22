import math
import re
from datetime import timedelta
from .durationparser import DurationParser, MAX_NUMBER_LENGTH, NUMBER, formatNumber
from .validator import Validator


class DurationAsStringValidator(Validator):
    def __init__(self, name, minimum=None, maximum=None, base_seconds=1, default_as_empty=None):
        super().__init__(name)
        self.min = minimum
        self.max = maximum
        self.base_seconds = base_seconds
        self.default_as_empty = default_as_empty

    def validate(self, value):
        if value is None or (type(value) == str and len(value) == 0):
            return None
        # Errors name the value as the user gave it ("60"), not converted
        # (60.0 seconds, or a fraction of a day).
        given = value
        try:
            value = self._toNumber(value)
        except (ValueError, OverflowError, TypeError):  # OverflowError: e.g. "1e99 days" as digits
            self.raiseForValue(given)
        # NaN passes every comparison below (they're all False).
        if not math.isfinite(value):
            self.raiseForValue(given)
        if self.max is not None and value > self.max:
            self.raiseForValue(given)
        if self.min is not None and value < self.min:
            self.raiseForValue(given)
        return value

    def _toNumber(self, value) -> float:
        """value in the setting's own unit, from a number or a duration's text."""
        # True would be read as 1, and a list or dict raised a TypeError that
        # became an unexpected error without the setting's name.
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise TypeError()
        if isinstance(value, str):
            if len(value) <= MAX_NUMBER_LENGTH and re.fullmatch(r"\s*%s\s*" % NUMBER, value):
                # A bare number is in the setting's own unit, as it is
                # from the Configuration tab: "30" days, not 30 seconds.
                # Anything else needs a unit on every number (DurationParser).
                return float(value)
            return DurationParser().parse(value).total_seconds() / self.base_seconds
        return float(value)

    def formatForUi(self, value):
        if self.default_as_empty is not None and value == self.default_as_empty:
            return ""
        # A duration ("3 hours") when that reads back as exactly this value,
        # otherwise the number in the setting's own unit: "0.999" days rather
        # than "23 hours, 58 minutes, 33 seconds" (0.99899 days), and a value
        # too large for a duration (from the Configuration tab, which takes any
        # number) in full rather than "1e+308".  Either way, saving the
        # settings form unchanged keeps the value.
        try:
            text = DurationParser().format(timedelta(seconds=value * self.base_seconds))
            if self._toNumber(text) == value:
                return text
        except (OverflowError, ValueError, TypeError):
            pass
        return formatNumber(value)
