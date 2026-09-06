from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "frontend" / "src" / "pages" / "DashboardPage.tsx"
SEARCH_DIALOG = ROOT / "frontend" / "src" / "components" / "workspace" / "MeetingSearchDialog.tsx"
SEARCH_API = ROOT / "frontend" / "src" / "api" / "meetingSearchApi.ts"


class FrontendArchiveSearchContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dashboard = DASHBOARD.read_text(encoding="utf-8")
        self.dialog = SEARCH_DIALOG.read_text(encoding="utf-8")
        self.api = SEARCH_API.read_text(encoding="utf-8")

    def test_today_view_no_longer_searches_compact_transcript_preview(self) -> None:
        self.assertNotIn("searchedMeetings", self.dashboard)
        self.assertNotIn("transcription?.text?.slice(0, 800)", self.dashboard)
        self.assertIn("meetings.filter((meeting) => isWithinTimeRange", self.dashboard)

    def test_command_k_opens_complete_search_dialog(self) -> None:
        self.assertIn("e.key.toLowerCase() === 'k'", self.dashboard)
        self.assertIn("setIsSearchOpen(true)", self.dashboard)
        self.assertIn("<MeetingSearchDialog", self.dashboard)
        self.assertIn("onOpenMeeting={(id) => navigateTo('meeting', id)}", self.dashboard)

    def test_search_is_server_side_bounded_and_paged(self) -> None:
        self.assertIn("const PAGE_SIZE = 25", self.dialog)
        self.assertIn("searchMeetingArchive(query, 1, PAGE_SIZE", self.dialog)
        self.assertIn("searchMeetingArchive(query, page + 1, PAGE_SIZE)", self.dialog)
        self.assertIn("response.has_more", self.dialog)
        self.assertIn("Math.min(limit, 50)", self.api)
        self.assertIn("q: query", self.api)
        self.assertIn("page: String(Math.max(1, page))", self.api)

    def test_stale_search_responses_do_not_replace_new_query_results(self) -> None:
        self.assertIn("generationRef", self.dialog)
        self.assertIn("generation !== generationRef.current", self.dialog)
        self.assertIn("controller.abort()", self.dialog)

    def test_search_exposes_loading_error_empty_and_more_states(self) -> None:
        self.assertIn("loading ?", self.dialog)
        self.assertIn("Search unavailable", self.dialog)
        self.assertIn("No meetings found", self.dialog)
        self.assertIn("Load more", self.dialog)
        self.assertIn('aria-live="polite"', self.dialog)

    def test_query_survives_navigation_without_loading_entire_archive(self) -> None:
        self.assertIn("sessionStorage.setItem(QUERY_STORAGE_KEY, query)", self.dialog)
        self.assertNotIn("ApiClient.listMeetings", self.dialog)
        self.assertNotIn("setMeetings", self.dialog)


if __name__ == "__main__":
    unittest.main()
