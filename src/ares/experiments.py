"""Repeated experiments: >= 20 seeds per scenario, ablations and baselines (RF-14, RF-15)."""
import time

import numpy as np
import pandas as pd

from .mission import POLICIES, HybridMission

SCENARIOS = {
    'estandar': dict(label='Estándar (peligros ocultos)', events=[]),
    'eventos': dict(label='Con eventos (barranco, tormenta, sismo, falla de sensor)',
                    events=[(3, 'barranco', {}), (8, 'tormenta_polvo', {}), (14, 'sismo', {}),
                            (20, 'falla_sensor', {'sensor': 'distance'}), (26, 'alienigena', {})]),
    'bateria_baja': dict(label='Batería inicial 25 %', events=[], battery=25.),
}
METRICS = ['success', 'collisions', 'cliffs_avoided', 'hazards_avoided', 'battery_left', 'distance',
           'science', 'replans', 'safety_violations', 'decision_ms', 'steps']


def run_one(policy, seed, scenario='estandar', **overrides):
    spec = SCENARIOS[scenario]
    config = dict(policy=policy, seed=seed, battery=spec.get('battery', 100.), hidden_cliffs=6, difficulty='medium')
    config.update(overrides)
    mission = HybridMission(**config)
    schedule = sorted(spec['events'], key=lambda e: e[0])
    started = time.perf_counter()
    while not mission.finished and mission.step_index < 400:
        for at, kind, data in schedule:
            if mission.step_index == at:
                try:
                    mission.inject(kind, **dict(data))
                except ValueError:
                    pass  # event not applicable in this state (e.g. no free cell)
        mission.step()
    row = mission.summary()
    row.update(scenario=scenario, wall_s=round(time.perf_counter() - started, 3))
    return row


def run_experiments(policies=None, seeds=20, scenario='estandar', first_seed=0, progress=None, **overrides):
    policies = list(policies or POLICIES)
    unknown = set(policies) - set(POLICIES)
    if unknown:
        raise ValueError(f'Políticas desconocidas: {sorted(unknown)}')
    if not isinstance(seeds, int) or not 1 <= seeds <= 200:
        raise ValueError('Cantidad de semillas inválida (1–200)')
    rows = []
    for policy in policies:
        for seed in range(first_seed, first_seed + seeds):
            rows.append(run_one(policy, seed, scenario, **overrides))
            if progress:
                progress(len(rows), len(policies) * seeds)
    return pd.DataFrame(rows)


def summarize(frame):
    """Mean, median and standard deviation per policy (dispersion is reported)."""
    frame = frame.copy()
    frame['success'] = frame['success'].astype(float)
    grouped = frame.groupby('policy')[METRICS]
    table = pd.concat({'media': grouped.mean(), 'mediana': grouped.median(), 'desv': grouped.std(ddof=1).fillna(0.)}, axis=1)
    order = [p for p in POLICIES if p in table.index]
    return table.loc[order]


def summary_records(frame):
    table = summarize(frame)
    records = []
    for policy, row in table.iterrows():
        entry = {'policy': policy, 'label': POLICIES[policy]['label'], 'n': int((frame['policy'] == policy).sum())}
        for metric in METRICS:
            entry[metric] = {stat: float(np.round(row[(stat, metric)], 4)) for stat in ('media', 'mediana', 'desv')}
        records.append(entry)
    return records
