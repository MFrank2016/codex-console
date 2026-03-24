from datetime import UTC, datetime


def utc_now() -> datetime:
    """返回 timezone-aware 的 UTC 当前时间。"""
    return datetime.now(UTC)


def utc_now_naive() -> datetime:
    """返回 naive UTC 时间，用于当前仍使用 naive DateTime 列的 ORM 写入。"""
    return utc_now().replace(tzinfo=None)
