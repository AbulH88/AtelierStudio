import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'home_agent'))
from rife_media import media_info, output_frames, mux_audio, audio_hash


def test_output_count_covers_full_audio_without_stretching_motion():
    info = {'width': 832, 'height': 1504, 'fps': 24., 'video_duration': 277/24,
            'audio_duration': 11.542, 'frames': 277}
    assert output_frames(info, 48, 553) == 555
    with pytest.raises(ValueError):output_frames({**info, 'audio_duration': 20}, 48, 553)


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg required')
def test_unaligned_native_audio_payload_survives_mux(tmp_path):
    source, picture, final = (tmp_path/n for n in ('source.mp4','picture.mp4','final.mp4'))
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=s=64x64:r=24:d=0.30',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=32000:duration=0.317',
        '-c:v','libx264','-c:a','aac',str(source)],check=True)
    info = media_info(source, 'ffmpeg')
    frames = output_frames(info, 48, 15)
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=s=64x64:r=48',
        '-frames:v',str(frames),'-c:v','libx264',str(picture)],check=True)
    mux_audio(picture, source, final, 'ffmpeg')
    result = media_info(final, 'ffmpeg')
    assert result['audio_duration'] == pytest.approx(info['audio_duration'], abs=1/32000)
    assert result['video_duration'] >= result['audio_duration']
    assert audio_hash(source, 'ffmpeg') == audio_hash(final, 'ffmpeg')
    subprocess.run(['ffmpeg','-v','error','-i',str(final),'-f','null','-'],check=True)


def test_container_duration_rounding_does_not_reject_identical_complete_audio(tmp_path,monkeypatch):
    import rife_media
    source,picture,final=(tmp_path/n for n in ('source.mp4','picture.mp4','final.mp4'))
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=s=64x64:r=24:d=0.3',
        '-f','lavfi','-i','sine=sample_rate=32000:duration=0.317','-c:v','libx264','-c:a','aac',str(source)],check=True)
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=s=64x64:r=48:d=0.4',
        '-c:v','libx264',str(picture)],check=True)
    inspect=rife_media.media_info
    def rounded(path,ffmpeg):
        info=inspect(path,ffmpeg)
        if Path(path)==source:info['audio_duration']+=10/32000
        return info
    monkeypatch.setattr(rife_media,'media_info',rounded)
    rife_media.mux_audio(picture,source,final,'ffmpeg')
    assert rife_media.audio_pcm_hash(source,'ffmpeg')==rife_media.audio_pcm_hash(final,'ffmpeg')
