"""Build the static web version (site/) that runs the same Python engine in the browser via Pyodide."""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / 'site'
PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.27.7/full/'
MODULES = ['__init__', 'planet', 'world', 'sensors', 'events', 'logger', 'state_machine', 'neural', 'fuzzy',
           'genetic', 'supervisor', 'mission', 'experiments', 'api']

BOOT = f"""<script src="{PYODIDE}pyodide.js"></script>
<script>
// Boots the Python engine (numpy + scikit-learn) inside the browser with Pyodide.
window.ARES_BOOT = (async () => {{
  const box = document.createElement('div');
  box.id = 'bootOverlay';
  box.style.cssText = 'position:fixed;inset:0;z-index:99;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;background:#070b12;color:#d7e2f0;font:14px system-ui,sans-serif';
  box.innerHTML = '<b style="letter-spacing:.1em;color:#4cc3ff">ARES-X</b><span id="bootMsg">Cargando el motor Python en el navegador (Pyodide)…</span><small style="color:#7f93ad">numpy · scikit-learn · pandas — primera carga ~20–40 s</small>';
  document.body.appendChild(box);
  const say = t => {{ const m = document.getElementById('bootMsg'); if (m) m.textContent = t; }};
  const py = await loadPyodide({{ indexURL: '{PYODIDE}' }});
  say('Instalando numpy, scikit-learn y pandas…');
  await py.loadPackage(['numpy', 'scikit-learn', 'pandas']);
  say('Cargando módulos ARES-X y entrenando la RNA…');
  const files = await (await fetch('py/manifest.json')).json();
  py.FS.mkdirTree('/app/ares');
  for (const name of files) py.FS.writeFile('/app/ares/' + name, await (await fetch('py/ares/' + name)).text());
  await new Promise(r => setTimeout(r, 30));
  py.runPython("import sys; sys.path.insert(0, '/app'); from ares.api import Session, handle_json; SESSION = Session(event_rate=0.03)");
  const handle = py.globals.get('handle_json'), session = py.globals.get('SESSION');
  window.ARES_TRANSPORT = async (fn, args) => handle(session, fn, args);
  box.remove();
}})();
</script>
"""


def main():
    if (SITE / 'py').exists():
        shutil.rmtree(SITE / 'py')  # keep site/.vercel (project link)
    (SITE / 'py' / 'ares').mkdir(parents=True)
    page = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
    page = page.replace('<script>\n\'use strict\';', BOOT + '<script>\n\'use strict\';', 1)
    assert 'ARES_BOOT = (async' in page, 'boot script not injected'
    (SITE / 'index.html').write_text(page, encoding='utf-8')
    names = []
    for name in MODULES:
        shutil.copy(ROOT / 'src' / 'ares' / f'{name}.py', SITE / 'py' / 'ares' / f'{name}.py')
        names.append(f'{name}.py')
    (SITE / 'py' / 'manifest.json').write_text(json.dumps(names), encoding='utf-8')
    # Deployment config lives in the repository root vercel.json (outputDirectory: site).
    print('site/ generado:', len(names), 'módulos Python')


if __name__ == '__main__':
    main()
