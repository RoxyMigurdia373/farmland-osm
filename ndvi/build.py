from pathlib import Path
root = Path(__file__).parent
page = (root / 'page.html').read_text(encoding='utf-8')
core = (root / 'core.js').read_text(encoding='utf-8')
(root / 'ndvi_workbench.html').write_text(page.replace('/* CORE */', core), encoding='utf-8')
print('Built standalone ndvi_workbench.html')
