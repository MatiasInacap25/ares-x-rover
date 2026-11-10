"""Hybrid safety supervisor: physical prohibitions first, then AI proposals.

Every decision carries a reproducible reason code. Rules are evaluated in a
fixed priority order, so simultaneous events always resolve the same way.
"""
from dataclasses import dataclass, field

from .planet import ASSUMPTION

# Ordered by priority (lower index wins). Codes are stable for audits/tests.
REASONS = {
    'R00_RECURSOS_AGOTADOS': 'Batería o integridad agotadas: misión terminada.',
    'R01_LIMITE_TERMICO': 'Temperatura fuera de la tolerancia del hardware: se aísla el sistema.',
    'R02_SENSORES_NAVEGACION_FALLIDOS': 'Fallan todos los sensores de navegación: no se avanza a ciegas.',
    'R03_DANO_CRITICO': 'Integridad mecánica crítica: modo seguro.',
    'R04_VETO_BARRANCO_CONFIRMADO': 'El sensor de borde confirma un barranco en la siguiente celda: se detiene y replanifica.',
    'R05_RNA_PELIGRO': 'La RNA predice peligro en la siguiente celda con confianza suficiente: se detiene y replanifica.',
    'R06_REFUGIO_INALCANZABLE': 'La energía no alcanza para llegar a ningún refugio: se declara inalcanzable y se espera en modo seguro.',
    'R07_RETORNO_ENERGIA': 'La energía restante solo alcanza para volver: se prioriza el refugio.',
    'R08_ESPERA_SISMO': 'Sismo detectado: frenar, esperar y volver a medir.',
    'R09_RECARGA': 'En refugio con batería incompleta: se recarga.',
    'R10_SIN_RUTA': 'No existe ruta factible: se informa sin solución y se espera.',
    'R11_REPLANIFICAR': 'Ruta bloqueada o evento grave: se ejecuta el AG.',
    'R12_DIFUSO_PARAR': 'El controlador difuso recomienda velocidad casi nula: se detiene.',
    'R13_AVANCE_DEGRADADO': 'Sensor degradado o RNA con baja confianza: avance conservador fusionado con sensor determinista.',
    'R14_AVANCE': 'Ruta segura y sensores válidos: se avanza.',
    'R15_MISION_COMPLETA': 'Objetivos alcanzables completados y retorno seguro.',
}
PRIORITY = list(REASONS)


@dataclass
class Decision:
    action: str            # avanzar | detener | recargar | volver | replanificar
    reason: str
    state: str
    speed_cap: float = 1.0
    vetoes: list = field(default_factory=list)
    permitted_by: list = field(default_factory=list)

    @property
    def explanation(self):
        return REASONS[self.reason]

    def to_dict(self):
        return {'action': self.action, 'reason': self.reason, 'state': self.state,
                'explanation': self.explanation, 'speed_cap': self.speed_cap,
                'vetoes': list(self.vetoes), 'permitted_by': list(self.permitted_by),
                'operational_label': ASSUMPTION}


