from datetime import time, datetime

import shortuuid

from exceptions import NightOperationsForbiddenError


def generate_short_uuid(length: int = 8) -> str:
    return shortuuid.ShortUUID().random(length=length)


def check_night_curfew(current_time: time | None = None) -> None:
    if current_time is None:
        current_time = datetime.now().time()

    start_night = time(0, 0, 0)
    end_night = time(5, 0, 0)

    if start_night <= current_time < end_night:
        raise NightOperationsForbiddenError(
            f"Banking operations are prohibited at night (from 00:00 to 05:00). Current time: {current_time.strftime('%H:%M:%S')}"
        )
