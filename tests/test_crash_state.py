from androidlink.utils import crash_state


def test_update_and_snapshot_round_trip():
    crash_state.update("casting", state="running", target_fps=165)
    snapshot = crash_state.snapshot()
    assert snapshot["casting"]["state"] == "running"
    assert snapshot["casting"]["target_fps"] == 165


def test_update_merges_rather_than_replaces():
    crash_state.update("casting", state="starting", target_fps=60)
    crash_state.update("casting", state="running")  # target_fps not repeated

    snapshot = crash_state.snapshot()
    assert snapshot["casting"]["state"] == "running"
    assert snapshot["casting"]["target_fps"] == 60  # still there from the earlier update


def test_components_are_independent():
    crash_state.update("casting", state="running")
    crash_state.update("mic", state="stopped")

    snapshot = crash_state.snapshot()
    assert snapshot["casting"]["state"] == "running"
    assert snapshot["mic"]["state"] == "stopped"


def test_snapshot_is_a_copy_not_a_live_view():
    crash_state.update("casting", state="running")
    snapshot = crash_state.snapshot()

    crash_state.update("casting", state="stopped")

    assert snapshot["casting"]["state"] == "running"  # the earlier snapshot is unaffected
    assert crash_state.snapshot()["casting"]["state"] == "stopped"
