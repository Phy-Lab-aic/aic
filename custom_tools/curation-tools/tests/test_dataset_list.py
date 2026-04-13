"""Tests for dataset listing endpoint — discovers datasets under the configured root."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.services.dataset_service import DatasetService
import backend.services.dataset_service as ds_mod
import backend.services.episode_service as ep_mod
import backend.services.task_service as ts_mod


@pytest.fixture(autouse=True)
def reset_singleton():
    from backend.routers import datasets as datasets_router

    orig_ds = ds_mod.dataset_service
    orig_ep = ep_mod.dataset_service
    orig_ts = ts_mod.dataset_service
    orig_router = datasets_router.dataset_service

    fresh = DatasetService()
    ds_mod.dataset_service = fresh
    ep_mod.dataset_service = fresh
    ts_mod.dataset_service = fresh
    datasets_router.dataset_service = fresh
    yield
    ds_mod.dataset_service = orig_ds
    ep_mod.dataset_service = orig_ep
    ts_mod.dataset_service = orig_ts
    datasets_router.dataset_service = orig_router


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestListDatasets:
    @pytest.mark.asyncio
    async def test_list_returns_available_datasets(self, client):
        resp = await client.get("/api/datasets/list")
        assert resp.status_code == 200
        datasets = resp.json()
        assert isinstance(datasets, list)
        assert len(datasets) >= 2  # basic_aic and hojun

    @pytest.mark.asyncio
    async def test_each_dataset_has_name_and_path(self, client):
        resp = await client.get("/api/datasets/list")
        datasets = resp.json()
        for ds in datasets:
            assert "name" in ds
            assert "path" in ds

    @pytest.mark.asyncio
    async def test_datasets_contain_basic_aic(self, client):
        resp = await client.get("/api/datasets/list")
        datasets = resp.json()
        names = [ds["name"] for ds in datasets]
        assert "basic_aic_cheetcode_dataset" in names

    @pytest.mark.asyncio
    async def test_datasets_contain_hojun(self, client):
        resp = await client.get("/api/datasets/list")
        datasets = resp.json()
        names = [ds["name"] for ds in datasets]
        assert "hojun" in names

    @pytest.mark.asyncio
    async def test_dataset_paths_are_absolute(self, client):
        resp = await client.get("/api/datasets/list")
        datasets = resp.json()
        for ds in datasets:
            assert ds["path"].startswith("/")

    @pytest.mark.asyncio
    async def test_select_dataset_loads_it(self, client):
        """Selecting a dataset from the list and loading it should work."""
        # First get the list
        list_resp = await client.get("/api/datasets/list")
        datasets = list_resp.json()
        first = datasets[0]

        # Load it
        load_resp = await client.post("/api/datasets/load", json={"path": first["path"]})
        assert load_resp.status_code == 200
        assert load_resp.json()["total_episodes"] > 0
