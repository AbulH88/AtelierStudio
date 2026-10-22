"""Full-timeline audio preservation for the fixed Media OS RIFE recipe."""
import json
import math
from pathlib import Path
import shutil
import subprocess


def media_info(path, ffmpeg):
    sibling = Path(ffmpeg).with_name('ffprobe.exe' if str(ffmpeg).lower().endswith('.exe') else 'ffprobe')
    probe = str(sibling) if sibling.is_file() else shutil.which('ffprobe')
    if not probe:
        raise ValueError('FFprobe unavailable')
    result = subprocess.run([probe, '-v', 'error', '-show_streams', '-of', 'json', str(path)],
        capture_output=True, timeout=30, check=True)
    streams = json.loads(result.stdout)['streams']
    video = next(s for s in streams if s.get('codec_type') == 'video')
    audio = [s for s in streams if s.get('codec_type') == 'audio']
    numerator, denominator = video['avg_frame_rate'].split('/')
    info = {'width': int(video['width']), 'height': int(video['height']),
        'fps': float(numerator)/float(denominator), 'video_duration': float(video['duration']),
        'frames': int(video['nb_frames']), 'audio_duration': max((float(s['duration']) for s in audio), default=0),
        'audio_streams': len(audio), 'audio_codec': audio[0]['codec_name'] if audio else None}
    if not all(math.isfinite(info[k]) for k in ('fps', 'video_duration', 'audio_duration')):
        raise ValueError('Invalid media timeline')
    return info


def output_frames(info, fps, minimum):
    if info['audio_duration'] > info['video_duration'] + .1:
        raise ValueError('Audio extends beyond the supported terminal padding')
    return max(minimum, math.ceil(max(info['video_duration'], info['audio_duration'])*fps - 1e-7))


def audio_hash(path, ffmpeg):
    return subprocess.check_output([ffmpeg, '-v', 'error', '-i', str(path), '-map', '0:a:0',
        '-c:a', 'copy', '-f', 'hash', '-hash', 'sha256', '-'], timeout=45).decode().strip()


def mux_audio(picture, source, target, ffmpeg):
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', str(picture), '-i', str(source),
        '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'copy',
        '-movflags', '+faststart', str(target)], capture_output=True, timeout=90, check=True)
    before, after = media_info(source, ffmpeg), media_info(target, ffmpeg)
    if (after['video_duration'] + 1e-6 < after['audio_duration'] or
        abs(before['audio_duration'] - after['audio_duration']) > 1/32000 or
        audio_hash(source, ffmpeg) != audio_hash(target, ffmpeg)):
        raise ValueError('Complete source audio was not preserved')
