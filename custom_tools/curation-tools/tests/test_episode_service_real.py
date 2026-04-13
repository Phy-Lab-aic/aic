"""Tests for EpisodeService against real LeRobot v3.0 datasets."""

import pytest
from backend.services.dataset_service import DatasetService
from backend.services.episode_service import EpisodeService, EpisodeNotFoundError


def _setup_services(dataset_path):
    """Wire up fresh services pointing at the given dataset."""
    import backend.services.dataset_service as ds_mod
    import backend.services.episode_service as ep_mod

    ds = DatasetService()
    ds.load_dataset(dataset_path)
    ds_mod.dataset_service = ds
    ep_mod.dataset_service = ds
    return ds, EpisodeService()


# ---------------------------------------------------------------------------
# get_episodes
# ---------------------------------------------------------------------------

class TestGetEpisodes:
    @pytest.mark.asyncio
    async def test_returns_all_basic_aic_episodes(self, basic_aic_path):
        _, es = _setup_services(basic_aic_path)
        episodes = await es.get_episodes()
        assert len(episodes) == 40

    @pytest.mark.asyncio
    async def test_returns_all_hojun_episodes(self, hojun_path):
        _, es = _setup_services(hojun_path)
        episodes = await es.get_episodes()
        assert len(episodes) == 6

    @pytest.mark.asyncio
    async def test_episode_has_schema_fields(self, basic_aic_path):
        _, es = _setup_services(basic_aic_path)
        episodes = await es.get_episodes()
        ep = episodes[0]

        assert "episode_index" in ep
        assert "length" in ep
        assert "task_index" in ep
        assert "task_instruction" in ep
        assert "grade" in ep
        assert "tags" in ep

    @pytest.mark.asyncio
    async def test_episode_length_is_positive(self, basic_aic_path):
        _, es = _setup_services(basic_aic_path)
        episodes = await es.get_episodes()
        for ep in episodes:
            assert ep["length"] > 0, f"Episode {ep['episode_index']} has non-positive length {ep['length']}"

    @pytest.mark.asyncio
    async def test_task_instruction_resolved(self, basic_aic_path):
        """Episodes should have task_instruction denormalized from tasks.parquet."""
        _, es = _setup_services(basic_aic_path)
        episodes = await es.get_episodes()
        instructions = {ep["task_instruction"] for ep in episodes}
        # At least some episodes should have a non-empty instruction
        assert any(inst != "" for inst in instructions), "All task instructions are empty"

    @pytest.mark.asyncio
    async def test_caching_returns_same_result(self, basic_aic_path):
        ds, es = _setup_services(basic_aic_path)
        first = await es.get_episodes()
        second = await es.get_episodes()
        assert len(first) == len(second)
        # Second call should use cache
        assert ds.episodes_cache is not None


# ---------------------------------------------------------------------------
# get_episode
# ---------------------------------------------------------------------------

class TestGetEpisode:
    @pytest.mark.asyncio
    async def test_returns_single_episode(self, basic_aic_path):
        _, es = _setup_services(basic_aic_path)
        ep = await es.get_episode(0)
        assert ep["episode_index"] == 0

    @pytest.mark.asyncio
    async def test_raises_for_nonexistent_episode(self, basic_aic_path):
        _, es = _setup_services(basic_aic_path)
        with pytest.raises(EpisodeNotFoundError):
            await es.get_episode(9999)

    @pytest.mark.asyncio
    async def test_returns_correct_episode_from_second_file(self, basic_aic_path):
        """Episode 20+ should come from a later parquet file."""
        ds, es = _setup_services(basic_aic_path)
        # Populate cache first
        await es.get_episodes()
        ep = await es.get_episode(20)
        assert ep["episode_index"] == 20


# ---------------------------------------------------------------------------
# update_episode
# ---------------------------------------------------------------------------

class TestUpdateEpisode:
    @pytest.mark.asyncio
    async def test_update_grade_and_tags(self, writable_basic_aic):
        _, es = _setup_services(writable_basic_aic)
        updated = await es.update_episode(episode_index=0, grade="Good", tags=["good", "clean"])

        assert updated["grade"] == "Good"
        assert updated["tags"] == ["good", "clean"]

    @pytest.mark.asyncio
    async def test_update_persists_to_sidecar(self, writable_basic_aic):
        ds, es = _setup_services(writable_basic_aic)
        await es.update_episode(episode_index=0, grade="Good", tags=["review"])

        # Re-read directly from sidecar JSON
        from backend.services.episode_service import _load_sidecar
        sidecar = _load_sidecar(ds.dataset_path)
        ann = sidecar.get("0")
        assert ann is not None, "Episode 0 annotation not found in sidecar"
        assert ann["grade"] == "Good"
        assert ann["tags"] == ["review"]

    @pytest.mark.asyncio
    async def test_update_clears_grade_with_none(self, writable_basic_aic):
        _, es = _setup_services(writable_basic_aic)
        await es.update_episode(episode_index=0, grade="Good", tags=[])
        updated = await es.update_episode(episode_index=0, grade=None, tags=[])
        assert updated["grade"] is None

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises(self, writable_basic_aic):
        _, es = _setup_services(writable_basic_aic)
        with pytest.raises(EpisodeNotFoundError):
            await es.update_episode(episode_index=9999, grade="Good", tags=[])

    @pytest.mark.asyncio
    async def test_update_syncs_cache(self, writable_basic_aic):
        ds, es = _setup_services(writable_basic_aic)
        # Populate cache
        await es.get_episodes()
        assert ds.episodes_cache is not None

        await es.update_episode(episode_index=0, grade="Bad", tags=["cached"])
        cached_ep = ds.episodes_cache[0]
        assert cached_ep["grade"] == "Bad"
        assert cached_ep["tags"] == ["cached"]

    @pytest.mark.asyncio
    async def test_update_episode_in_second_file(self, writable_basic_aic):
        """Update an episode stored in a different parquet chunk file."""
        ds, es = _setup_services(writable_basic_aic)
        # Find an episode in the second file
        ep_in_second = None
        for ep_idx, fp in ds._episode_to_file_map.items():
            if fp != ds._episode_parquet_files[0]:
                ep_in_second = ep_idx
                break
        assert ep_in_second is not None, "No episode in second file"

        updated = await es.update_episode(episode_index=ep_in_second, grade="Normal", tags=["other-file"])
        assert updated["grade"] == "Normal"
