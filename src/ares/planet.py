"""Planetary reference profiles and explicit vehicle compatibility."""
from dataclasses import dataclass
import unicodedata

ASSUMPTION = 'supuesto de simulación'


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.lower()) if unicodedata.category(c) != 'Mn')


@dataclass(frozen=True)
class PlanetProfile:
    name: str
    rocky: bool
    gravity: float
    temperature: float
    pressure: float
    oxygen: float
    hazards: tuple
    mode: str = 'rover'
    operational_label: str = ASSUMPTION

    @classmethod
    def for_body(cls, name='Marte', mode='rover'):
        key = normalize(name)
        if key not in PROFILES:
            raise ValueError('Planeta desconocido')
        mode_key = normalize(mode)
        modes = {'rover': 'rover', 'ruedas': 'rover', 'sonda': 'probe', 'probe': 'probe'}
        if mode_key not in modes:
            raise ValueError('Modo inválido: use rover o sonda')
        profile = cls(*PROFILES[key], mode=modes[mode_key])
        profile.validate()
        return profile

    def validate(self):
        if self.mode not in ('rover', 'probe'):
            raise ValueError('Modo inválido: use rover o sonda')
        if not self.rocky and self.mode == 'rover':
            raise ValueError(f'{self.name} no tiene suelo sólido accesible y estable para ruedas; seleccione modo sonda atmosférica virtual.')
        return self


PROFILES = {
    'mercurio': ('Mercurio', True, 3.7, 167., 0., 0., ('radiación', 'contraste térmico')),
    'venus': ('Venus', True, 8.87, 464., 9200000., 0., ('corrosión', 'presión', 'temperatura')),
    'tierra': ('Tierra', True, 9.81, 15., 101325., 20.95, ('sismo', 'lluvia')),
    'marte': ('Marte', True, 3.71, -63., 610., .13, ('polvo', 'barranco', 'noche')),
    'jupiter': ('Júpiter', False, 24.79, -110., 100000., 0., ('turbulencia', 'presión')),
    'saturno': ('Saturno', False, 10.44, -140., 100000., 0., ('viento', 'enlace')),
    'urano': ('Urano', False, 8.69, -195., 100000., 0., ('frío', 'energía')),
    'neptuno': ('Neptuno', False, 11.15, -200., 100000., 0., ('viento', 'latencia')),
}
