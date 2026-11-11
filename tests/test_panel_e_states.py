"""Panel E must tell 'no inference yet' apart from 'policy without fuzzy logic'."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from ares.api import Session  # noqa: E402
from ares.mission import POLICIES  # noqa: E402


@pytest.mark.parametrize('policy', list(POLICIES))
def test_snapshot_says_which_components_the_policy_uses(policy):
    snapshot = Session(seed=42, policy=policy).dispatch('state')
    flags = POLICIES[policy]
    assert snapshot['policy_uses'] == {'rna': flags['rna'], 'fuzzy': flags['fuzzy'], 'ga': flags['ga']}


def test_a_hybrid_mission_at_step_zero_has_fuzzy_enabled_but_no_inference_yet():
    session = Session(seed=42)
    session.dispatch('step', {})
    snapshot = session.dispatch('reset')
    assert snapshot['fuzzy'] is None and snapshot['policy_uses']['fuzzy'] is True
    assert session.dispatch('step', {})['fuzzy'] is not None


def test_a_historical_ga_run_keeps_its_candidate_routes_for_the_minimap():
    session = Session(seed=42)
    first = session.dispatch('step', {})
    session.dispatch('inject', {'kind': 'tormenta_polvo'})          # forces a new GA run
    run = session.dispatch('ga_run', {'run': 0})
    routes = run['ga']['routes']
    assert len(routes) == len(run['ga']['candidates']) and all(len(r) >= 2 for r in routes)
    assert routes[run['ga']['chosen']] == first['map']['candidates'][first['map']['chosen']]
