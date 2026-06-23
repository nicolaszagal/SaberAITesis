from fog.domain.models import Match, WeaponSide
from fog.infrastructure.persistence.in_memory_match_repository import InMemoryMatchRepository


async def test_save_and_get_roundtrip():
    repo = InMemoryMatchRepository()
    match = Match(match_id="m1", weapon_side_a=WeaponSide.RIGHT, weapon_side_b=WeaponSide.LEFT)

    await repo.save(match)
    fetched = await repo.get("m1")

    assert fetched is match


async def test_get_missing_returns_none():
    repo = InMemoryMatchRepository()
    assert await repo.get("does-not-exist") is None


async def test_save_overwrites_existing_match():
    repo = InMemoryMatchRepository()
    await repo.save(Match(match_id="m1", weapon_side_a=WeaponSide.RIGHT, weapon_side_b=WeaponSide.RIGHT))
    await repo.save(Match(match_id="m1", weapon_side_a=WeaponSide.LEFT, weapon_side_b=WeaponSide.LEFT))

    fetched = await repo.get("m1")
    assert fetched.weapon_side_a is WeaponSide.LEFT
