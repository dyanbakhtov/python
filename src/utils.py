from datetime import time, datetime

import shortuuid

from exceptions import NightOperationsForbiddenError


def generate_short_uuid(length: int = 8) -> str:
    return shortuuid.ShortUUID().random(length=length)


CURFEW_START = time(0, 0, 0)
CURFEW_END = time(5, 0, 0)


def check_night_curfew(current_time: time | None = None) -> None:
    if current_time is None:
        current_time = datetime.now().time()

    if CURFEW_START <= current_time < CURFEW_END:
        raise NightOperationsForbiddenError(
            f"Banking operations are prohibited at night (from {CURFEW_START} to {CURFEW_END}). "
            f"Current time: {current_time.strftime('%H:%M:%S')}"
        )
