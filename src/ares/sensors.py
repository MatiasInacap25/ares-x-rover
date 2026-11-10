"""Imperfect measurements, with explicit critical-reading validation."""
import math
import numpy as np
from .planet import ASSUMPTION


class SensorSuite:
    operational_label = ASSUMPTION
    ranges = {'distance': (0, 20), 'slope': (0, 45), 'battery': (0, 100),
              'elevation_delta': (-1e6, 1e6), 'temperature_external': (-273.15, 1e4)}

    def __init__(self, seed=0, noise=.05):
        if not math.isfinite(noise) or noise < 0:
            raise ValueError('Ruido inválido')
        self.rng = np.random.default_rng(seed)
        self.noise = noise
        self.failures = {}
        self.link_available = True

    @staticmethod
    def validate(readings):
        for key in ('distance',):
            value = readings.get(key)
            if not isinstance(value, (int, float, np.number)) or not math.isfinite(value) or not 0 < value <= 20:
                return False
        for key in ('elevation_delta', 'temperature_external', 'temperature_internal'):
            if key in readings:
                value = readings[key]
                if not isinstance(value, (int, float, np.number)) or not math.isfinite(value):
                    return False
        for key, bounds in SensorSuite.ranges.items():
            if key in readings:
                value = readings[key]
                if not isinstance(value, (int, float, np.number)) or not math.isfinite(value) or not bounds[0] <= value <= bounds[1]:
                    return False
        return True

    def fail(self, sensor='distance', failure='nan'):
        if failure not in ('nan', 'saturation', 'missing'):
            raise ValueError('Tipo de falla desconocido')
        self.failures[sensor] = failure

    def observe(self, world, position, target, battery, profile, daylight=True, visibility=1.):
        valid = world.in_bounds(target)
        delta = float(world.elevation[target] - world.elevation[position]) if valid else 0.
        blocked = not world.traversable(target, profile.mode)
        readings = {
            'distance': 0. if blocked else float(np.clip(10 + self.rng.normal(0, self.noise), .001, 20)),
            'elevation_delta': delta,
            'cliff': valid and (tuple(target) in world.cliffs or delta < -5),
            'slope': float(min(45, abs(delta) * 3)),
            'battery': battery,
            'temperature_external': profile.temperature + float(self.rng.normal(0, self.noise)),
            'temperature_internal': 20., 'radiation': .1, 'pressure': profile.pressure,
            'oxygen_ambient': profile.oxygen, 'oxygen_stored': 100., 'co2': 95. if profile.name == 'Marte' else .04,
            'so2': 0., 'visibility': visibility, 'particles': 1 - visibility,
            'solar_power': 10. * visibility if daylight else 0., 'position': tuple(position),
            'heading': 0., 'vibration': 0., 'texture': float(self.rng.random()),
            'link_available': self.link_available,
        }
        for key, failure in self.failures.items():
            readings[key] = {'nan': float('nan'), 'saturation': float('inf'), 'missing': None}[failure]
        return readings
