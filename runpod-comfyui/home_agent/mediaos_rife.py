"""Persistent, fixed-recipe RIFE API on the existing authenticated Home Agent."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from uuid import uuid4

from flask import jsonify, request, send_file
from rife_media import media_info, output_frames, audio_hash

RECIPE = {'version': 1, 'engine': 'rife', 'model': 'rife49.pth', 'multiplier': 2,
          'native_dimensions': True, 'rtx': False, 'complete_audio': True}
MODEL_SHA = 'e55fd00f3cc184e3c65961f4bb827a9da022e78eed36b055242c0ac30000d533'
MAX_BYTES = 100*1024*1024


def checksum(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def model_hash(root):
    return checksum(Path(root)/'custom_nodes/ComfyUI-Frame-Interpolation/ckpts/rife/rife49.pth')


def queue_state():
    url = os.environ.get('COMFY_URL', 'http://127.0.0.1:8189').rstrip('/')
    try:
        with urllib.request.urlopen(url+'/queue', timeout=3) as response:
            return json.load(response)
    except urllib.error.URLError as exc:
        # Standalone RIFE does not require ComfyUI. Only definite refusal is idle.
        if isinstance(exc.reason, ConnectionRefusedError):
            return {'queue_running': [], 'queue_pending': []}
        raise


def gpu_state():
    result = subprocess.run(['nvidia-smi', '--query-gpu=memory.free,utilization.gpu',
        '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=5, check=True)
    rows = result.stdout.strip().splitlines()
    if len(rows) != 1:
        raise ValueError('Single GPU required')
    return tuple(float(value.strip()) for value in rows[0].split(','))


def local_availability():
    try:
        queue = queue_state()
        if not isinstance(queue.get('queue_running'), list) or not isinstance(queue.get('queue_pending'), list):
            raise ValueError('Queue unknown')
        if queue['queue_running'] or queue['queue_pending']:
            return {'free': False, 'reason': 'comfy_busy'}
        free_mb, utilization = gpu_state()
        if not math.isfinite(free_mb) or not math.isfinite(utilization):
            raise ValueError('GPU state unknown')
        if free_mb < 8192 or not 0 <= utilization <= 10:
            return {'free': False, 'reason': 'gpu_busy'}
        return {'free': True, 'reason': 'idle'}
    except Exception:
        return {'free': False, 'reason': 'gpu_state_unknown'}


class RifeService:
    def __init__(self, root, enhance, availability=None, launch=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root/'jobs.sqlite3'
        self.enhance = enhance
        self.availability_probe = availability or local_availability
        self.launch = launch or self._launch
        self.spawn = subprocess.Popen
        self.recovery_required = False
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            for key, payload in db.execute('SELECT key,payload FROM jobs').fetchall():
                job = json.loads(payload)
                if job['status'] in ('accepted', 'running'):
                    job.update(status='interrupted', error='agent_restarted', finished_at=time.time())
                    db.execute('UPDATE jobs SET payload=? WHERE key=?', (json.dumps(job), key))
                if job['status'] == 'interrupted':
                    self.recovery_required = True

    def connect(self):
        return sqlite3.connect(self.database, timeout=15)

    def get(self, key):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM jobs WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, job):
        with self.connect() as db:
            db.execute('INSERT INTO jobs(key,payload) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload',
                (job['key'], json.dumps(job, sort_keys=True)))

    def availability(self):
        if self.recovery_required:
            return {'free': False, 'reason': 'interrupted_work_requires_reconciliation'}
        if self.enhance.ACTIVE['job']:
            return {'free': False, 'reason': 'enhance_busy'}
        try:
            if 'rife49.pth' not in self.enhance._models() or model_hash(self.enhance._comfy_root()) != MODEL_SHA:
                return {'free': False, 'reason': 'rife_runtime_unavailable'}
        except Exception:
            return {'free': False, 'reason': 'rife_runtime_unavailable'}
        return self.availability_probe()

    def submit(self, key, manifest, upload):
        if not re.fullmatch('[0-9a-f]{64}', key):
            return {'error': 'invalid_key'}, 400
        if not isinstance(manifest, dict) or manifest.get('recipe') != RECIPE or not re.fullmatch('[0-9a-f]{64}', str(manifest.get('source_sha256', ''))):
            return {'error': 'invalid_manifest'}, 400
        existing = self.get(key)
        if existing:
            if existing['source_sha256'] != manifest['source_sha256'] or existing['recipe'] != RECIPE:
                return {'error': 'request_conflict'}, 409
            return existing, 202
        temporary = self.root/(uuid4().hex+'.upload')
        try:
            h, size = hashlib.sha256(), 0
            with temporary.open('xb') as target:
                while block := upload.stream.read(1024*1024):
                    size += len(block)
                    if size > MAX_BYTES:
                        return {'error': 'upload_too_large'}, 413
                    h.update(block)
                    target.write(block)
            if not size or h.hexdigest() != manifest['source_sha256']:
                return {'error': 'source_hash_mismatch'}, 400
            with self.enhance.LOCK:
                existing = self.get(key)
                if existing:
                    return (existing, 202) if existing['source_sha256'] == manifest['source_sha256'] else ({'error': 'request_conflict'}, 409)
                state = self.availability()
                if not state.get('free'):
                    return {'error': 'busy', 'reason': state.get('reason', 'gpu_state_unknown')}, 409
                folder = self.root/key
                folder.mkdir(exist_ok=True)
                temporary.replace(folder/'source.mp4')
                job = {'key': key, 'source_sha256': manifest['source_sha256'], 'recipe': RECIPE,
                    'status': 'accepted', 'created_at': time.time(), 'receipt': None, 'error': None}
                self.save(job)
                self.enhance.ACTIVE['job'] = 'mediaos:'+key
                self.launch(key)
                return job, 202
        finally:
            temporary.unlink(missing_ok=True)

    def _launch(self, key):
        threading.Thread(target=self.work, args=(key,), daemon=True).start()

    def work(self, key):
        folder = self.root/key
        job = self.get(key)
        spawned = clean_exit = False
        try:
            from rife_video import _ffmpeg
            comfy = self.enhance._comfy_root()
            ffmpeg = _ffmpeg(comfy)
            source, output = folder/'source.mp4', folder/'result.mp4'
            before = media_info(source, ffmpeg)
            if (before['fps'] != 24 or not 2 <= before['frames'] <= 720 or
                before['width']*before['height'] > 2_200_000 or before['audio_streams'] != 1 or
                before['audio_codec'] != 'aac' or not 0 < before['video_duration'] <= 30):
                raise ValueError('unsupported_source')
            expected_frames = output_frames(before, 48, before['frames']*2-1)
            if checksum(source) != job['source_sha256'] or model_hash(comfy) != MODEL_SHA:
                raise ValueError('runtime_or_source_changed')
            if not self.availability_probe().get('free'):
                raise ValueError('gpu_became_busy')
            python = Path(os.environ.get('ATELIER_COMFY_PYTHON', str(comfy/'venv/Scripts/python.exe')))
            if not python.is_file():
                raise ValueError('runtime_unavailable')
            command = [str(python), str(Path(__file__).with_name('rife_video.py')), '--comfy', str(comfy),
                '--input', str(source), '--output', str(output), '--model', 'rife49.pth',
                '--multiplier', '2', '--preserve-audio']
            job.update(status='running', started_at=time.time())
            self.save(job)
            with (folder/'worker.log').open('w', encoding='utf-8') as log:
                process = self.spawn(command, stdout=log, stderr=subprocess.STDOUT)
                spawned = True
                job['pid'] = process.pid
                self.save(job)
                with self.enhance.LOCK:
                    self.enhance.ACTIVE['process'] = process
                if process.wait(timeout=600):
                    raise ValueError('processor_failed')
                clean_exit = True
            after = media_info(output, ffmpeg)
            if (any(after[k] != before[k] for k in ('width', 'height')) or after['fps'] != 48 or
                after['frames'] != expected_frames or after['video_duration'] < after['audio_duration'] or
                abs(before['audio_duration']-after['audio_duration']) > 1/32000 or
                audio_hash(source, ffmpeg) != audio_hash(output, ffmpeg)):
                raise ValueError('result_verification_failed')
            decoded = subprocess.run([ffmpeg, '-v', 'error', '-xerror', '-i', str(output), '-f', 'null', '-'],
                capture_output=True, timeout=120, check=True)
            if decoded.stderr.strip():
                raise ValueError('decode_failed')
            receipt = {'key': key, 'source_sha256': job['source_sha256'], 'recipe': RECIPE,
                'model_sha256': MODEL_SHA, 'result_sha256': checksum(output), 'result_bytes': output.stat().st_size,
                'source_metadata': before, 'result_metadata': after, 'audio_payload_sha256': audio_hash(output, ffmpeg),
                'helper_sha256': checksum(Path(__file__).with_name('rife_video.py')),
                'started_at': job['started_at'], 'finished_at': time.time()}
            job.update(status='succeeded', receipt=receipt, finished_at=receipt['finished_at'])
            self.save(job)
        except Exception as exc:
            reason = str(exc) if type(exc) is ValueError and re.fullmatch('[a-z_]+', str(exc)) else 'processor_failed'
            interrupted = spawned and not clean_exit
            if interrupted:
                self.recovery_required = True
            job.update(status='interrupted' if interrupted else 'failed', error=reason, finished_at=time.time())
            self.save(job)
        finally:
            # A timed-out owned child can still be alive. Keep its reservation;
            # never start another job on top of it or kill unrelated processes.
            process = self.enhance.ACTIVE.get('process')
            with self.enhance.LOCK:
                if self.enhance.ACTIVE['job'] == 'mediaos:'+key and (not process or process.poll() is not None):
                    self.enhance.ACTIVE.update(job=None, process=None)


def register(app, authorized, service=None):
    if service is None:
        import enhance_service
        service = RifeService(os.environ.get('MEDIAOS_RIFE_DATA', r'C:\AtelierStudio\mediaos_rife_jobs'), enhance_service)
    app.extensions['mediaos_rife'] = service

    @app.get('/mediaos/rife/availability')
    def mediaos_rife_availability():
        if not authorized():
            return jsonify(error='unauthorized'), 401
        return jsonify(protocol=1, recipe=RECIPE, **service.availability())

    @app.route('/mediaos/rife/jobs/<key>', methods=['GET', 'POST'])
    def mediaos_rife_job(key):
        if not authorized():
            return jsonify(error='unauthorized'), 401
        if not re.fullmatch('[0-9a-f]{64}', key):
            return jsonify(error='invalid_key'), 400
        if request.method == 'GET':
            job = service.get(key)
            return (jsonify(job), 200) if job else (jsonify(error='not_found'), 404)
        if request.content_length is None or request.content_length > MAX_BYTES + 1024*1024:
            return jsonify(error='upload_too_large'), 413
        upload = request.files.get('video')
        try:
            manifest = json.loads(request.form.get('manifest', ''))
        except (ValueError, TypeError):
            return jsonify(error='invalid_manifest'), 400
        if upload is None:
            return jsonify(error='missing_source'), 400
        body, code = service.submit(key, manifest, upload)
        return jsonify(body), code

    @app.get('/mediaos/rife/jobs/<key>/result')
    def mediaos_rife_result(key):
        if not authorized():
            return jsonify(error='unauthorized'), 401
        if not re.fullmatch('[0-9a-f]{64}', key):
            return jsonify(error='invalid_key'), 400
        job = service.get(key)
        if not job:
            return jsonify(error='not_found'), 404
        if job['status'] != 'succeeded':
            return jsonify(error='result_unsettled'), 409
        path = service.root/key/'result.mp4'
        if not path.is_file() or checksum(path) != job['receipt']['result_sha256']:
            return jsonify(error='result_changed'), 409
        return send_file(path, mimetype='video/mp4', as_attachment=False, download_name='RIFE2x-complete-audio.mp4')

    return service