class SafetySupervisor:
    """Arbitrates RNA, fuzzy and GA recommendations under hard constraints.

    ``context`` keys: battery, health (required); temperature_internal,
    thermal_limit, nav_valid (sensor -> bool), edge_cliff, rna (prediction or
    None), rna_used, fuzzy_speed, has_route, needs_replan, quake_wait,
    at_refuge, energy_to_refuge, recharge_target, returning, mission_complete.
    """

    operational_label = ASSUMPTION

    def __init__(self, confidence_threshold=.65, hazard_threshold=.5, return_margin=1.25,
                 stop_speed=.08, degraded_speed=.3):
        self.confidence_threshold = confidence_threshold
        self.hazard_threshold = hazard_threshold
        self.return_margin = return_margin
        self.stop_speed = stop_speed
        self.degraded_speed = degraded_speed

    def decide(self, ctx):
        vetoes, permits = [], []
        battery, health = ctx['battery'], ctx['health']
        if battery <= 0 or health <= 0:
            return Decision('detener', 'R00_RECURSOS_AGOTADOS', 'FRACASO')
        if ctx.get('temperature_internal', 20) > ctx.get('thermal_limit', 1e9):
            return Decision('detener', 'R01_LIMITE_TERMICO', 'MODO_SEGURO')
        nav = ctx.get('nav_valid', {})
        if nav and not any(nav.values()):
            return Decision('detener', 'R02_SENSORES_NAVEGACION_FALLIDOS', 'MODO_SEGURO')
        if health < 30:
            return Decision('detener', 'R03_DANO_CRITICO', 'MODO_SEGURO')
        if ctx.get('mission_complete'):
            return Decision('detener', 'R15_MISION_COMPLETA', 'EXITO')
        # Energy feasibility is a physical constraint and precedes AI proposals.
        energy_to_refuge = ctx.get('energy_to_refuge', 0.)
        if not ctx.get('at_refuge') and (energy_to_refuge == float('inf') or energy_to_refuge > battery):
            return Decision('detener', 'R06_REFUGIO_INALCANZABLE', 'MODO_SEGURO')
        if ctx.get('edge_cliff'):
            vetoes.append('Barranco confirmado por sensor de borde')
            return Decision('replanificar', 'R04_VETO_BARRANCO_CONFIRMADO', 'REPLANIFICACION', 0., vetoes)
        rna = ctx.get('rna') if ctx.get('rna_used', True) else None
        low_confidence = False
        if rna is not None:
            hazard = 1 - rna['probabilities']['libre']
            if rna['confidence'] >= self.confidence_threshold and rna['label'] != 'libre':
                vetoes.append(f"RNA: {rna['label']} p={rna['confidence']:.2f}")
                return Decision('replanificar', 'R05_RNA_PELIGRO', 'ALERTA', 0., vetoes)
            low_confidence = rna['low_confidence'] or hazard >= self.hazard_threshold
            permits.append(f"RNA: libre p={rna['probabilities']['libre']:.2f}")
        if ctx.get('quake_wait', 0) > 0:
            return Decision('detener', 'R08_ESPERA_SISMO', 'ALERTA', 0., vetoes, permits)
        if ctx.get('at_refuge') and battery < ctx.get('recharge_target', 0):
            return Decision('recargar', 'R09_RECARGA', 'REFUGIO', 0., vetoes, permits)
        if not ctx.get('at_refuge') and not ctx.get('returning') and energy_to_refuge * self.return_margin >= battery:
            permits.append('Energía justa para el retorno')
            return Decision('volver', 'R07_RETORNO_ENERGIA', 'REFUGIO', self.degraded_speed, vetoes, permits)
        if ctx.get('needs_replan'):
            return Decision('replanificar', 'R11_REPLANIFICAR', 'REPLANIFICACION', 0., vetoes, permits)
        if not ctx.get('has_route'):
            return Decision('detener', 'R10_SIN_RUTA', 'ALERTA', 0., vetoes, permits)
        speed = ctx.get('fuzzy_speed')
        if speed is not None and speed < self.stop_speed:
            return Decision('detener', 'R12_DIFUSO_PARAR', 'ALERTA', 0., vetoes, permits)
        if low_confidence or (nav and not all(nav.values())):
            permits.append('Avance limitado por degradación')
            return Decision('avanzar', 'R13_AVANCE_DEGRADADO', 'ALERTA', self.degraded_speed, vetoes, permits)
        state = 'REFUGIO' if ctx.get('returning') else 'EXPLORACION'
        return Decision('avanzar', 'R14_AVANCE', state, 1.0, vetoes, permits)

    def filter_routes(self, candidates, known_cliffs, known_obstacles):
        """Reject GA candidates crossing confirmed hazards; document each veto."""
        accepted, rejected = [], []
        for index, candidate in enumerate(candidates):
            route = candidate.get('route') or []
            bad = [cell for cell in route if cell in known_cliffs or cell in known_obstacles]
            if bad:
                rejected.append({'index': index, 'reason': 'cruza peligro confirmado', 'cells': [list(c) for c in bad[:3]]})
            elif not candidate.get('feasible'):
                rejected.append({'index': index, 'reason': 'infactible: ' + ', '.join(candidate.get('violations', [])), 'cells': []})
            elif not route:
                rejected.append({'index': index, 'reason': 'ruta vacía', 'cells': []})
            else:
                accepted.append(index)
        return accepted, rejected
