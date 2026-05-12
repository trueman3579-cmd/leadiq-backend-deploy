import pytest

from backend.shared.deduper import PostDeduplicator


class FakeRedis:
    def __init__(self):
        self._set = set()

    async def sadd(self, key, value):
        if value in self._set:
            return 0
        self._set.add(value)
        return 1

    async def expire(self, key, ttl):
        return True

    async def delete(self, key):
        self._set.clear()


@pytest.mark.asyncio
async def test_is_duplicate_flow():
    fake = FakeRedis()
    deduper = PostDeduplicator(fake)  # type: ignore[arg-type]

    first = await deduper.is_duplicate("Need CRM recommendation for SMB")
    second = await deduper.is_duplicate("Need CRM recommendation for SMB")

    assert first is False
    assert second is True
