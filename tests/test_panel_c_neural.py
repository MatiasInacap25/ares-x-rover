"""Panel C -> D integration checks using the real public engine interface.

Run: .venv/bin/python -m pytest tests/test_panel_c_neural.py -q
Browser checks additionally require Chromium and Node with built-in WebSocket.
"""
import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from ares.api import Session  # noqa: E402
from ares.mission import EVENT_LABELS, POLICIES  # noqa: E402
from ares.planet import PROFILES  # noqa: E402


@pytest.fixture
def session():
    return Session(seed=42)


def command(session, name, **args):
    result = session.dispatch(name, args)
    assert 'error' not in result, result
    return result


def assert_neural(snapshot):
    prediction = snapshot['rna']
    if prediction is None:
        assert (not POLICIES[snapshot['config']['policy']]['rna']
                or snapshot['rna_error'] or snapshot['status']['finished']
                or snapshot['decision']), snapshot
        return
    assert len(prediction['features']) == len(prediction['normalized']) == 6
    assert set(prediction['probabilities']) == {'libre', 'obstaculo', 'barranco'}
    assert sum(prediction['probabilities'].values()) == pytest.approx(1, abs=.0002)
    assert prediction['confidence'] == max(prediction['probabilities'].values())
    assert prediction['label'] in prediction['probabilities']
    assert len(prediction['cell']) == 2
    assert prediction['layers']


CONFIGS = [
    *[{'planet': profile[0], 'mode': 'rover' if profile[1] else 'sonda'}
      for profile in PROFILES.values()],
    {'mode': 'sonda'},
    *[{'policy': policy} for policy in POLICIES],
    *[{'seed': seed} for seed in (0, 7, 42)],
    *[{'difficulty': level} for level in ('low', 'medium', 'high')],
    *[{'battery': battery} for battery in (0, 50, 100)],
    *[{'step_duration': duration} for duration in (.5, 1, 1.5, 2, 2.5, 3)],
    {'drone': True}, {'drone': False},
]


@pytest.mark.parametrize('config', CONFIGS, ids=lambda c: str(c))
def test_apply_config_clears_prediction_without_retraining(session, config):
    initial = command(session, 'step', n=1)
    assert initial['rna'] is not None
    network = command(session, 'meta')['network']
    applied = command(session, 'configure', **config)
    assert applied['status']['step'] == 0 and applied['rna'] is None
    for key, value in config.items():
        assert applied['config'][key] == value
    after = command(session, 'step', n=1)
    assert_neural(after)
    assert after['nn'] == initial['nn']
    assert command(session, 'meta')['network'] == network
    if 'policy' in config:
        assert (after['rna'] is not None) == POLICIES[config['policy']]['rna']


@pytest.mark.parametrize('kind', list(EVENT_LABELS) + ['navigation_total'])
def test_each_event_retains_last_prediction_until_next_step(session, kind):
    before = command(session, 'step', n=1)
    args = {'kind': kind} if kind != 'navigation_total' else {'kind': 'falla_sensor', 'sensor': 'todos'}
    injected = command(session, 'inject', **args)
    assert injected['rna'] == before['rna']
    assert injected['event_feed']['total'] == before['event_feed']['total'] + 1
    after = command(session, 'step', n=1)
    assert after['status']['step'] == before['status']['step'] + 1
    assert after['nn'] == before['nn']
    assert_neural(after)
    if kind == 'navigation_total':
        assert after['rna'] is None and after['rna_error']


@pytest.mark.parametrize('operation,args', [
    ('reset', {}), ('ghosts', {'enabled': True}), ('ghosts', {'enabled': False}),
])
def test_reset_and_ghost_controls_clear_live_inference(session, operation, args):
    before = command(session, 'step', n=1)
    reset = command(session, operation, **args)
    assert reset['rna'] is None and reset['status']['step'] == 0
    after = command(session, 'step', n=1)
    assert after['rna'] == before['rna'] and after['nn'] == before['nn']


