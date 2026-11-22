import re
from datetime import timedelta
from decimal import Decimal
from injector import inject, singleton

SECOND_IDENTIFIERS = ["s", "sec", "secs", "second", "seconds"]
MINUTE_IDENTIFIERS = ["m", "min", "mins", "minute", "minutes"]
HOUR_IDENTIFIERS = ["h", "hr", "hour", "hours"]
DAY_IDENTIFIERS = ["d", "day", "days"]
UNIT_SECONDS = {
    **{unit: 1 for unit in SECOND_IDENTIFIERS},
    **{unit: 60 for unit in MINUTE_IDENTIFIERS},
    **{unit: 60 * 60 for unit in HOUR_IDENTIFIERS},
    **{unit: 24 * 60 * 60 for unit in DAY_IDENTIFIERS},
}
# Longest first, so "mins" is matched whole rather than as "m" + "ins".
_UNIT = "|".join(sorted(map(re.escape, UNIT_SECONDS), key=len, reverse=True))
# A number, "30", "1.5" or ".5", written so a run of digits can be matched in
# only one way: "[0-9]*\.?[0-9]+" could split "1111" many ways, and a long
# non-matching input then took time growing with the square of its length.
NUMBER = r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
# One "<number> <unit>" part: "3h", "3 h", "90 minutes", "1.5 days".
PART_REGEX = re.compile(r"(%s) *(%s)" % (NUMBER, _UNIT))
_PART = r"%s *(?:%s)" % (NUMBER, _UNIT)
# A whole duration: one or more parts, separated by spaces and/or commas, e.g.
# "1 day, 2 hours" (what format() writes).  Every number needs one of the
# units above; anything else ("30,", "7 30", "1:30:00") is rejected rather than
# guessed at, since a number without a unit used to be read as seconds.
DURATION_REGEX = re.compile(r" *%s(?:[ ,]+%s)*[ ,]*" % (_PART, _PART))
# Longer than any real duration ("1 day, 23 hours, 59 minutes, 59 seconds" is
# 37); refused before any regex runs.
MAX_LENGTH = 100
# A lone number can be longer: formatNumber writes the largest float in full
# (309 digits) and the smallest as "0.000…5" (326 characters).  Its regex
# (NUMBER) runs in linear time.
MAX_NUMBER_LENGTH = 400


def formatNumber(value) -> str:
    """
    value written out in full, e.g. "9999999", "0.000001" or "1.5": never
    "1e+07" (which a duration field rejects) or rounded like "{:g}"
    ("1.23457e+06").  float(formatNumber(v)) == v for every finite v.
    """
    value = float(value)
    if value == 0:
        return "0"  # not "-0"
    text = format(Decimal(repr(value)), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


@singleton
class DurationParser():
    @inject
    def __init__(self):
        pass

    def parse(self, source: str) -> timedelta:
        source = source.lower()
        if len(source) > MAX_LENGTH or not DURATION_REGEX.fullmatch(source):
            raise ValueError()
        return timedelta(seconds=sum(float(number) * UNIT_SECONDS[unit]
                                     for number, unit in PART_REGEX.findall(source)))

    def format(self, duration: timedelta):
        parts = []
        if duration >= timedelta(days=1):
            days = int(duration.days)
            parts.append("{} days".format(days))
            duration = duration - timedelta(days=days)
        if duration >= timedelta(hours=1):
            hours = int(duration.seconds / (60 * 60))
            parts.append("{} hours".format(hours))
            duration = duration - timedelta(hours=hours)
        if duration >= timedelta(minutes=1):
            minutes = int(duration.seconds / 60)
            parts.append("{} minutes".format(minutes))
            duration = duration - timedelta(minutes=minutes)
        if duration >= timedelta(seconds=1):
            seconds = int(duration.seconds)
            parts.append("{} seconds".format(seconds))
            duration = duration - timedelta(seconds=seconds)
        if len(parts) > 0:
            return ", ".join(parts)
        else:
            return "0 seconds"
