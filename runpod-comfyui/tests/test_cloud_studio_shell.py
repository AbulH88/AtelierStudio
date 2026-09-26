from pathlib import Path


HTML = (Path(__file__).parents[1] / "webapp" / "index.html").read_text(encoding="utf-8")


def test_local_and_cloud_are_separate_top_level_destinations():
    assert 'data-page="studio">Local Studio<' in HTML
    assert 'data-page="cloud">Cloud Studio<' in HTML
    assert HTML.index('data-page="cloud">Cloud Studio<') < HTML.index('data-page="gallery">Gallery<')


def test_cloud_shell_contains_workflow_navigation_and_shared_queue():
    assert 'data-cloud-workflow="scail"' in HTML
    assert 'data-cloud-workflow="h3"' in HTML
    assert 'id="cloudJobList"' in HTML
    assert "Cloud Queue" in HTML


def test_cloud_jobs_opens_a_full_history_workspace_with_real_usage_columns():
    assert 'id="cloudJobsNav" data-cloud-workflow="jobs"' in HTML
    assert 'id="cloudJobsPanel"' in HTML
    assert 'id="cloudQueueViewAll"' in HTML
    assert '>My Jobs<' in HTML
    assert '>All Jobs<' in HTML
    assert '>RunningHub Task ID<' in HTML
    assert '>RH Coins<' in HTML
    assert "view:'history'" in HTML


def test_recent_cloud_jobs_label_runtime_and_coin_usage():
    assert "cloudFormatRuntime(job.runtime)" in HTML
    assert "cloudCoinText(job.rh_coins)" in HTML
    assert "queue-row-meta" in HTML
    assert "queue-row-tail" not in HTML


def test_h3_reference_modes_and_upload_limits_are_exposed():
    assert 'data-mode="i2v"' in HTML
    assert 'data-mode="omni"' in HTML
    assert 'data-mode="flf"' in HTML
    assert 'id="h3ImageCount">0</span>' in HTML
    assert 'id="h3VideoCount">0</span>' in HTML
    assert 'id="h3AudioCount">0</span>' in HTML
    assert "h3Mode==='flf'?2:3" in HTML
    assert "return 3" in HTML
    assert "total>7" in HTML
    assert 'id="h3ReferenceSections"' in HTML
    assert "Up to 3 images, 1 video, and 3 audio references." in HTML


def test_cloud_credentials_are_admin_managed_and_video_uses_modal():
    assert 'id="cloudApiKey"' not in HTML
    assert 'id="cloudSaveKey"' not in HTML
    assert 'id="cloudVideoModal"' in HTML
    assert "Credentials are securely managed by your administrator." in HTML


def test_h3_only_exposes_workflow_backed_settings_and_optional_audio():
    assert 'id="h3Aspect"' in HTML
    assert 'id="h3Duration"' in HTML
    assert 'id="h3Quality"' not in HTML
    assert 'id="h3Instance"' not in HTML
    assert "['image','audio']" in HTML


def test_h3_add_cards_support_drag_and_drop_from_computer():
    assert "ondragover" in HTML
    assert "ondrop" in HTML
    assert "drag-over" in HTML
    assert "Drop a supported ${type} file" in HTML


def test_cloud_studio_stacks_before_workspace_is_squeezed():
    assert "@media(max-width:1800px)" in HTML
    assert "@media(max-width:1100px)" in HTML
    assert "grid-column:1/-1" in HTML


def test_h3_submit_uses_the_supported_runninghub_route():
    assert 'id="h3Run" class="cloud-run" disabled' in HTML
    assert "/api/runninghub/h3/jobs" in HTML
    assert "Ready to submit MiniMax H3" in HTML


def test_talking_workflow_has_separate_navigation_permission_and_history_filter():
    assert 'data-cloud-workflow="h3_talking"' in HTML
    assert '<input type="checkbox" value="h3_talking">' in HTML
    assert '<option value="h3_talking">H3 Optimized for Talking</option>' in HTML
    assert "key==='h3_talking'?'H3 Optimized for Talking'" in HTML


def test_talking_workflow_exposes_portrait_source_and_complete_prompt_inputs():
    assert 'id="h3TalkingImage" type="file" accept="image/png,image/jpeg,image/webp"' in HTML
    assert 'id="h3TalkingPreview"' in HTML
    assert 'class="h3-talking-preview hide"' in HTML
    assert 'id="h3TalkingDescription"' in HTML
    assert 'id="h3TalkingScript"' in HTML
    assert 'id="h3TalkingAudio"' in HTML
    assert 'id="h3TalkingMusic"' in HTML
    assert 'id="h3TalkingPrompt"' in HTML
    assert 'object-fit:cover' in HTML
    assert 'aspect-ratio:9/16' in HTML


def test_talking_workflow_has_only_approved_models_and_integer_duration_contract():
    select = ('<select id="h3TalkingModel"><option value="openai/gpt-6-luna" selected>GPT-6 Luna</option>'
              '<option value="qwen/qwen3.8-27b">Qwen 3.8 27B</option></select>')
    assert select in HTML
    assert 'id="h3TalkingDuration" type="number" min="5" max="15" step="1" value="10"' in HTML


def test_talking_prompt_generation_and_video_submission_use_separate_routes():
    assert 'id="h3TalkingGeneratePrompt"' in HTML
    assert 'id="h3TalkingRun" class="cloud-run" disabled' in HTML
    assert "fetch('/api/runninghub/h3-talking/prompt',{method:'POST',body})" in HTML
    assert "fetch('/api/runninghub/h3-talking/jobs',{method:'POST',body})" in HTML
    assert "body.append('prompt',$('#h3TalkingPrompt').value)" in HTML
    generation = HTML.index("fetch('/api/runninghub/h3-talking/prompt'")
    assignment = HTML.index("$('#h3TalkingPrompt').value=d.prompt", generation)
    failure = HTML.index("if(!r.ok)throw", generation)
    assert generation < failure < assignment
