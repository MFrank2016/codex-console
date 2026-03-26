from tests_runtime.realtime_log_harness import run_realtime_log_scenario


def test_snapshot_required_resync_contract():
    result = run_realtime_log_scenario("snapshot_required_resync")

    assert result["cursor_after_snapshot"] == 11
    assert result["visible_levels"] == ["INFO", "ERROR"]
    assert result["last_rendered_text"].startswith("10:00:02")
    assert result["theme_error_class"] == "realtime-log-level-error"
    assert result["live_window_size"] == 500
    assert result["history_chunk_merged"] is True
    assert result["history_overlap_deduped"] is True
    assert result["resync_pending_replayed_in_order"] is True


def test_search_and_level_filter_contract():
    result = run_realtime_log_scenario("search_and_level_filter")
    assert result["visible_messages"] == ["proxy fallback failed"]
    assert result["registration_shim_uses_shared_store"] is True


def test_wrap_and_auto_scroll_toggle_contract():
    result = run_realtime_log_scenario("wrap_and_auto_scroll_toggle")
    assert result["has_nowrap_class"] is True
    assert result["auto_scroll_preserved_manual_position"] is True


def test_copy_and_clear_view_contract():
    result = run_realtime_log_scenario("copy_and_clear_view")
    assert result["copied_text"].endswith("proxy fallback failed")
    assert result["clear_keeps_store_entries"] is True
    assert result["new_entries_visible_after_clear"] is True


def test_history_partial_overlap_preserves_extra_history_duplicates():
    result = run_realtime_log_scenario("history_partial_overlap")
    assert result["total_entries"] == 3


def test_connection_empty_error_states_contract():
    result = run_realtime_log_scenario("connection_empty_error_states")
    assert result["connection_text"] == "重连中"
    assert result["empty_state_visible"] is True
    assert result["error_state_visible"] is True
