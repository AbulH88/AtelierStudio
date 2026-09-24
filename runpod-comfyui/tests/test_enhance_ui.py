from pathlib import Path


HTML = (Path(__file__).parents[1] / "webapp" / "index.html").read_text(encoding="utf-8")


def test_enhance_accepts_images_and_videos():
    assert 'id="enhanceInput"' in HTML
    assert "image/png,image/jpeg,image/webp,image/avif,image/tiff" in HTML
    assert "video/mp4,video/quicktime,video/webm,video/x-matroska" in HTML
    assert 'id="enhanceBeforeImage"' in HTML
    assert 'id="enhanceAfterImage"' in HTML


def test_dlss5_primary_controls_and_defaults():
    assert "DLSS5 · Neural Rendering" in HTML
    assert 'id="enhanceNrPasses"' in HTML
    assert '<option value="2" selected>2 passes · recommended</option>' in HTML
    assert 'id="enhanceDlssScale"' in HTML
    assert '<option value="1" selected>Source · 100%</option>' in HTML
    assert '<option value="0.75">75% · faster</option>' in HTML
    assert 'id="enhanceNrStyle"' in HTML
    assert 'id="enhanceNrIntensity"' in HTML


def test_advanced_dlss5_is_collapsed_and_complete():
    assert '<details class="enhance-advanced" id="enhanceDlssAdvanced">' in HTML
    for control in (
        "enhanceTone", "enhanceStructure", "enhanceSkin", "enhanceAutomaticMask",
        "enhanceColor", "enhancePreserveTone", "enhanceFaceProtect",
        "enhanceGrain", "enhanceFeather",
    ):
        assert f'id="{control}"' in HTML


def test_ui_submits_media_and_native_multipass_options():
    assert "body.append('media',enhanceFile)" in HTML
    assert "nr_passes:+$('#enhanceNrPasses').value" in HTML
    assert "dlss_scale:+$('#enhanceDlssScale').value" in HTML
    assert "RIFE ${$('#enhanceMultiplier').value}×" in HTML
    assert "DLSS5 ×${$('#enhanceNrPasses').value}" in HTML
