from pathlib import Path


HTML = (Path(__file__).parents[1] / "webapp" / "index.html").read_text(encoding="utf-8")


def test_local_and_cloud_are_separate_top_level_destinations():
    assert 'data-page="studio">Local Studio<' in HTML
    assert 'data-page="cloud">Cloud Studio<' in HTML


def test_cloud_shell_contains_workflow_navigation_and_shared_queue():
    assert 'data-cloud-workflow="scail"' in HTML
    assert 'data-cloud-workflow="h3"' in HTML
    assert 'id="cloudJobList"' in HTML
    assert "Cloud Queue" in HTML


def test_h3_reference_modes_and_upload_limits_are_exposed():
    assert 'data-mode="i2v"' in HTML
    assert 'data-mode="omni"' in HTML
    assert 'data-mode="flf"' in HTML
    assert 'id="h3ImageCount">0</span>/9' in HTML
    assert 'id="h3VideoCount">0</span>/3' in HTML
    assert 'id="h3AudioCount">0</span>/3' in HTML
    assert "total>12" in HTML


def test_h3_submit_stays_guarded_until_optional_nodes_are_published():
    assert 'id="h3Run" class="cloud-run" disabled' in HTML
    assert "waiting for the optional RunningHub reference nodes" in HTML
