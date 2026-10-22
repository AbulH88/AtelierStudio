import hashlib
import io
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'home_agent'))
import mediaos_rife as rife


@pytest.fixture
def service(tmp_path, monkeypatch):
    enhance = SimpleNamespace(LOCK=threading.Lock(), ACTIVE={'job': None, 'process': None},
        _comfy_root=lambda: tmp_path, _models=lambda: ['rife49.pth'])
    launched = []
    monkeypatch.setattr(rife, 'model_hash', lambda root: rife.MODEL_SHA)
    service = rife.RifeService(tmp_path/'jobs', enhance, availability=lambda: {'free': True, 'reason': 'idle'}, launch=launched.append)
    service.launched = launched
    app = Flask(__name__)
    rife.register(app, lambda: __import__('flask').request.headers.get('x-agent-secret') == 'fixture-secret', service)
    service.client = app.test_client()
    return service


HEADERS = {'x-agent-secret': 'fixture-secret'}
KEY = 'a'*64
BLOB = b'exact accepted source'
SHA = hashlib.sha256(BLOB).hexdigest()


def submit(service, key=KEY, source_sha=SHA, blob=BLOB, recipe=None):
    manifest = {'source_sha256': source_sha, 'recipe': recipe or rife.RECIPE}
    return service.client.post('/mediaos/rife/jobs/'+key, headers=HEADERS,
        data={'manifest': json.dumps(manifest), 'video': (io.BytesIO(blob), 'source.mp4')})


@pytest.mark.parametrize('method,path', [('get','/mediaos/rife/availability'),
    ('get','/mediaos/rife/jobs/'+KEY),('get','/mediaos/rife/jobs/'+KEY+'/result'),
    ('post','/mediaos/rife/jobs/'+KEY)])
def test_all_routes_require_auth(service, method, path):
    assert getattr(service.client, method)(path).status_code == 401


def test_idempotent_submit_is_persistent_and_does_not_launch_twice(service):
    first = submit(service)
    assert first.status_code == 202
    assert submit(service).json == first.json
    assert service.launched == [KEY]
    assert service.enhance.ACTIVE['job'] == 'mediaos:'+KEY
    restored = rife.RifeService(service.root, service.enhance, availability=lambda: {'free': True}, launch=lambda key: pytest.fail('restart must not launch'))
    assert restored.get(KEY)['status'] == 'interrupted'
    assert restored.get(KEY)['source_sha256'] == SHA


def test_completed_result_survives_service_restart(service):
    assert submit(service).status_code == 202
    job = service.get(KEY)
    job.update(status='succeeded', receipt={'result_sha256': 'f'*64})
    service.save(job)
    restored = rife.RifeService(service.root, service.enhance, availability=lambda: {'free': True}, launch=lambda key: pytest.fail('must not relaunch'))
    assert restored.get(KEY)['receipt'] == job['receipt']
    assert restored.get(KEY)['status'] == 'succeeded'


def test_conflicting_source_or_recipe_never_reuses_key(service):
    assert submit(service).status_code == 202
    assert submit(service, source_sha='b'*64, blob=b'other').status_code == 409
    assert submit(service, recipe={**rife.RECIPE, 'multiplier': 4}).status_code == 400
    assert service.launched == [KEY]


def test_upload_hash_mismatch_and_path_key_rejected(service):
    assert submit(service, blob=b'wrong').status_code == 400
    assert submit(service, key='not-a-sha').status_code == 400
    assert service.launched == []


@pytest.mark.parametrize('why', ['gpu_busy','comfy_busy','gpu_state_unknown'])
def test_busy_or_unknown_readiness_never_claims_work(service, why):
    service.availability_probe = lambda: {'free': False, 'reason': why}
    assert submit(service).status_code == 409
    assert service.get(KEY) is None and service.launched == []


def test_legacy_enhance_reservation_blocks_mediaos(service):
    service.enhance.ACTIVE['job'] = 'legacy-enhance-job'
    assert submit(service).status_code == 409
    assert service.launched == []


def test_changed_model_is_not_silently_downloaded_or_used(service, monkeypatch):
    monkeypatch.setattr(rife, 'model_hash', lambda root: '0'*64)
    assert submit(service).status_code == 409
    assert service.get(KEY) is None and service.launched == []


