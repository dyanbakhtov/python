import shortuuid


def generate_short_uuid(length: int = 8) -> str:
    return shortuuid.ShortUUID().random(length=length)
