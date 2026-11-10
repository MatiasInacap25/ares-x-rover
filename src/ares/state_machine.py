"""Physical-only mission loop. No AI policy is implied by this controller."""
from collections import deque
from enum import Enum
import math
from .planet import PlanetProfile, ASSUMPTION
from .sensors import SensorSuite
from .logger import MissionLogger
from .events import Event


class MissionState(str, Enum):
    CONFIGURACION = 'CONFIGURACION'
    EXPLORACION = 'EXPLORACION'
    ALERTA = 'ALERTA'
    REPLANIFICACION = 'REPLANIFICACION'
    REFUGIO = 'REFUGIO'
    MODO_SEGURO = 'MODO_SEGURO'
    EXITO = 'EXITO'
    FRACASO = 'FRACASO'


class Mission:
    operational_label = ASSUMPTION

    def __init__(self, world, profile=None, battery=100., step_duration=1., sensors=None, logger=None, thermal_limit=500.):
        if not math.isfinite(battery) or not 0 <= battery <= 100:
            raise ValueError('Batería inválida: debe estar entre 0 y 100')
        if not math.isfinite(step_duration) or step_duration <= 0:
            raise ValueError('Duración de paso inválida')
        if not math.isfinite(thermal_limit) or thermal_limit <= -273.15:
            raise ValueError('Límite térmico inválido')
        self.thermal_limit = thermal_limit
        self.world = world
        self.profile = (profile or PlanetProfile.for_body()).validate()
        self.battery, self.step_duration = float(battery), float(step_duration)
        self.sensors = sensors or SensorSuite(world.seed)
        self.logger = logger or MissionLogger()
        self.position = (0, 0)
        self.state = MissionState.CONFIGURACION
        self.health = 100.
        self.daylight, self.visibility = True, 1.
        self.wait_steps = 0
        self.elapsed = 0.
        self.pending_events = []
        self.paused = False
        self.path = [self.position]

    @property
    def science_progress(self):
        return self.world.science_progress

    def refuge_distance(self, start):
        """Physical reachability only; this is not an AI route planner."""
        queue = deque([(start, 0)])
        seen = {start}
        while queue:
            position, distance = queue.popleft()
            if position in self.world.refuges:
                return distance
            for dr, dc in ((-1, 0), (0, 1), (1, 0), (0, -1)):
                neighbor = (position[0] + dr, position[1] + dc)
                if neighbor in seen or not self.world.traversable(neighbor, self.profile.mode):
                    continue
                if self.profile.mode == 'rover' and self.world.elevation[neighbor] - self.world.elevation[position] < -5:
                    continue
                seen.add(neighbor)
                queue.append((neighbor, distance + 1))
        return math.inf

    def inject_event(self, kind, **data):
        event = Event(kind, data)
        self.pending_events.append(event.apply(self))

    def step(self, target=None):
        if self.paused or self.state in (MissionState.EXITO, MissionState.FRACASO):
            return None
        target = self.position if target is None else tuple(target)
        readings = self.sensors.observe(self.world, self.position, target, self.battery, self.profile, self.daylight, self.visibility)
        action, reason = 'detener', 'ESPERA'
        if self.battery <= 0 or self.health <= 0:
            self.state, reason = MissionState.FRACASO, 'RECURSOS_AGOTADOS'
        elif readings['temperature_external'] is not None and math.isfinite(readings['temperature_external']) and readings['temperature_external'] > self.thermal_limit:
            self.state, reason = MissionState.MODO_SEGURO, 'LIMITE_TERMICO'
        elif self.health < 30:
            self.state, reason = MissionState.MODO_SEGURO, 'DANO_CRITICO'
        elif readings['cliff'] and self.profile.mode == 'rover':
            if self.world.in_bounds(target):
                self.world.cliffs.add(target)
            self.state, reason = MissionState.REPLANIFICACION, 'BARRANCO_CONFIRMADO'
        elif not self.world.traversable(target, self.profile.mode):
            self.state, reason = MissionState.REPLANIFICACION, 'RUTA_BLOQUEADA'
        elif not self.sensors.validate(readings):
            self.state, reason = MissionState.MODO_SEGURO, 'SENSOR_CRITICO_INVALIDO'
        elif self.wait_steps:
            self.wait_steps -= 1
            self.state, reason = MissionState.ALERTA, 'ESPERAR_REMEDIR'
        elif abs(target[0] - self.position[0]) + abs(target[1] - self.position[1]) > 1:
            self.state, reason = MissionState.REPLANIFICACION, 'MOVIMIENTO_NO_CONTIGUO'
        elif target != self.position:
            cost = self.step_duration * (1 + (1-self.visibility))
            return_distance = self.refuge_distance(self.position)
            target_distance = self.refuge_distance(target)
            if cost > self.battery:
                self.state, reason = MissionState.MODO_SEGURO, 'ENERGIA_INSUFICIENTE'
            elif self.battery <= 10 and self.position not in self.world.refuges and (return_distance * cost > self.battery or target_distance >= return_distance):
                self.state, reason = MissionState.MODO_SEGURO, 'REFUGIO_INALCANZABLE'
                if return_distance * cost <= self.battery:
                    self.state, reason = MissionState.REFUGIO, 'RECURSOS_CRITICOS'
            else:
                self.battery = max(0., self.battery - cost)
                self.position = target
                self.path.append(target)
                self.world.visited_science.update({target} & self.world.science_sites)
                self.state, action, reason = MissionState.EXPLORACION, 'avanzar', 'MOVIMIENTO_VALIDO'
                if self.battery == 0:
                    self.state, reason = MissionState.FRACASO, 'RECURSOS_AGOTADOS'
        else:
            self.state = MissionState.EXPLORACION
        if self.science_progress == 1 and self.position in self.world.refuges and self.state == MissionState.EXPLORACION:
            self.state, reason = MissionState.EXITO, 'OBJETIVOS_Y_RETORNO_COMPLETADOS'
        self.elapsed += self.step_duration
        events, self.pending_events = self.pending_events, []
        return self.logger.record(step=len(self.logger.trace), elapsed=self.elapsed, state=self.state.value,
                                  position=self.position, battery=self.battery, health=self.health,
                                  sensors=readings, events=events, action=action, reason=reason,
                                  science_progress=self.science_progress, seed=self.world.seed,
                                  operational_label=ASSUMPTION)


StateMachine = Mission
