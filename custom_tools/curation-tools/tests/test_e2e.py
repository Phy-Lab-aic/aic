"""E2E tests for the curation tools UI using Playwright against a real running app.

Requires backend on :8000 and frontend on :5173.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session")
def browser_type_launch_args():
    return {"executable_path": "/snap/bin/chromium", "headless": True}


BASE_URL = "http://localhost:5173"


def _select_dataset(page: Page, name: str):
    """Click a dataset by its exact name text."""
    page.get_by_text(name, exact=True).click()


# ---------------------------------------------------------------------------
# Page load
# ---------------------------------------------------------------------------

class TestPageLoad:
    def test_app_loads(self, page: Page):
        page.goto(BASE_URL)
        expect(page.get_by_text("Datasets", exact=True)).to_be_visible()

    def test_shows_dataset_list(self, page: Page):
        page.goto(BASE_URL)
        expect(page.get_by_text("basic_aic_cheetcode_dataset", exact=True)).to_be_visible()
        expect(page.get_by_text("hojun", exact=True)).to_be_visible()

    def test_no_episodes_shown_initially(self, page: Page):
        page.goto(BASE_URL)
        # Before selecting a dataset, no episode list should be visible
        expect(page.get_by_text("#0", exact=True)).not_to_be_visible()


# ---------------------------------------------------------------------------
# Dataset selection
# ---------------------------------------------------------------------------

class TestDatasetSelection:
    def test_click_dataset_loads_it(self, page: Page):
        page.goto(BASE_URL)
        _select_dataset(page, "basic_aic_cheetcode_dataset")
        # Should show dataset info after loading
        expect(page.get_by_text("FPS")).to_be_visible(timeout=5000)
        expect(page.get_by_text("20", exact=True)).to_be_visible()

    def test_episode_list_populated_after_load(self, page: Page):
        page.goto(BASE_URL)
        _select_dataset(page, "basic_aic_cheetcode_dataset")
        # Wait for episodes to appear
        expect(page.get_by_text("#0", exact=True)).to_be_visible(timeout=5000)

    def test_switch_datasets(self, page: Page):
        page.goto(BASE_URL)
        _select_dataset(page, "basic_aic_cheetcode_dataset")
        expect(page.get_by_text("#0", exact=True)).to_be_visible(timeout=5000)

        # Switch to hojun
        _select_dataset(page, "hojun")
        page.wait_for_timeout(1000)
        expect(page.get_by_text("#0", exact=True)).to_be_visible()


# ---------------------------------------------------------------------------
# Episode interaction
# ---------------------------------------------------------------------------

class TestEpisodeInteraction:
    def test_click_episode_shows_editor(self, page: Page):
        page.goto(BASE_URL)
        _select_dataset(page, "basic_aic_cheetcode_dataset")
        expect(page.get_by_text("#0", exact=True)).to_be_visible(timeout=5000)
        page.get_by_text("#0", exact=True).click()
        # Right panel should show episode editor
        expect(page.get_by_text("Grade", exact=True)).to_be_visible(timeout=3000)

    def test_episode_shows_frame_count(self, page: Page):
        page.goto(BASE_URL)
        _select_dataset(page, "basic_aic_cheetcode_dataset")
        expect(page.get_by_text("#0", exact=True)).to_be_visible(timeout=5000)
        # Episodes should display frame counts
        expect(page.get_by_text("frames").first).to_be_visible()