@pytest.mark.parametrize('kind', ['obstaculo', 'barranco', 'limpiar'])
def test_terrain_edit_is_observed_on_next_step(session, kind):
    before = command(session, 'step', n=1)
    cell = before['rna']['cell']
    edited = command(session, 'place', position=cell, kind=kind)
    assert edited['rna'] == before['rna']
    if kind == 'limpiar':
        assert cell not in edited['map']['cliffs'] + edited['map']['obstacles']
    else:
        key = 'hidden_cliffs' if kind == 'barranco' else 'hidden_obstacles'
        assert cell in edited['map'][key]
    after = command(session, 'step', n=1)
    assert_neural(after)
    assert after['nn'] == before['nn']


def test_destination_add_remove_and_clear_do_not_retrain(session):
    before = command(session, 'step', n=1)
    cell = before['rna']['cell']
    added = command(session, 'destination', position=cell)
    assert cell in added['map']['destinations'] and added['rna'] == before['rna']
    removed = command(session, 'destination', position=cell)
    assert cell not in removed['map']['destinations']
    command(session, 'destination', position=cell)
    cleared = command(session, 'destination')
    assert cleared['map']['destinations'] == []
    assert_neural(command(session, 'step', n=1))
    assert command(session, 'state')['nn'] == before['nn']


@pytest.mark.parametrize('format', ['csv', 'json', 'comparison_csv'])
def test_export_does_not_change_panel_d(session, format):
    before = command(session, 'step', n=1)
    result = session.dispatch('export', {'format': format})
    if format == 'comparison_csv':
        assert 'Primero' in result['error']
    else:
        assert result['content'] and result['filename'].endswith('.' + format)
    assert command(session, 'state') == before


def test_live_inference_matches_panel_d_manual_evaluation(session):
    live = command(session, 'step', n=1)['rna']
    manual = command(session, 'rna_eval', **live['features'])
    assert manual['label'] == live['label']
    for label, probability in live['probabilities'].items():
        assert manual['probabilities'][label] == pytest.approx(probability, abs=.002)


@pytest.fixture(scope='module')
def browser_results(tmp_path_factory):
    if not (ROOT / 'server.py').exists():
        pytest.skip('server.py and the browser script are not bundled in the notebook')
    assert shutil.which('chromium') and shutil.which('node'), 'Chromium and Node are required'
    scratch = tmp_path_factory.mktemp('panel-c-d')
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        app_port = reservation.getsockname()[1]
    processes = []
    with (scratch / 'server.log').open('w') as log:
        try:
            server = subprocess.Popen([sys.executable, str(ROOT / 'server.py'), '--port', str(app_port)],
                                      stdout=log, stderr=log, cwd=ROOT)
            processes.append(server)
            deadline = time.monotonic() + 90
            while True:
                try:
                    urllib.request.urlopen(f'http://127.0.0.1:{app_port}/', timeout=1).close()
                    break
                except OSError:
                    assert server.poll() is None, (scratch / 'server.log').read_text()
                    assert time.monotonic() < deadline, 'Server startup timed out'
                    time.sleep(.2)
            chrome = subprocess.Popen(['chromium', '--headless', '--disable-gpu',
                '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0',
                f'--user-data-dir={scratch / "profile"}', 'about:blank'],
                stdout=log, stderr=log)
            processes.append(chrome)
            port_file = scratch / 'profile' / 'DevToolsActivePort'
            deadline = time.monotonic() + 20
            while not port_file.exists():
                assert chrome.poll() is None, (scratch / 'server.log').read_text()
                assert time.monotonic() < deadline, 'Chromium startup timed out'
                time.sleep(.1)
            port = port_file.read_text().splitlines()[0]
            run = subprocess.run(['node', str(ROOT / 'tests' / 'panel_c_neural_browser.mjs'), port, str(app_port)],
                                 capture_output=True, text=True, timeout=180)
            assert run.returncode == 0, run.stderr + run.stdout
            (scratch / 'browser-results.json').write_text(run.stdout)
            return json.loads(run.stdout)
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def test_panel_c_to_d_real_browser(browser_results):
    failures = [result for result in browser_results if not result['passed']]
    assert not failures, json.dumps(failures, ensure_ascii=False, indent=2)
