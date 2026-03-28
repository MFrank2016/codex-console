from tests_runtime.scheduled_tasks_js_harness import run_scheduled_tasks_js_scenario


def test_scheduled_tasks_delegated_plan_actions_still_work_without_inline_handlers():
    result = run_scheduled_tasks_js_scenario("delegated_plan_action_run_now")
    assert result["api_post_paths"] == ["/scheduled-plans/42/run"]


def test_scheduled_tasks_delegated_config_input_updates_entry_value():
    result = run_scheduled_tasks_js_scenario("delegated_config_value_change")
    assert result["updated_value"] == "12"