def test_missing_and_non_success_result_are_bounded(service):
    assert service.client.get('/mediaos/rife/jobs/'+KEY, headers=HEADERS).status_code == 404
    assert submit(service).status_code == 202
    assert service.client.get('/mediaos/rife/jobs/'+KEY+'/result', headers=HEADERS).status_code == 409


def test_gpu_probe_checks_real_queue_and_free_memory(monkeypatch):
    monkeypatch.setattr(rife, 'queue_state', lambda: {'queue_running': [], 'queue_pending': []})
    monkeypatch.setattr(rife, 'gpu_state', lambda: (24000, 2))
    assert rife.local_availability()['free']
    monkeypatch.setattr(rife, 'gpu_state', lambda: (2000, 2))
    assert not rife.local_availability()['free']
    monkeypatch.setattr(rife, 'gpu_state', lambda: (24000, 60))
    assert not rife.local_availability()['free']
    monkeypatch.setattr(rife, 'queue_state', lambda: {'queue_running': [1], 'queue_pending': []})
    monkeypatch.setattr(rife, 'gpu_state', lambda: (24000, 2))
    assert rife.local_availability()['reason'] == 'comfy_busy'


def test_bad_queue_and_probe_error_fail_closed(monkeypatch):
    monkeypatch.setattr(rife, 'queue_state', lambda: {})
    monkeypatch.setattr(rife, 'gpu_state', lambda: (24000, 2))
    assert not rife.local_availability()['free']
    def broken(): raise RuntimeError('private command details')
    monkeypatch.setattr(rife, 'queue_state', broken)
    assert rife.local_availability() == {'free': False, 'reason': 'gpu_state_unknown'}


def test_nonfinite_gpu_metrics_are_unknown(monkeypatch):
    monkeypatch.setattr(rife,'queue_state',lambda:{'queue_running':[],'queue_pending':[]})
    monkeypatch.setattr(rife,'gpu_state',lambda:(float('nan'),2))
    assert not rife.local_availability()['free']


def test_worker_saves_actual_full_audio_receipt_and_releases_only_its_reservation(service,monkeypatch):
    import subprocess
    from rife_media import media_info, output_frames
    source=service.root/'fixture.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=s=64x64:r=24:d=0.3',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=32000:duration=0.317',
        '-c:v','libx264','-c:a','aac',str(source)],check=True)
    blob=source.read_bytes();digest=hashlib.sha256(blob).hexdigest()
    assert submit(service,source_sha=digest,blob=blob).status_code==202
    python=service.enhance._comfy_root()/'venv/Scripts/python.exe';python.parent.mkdir(parents=True);python.touch()
    commands=[]
    class Process:
        pid=12345
        def wait(self,timeout=None):return 0
        def poll(self):return 0
    def spawn(command,**kwargs):
        commands.append(command)
        target=Path(command[command.index('--output')+1])
        native=Path(command[command.index('--input')+1])
        info=media_info(native,'ffmpeg');frames=output_frames(info,48,info['frames']*2-1)
        subprocess.run(['ffmpeg','-v','error','-i',str(native),'-map','0:v','-an','-vf','fps=48,tpad=stop_mode=clone:stop_duration=0.1',
            '-frames:v',str(frames),'-c:v','libx264',str(target.with_name('picture.mp4'))],check=True)
        subprocess.run(['ffmpeg','-v','error','-i',str(target.with_name('picture.mp4')),'-i',str(native),
            '-map','0:v','-map','1:a','-c','copy',str(target)],check=True)
        return Process()
    monkeypatch.setattr(service,'spawn',spawn)
    service.work(KEY)
    job=service.get(KEY)
    assert job['status']=='succeeded' and job['receipt']['model_sha256']==rife.MODEL_SHA
    assert '--preserve-audio' in commands[0] and service.enhance.ACTIVE['job'] is None
    response=service.client.get('/mediaos/rife/jobs/'+KEY+'/result',headers=HEADERS)
    assert response.status_code==200 and hashlib.sha256(response.data).hexdigest()==job['receipt']['result_sha256']
