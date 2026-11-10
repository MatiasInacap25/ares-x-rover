"""Explicit, ordered event injection; narrative signals are not scientific proof."""
from dataclasses import dataclass, field
from .planet import normalize

EVENTS = ('barranco', 'bateria_baja', 'dia', 'noche', 'sismo', 'meteorito', 'tormenta_polvo', 'corrosion', 'biosenal_anomala', 'alienigena', 'falla_sensor', 'perdida_enlace', 'viento')
ALIASES = {'low_battery': 'bateria_baja', 'day': 'dia', 'night': 'noche', 'quake': 'sismo', 'dust_storm': 'tormenta_polvo', 'sensor_failure': 'falla_sensor', 'link_loss': 'perdida_enlace', 'wind': 'viento'}


@dataclass
class Event:
    kind: str
    data: dict = field(default_factory=dict)

    def __post_init__(self):
        self.kind = normalize(self.kind).replace(' ', '_')
        self.kind = ALIASES.get(self.kind, self.kind)
        if self.kind not in EVENTS:
            raise ValueError('Evento desconocido')

    def apply(self, mission):
        world = mission.world
        position = tuple(self.data.get('position', mission.position))
        if self.kind in ('barranco', 'meteorito', 'alienigena'):
            if not world.in_bounds(position):
                raise ValueError('Evento fuera del mapa')
            if self.kind == 'barranco':
                world.cliffs.add(position)
                world.elevation[position] -= 20
            else:
                world.add_obstacle(position)
        elif self.kind == 'bateria_baja':
            mission.battery = min(mission.battery, 10.)
        elif self.kind in ('dia', 'noche'):
            mission.daylight = self.kind == 'dia'
        elif self.kind == 'sismo':
            mission.wait_steps = max(mission.wait_steps, 1)
        elif self.kind == 'tormenta_polvo':
            mission.visibility = .2
        elif self.kind == 'corrosion':
            mission.health = max(0., mission.health - 20.)
        elif self.kind == 'falla_sensor':
            mission.sensors.fail(self.data.get('sensor', 'distance'), self.data.get('failure', 'nan'))
        elif self.kind == 'perdida_enlace':
            mission.sensors.link_available = False
        elif self.kind == 'viento' and mission.profile.mode == 'probe':
            mission.wait_steps = max(mission.wait_steps, 1)
        return {'kind': self.kind, 'message': {
            'biosenal_anomala': 'Bioseñal anómala simulada; no confirma vida.',
            'alienigena': 'Evento narrativo completamente ficticio; evitar objeto.',
            'viento': 'Viento simulado; límites específicos del modo sonda.',
        }.get(self.kind, 'Evento aplicado: ' + self.kind)}
