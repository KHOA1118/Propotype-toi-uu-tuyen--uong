"""Validate deployment inputs and export optional static frontend assets."""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from deployment_config import api_base_url, allowed_origins

ROOT=Path(__file__).resolve().parents[1]

def build():
    api_base_url(); allowed_origins()
    fixture=json.loads((ROOT/'data/presentation_scenario.json').read_text(encoding='utf-8'))
    source=Path(os.getenv('MAP_DATA',str(ROOT/'data/raw/hcm_map4.osm')))
    if not source.is_file():raise ValueError('Missing raw OSM: include data/raw/hcm_map4.osm in the deployment')
    if hashlib.sha256(source.read_bytes()).hexdigest()!=fixture['source_sha256']:raise ValueError('OSM does not match fixed presentation scenario')
    for folder in ['lns','road_network']:
        for p in (ROOT/folder).glob('*.py'):ast.parse(p.read_text(encoding='utf-8-sig'))
    for name in ['server.py','deployment_config.py']:ast.parse((ROOT/name).read_text(encoding='utf-8-sig'))
    html=(ROOT/'frontend/index.html').read_text(encoding='utf-8')
    for asset in re.findall(r'(?:src|href)="/([^"#]+)"',html):
        if asset!='config.js' and not (ROOT/'frontend'/asset).is_file():raise ValueError('Missing asset: '+asset)
    output=ROOT/'dist';output.mkdir(exist_ok=True)
    for p in (ROOT/'frontend').iterdir():
        if p.is_file():shutil.copyfile(p,output/p.name)
    (output/'config.js').write_text('window.APP_CONFIG = '+json.dumps({'API_BASE_URL':api_base_url()})+';\n',encoding='utf-8')
    print('Build PASS: Python syntax, static assets, fixed map SHA256; dist/ created.')

if __name__=='__main__':build()
