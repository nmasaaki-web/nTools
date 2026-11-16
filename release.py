#!/usr/bin/env python3
"""Maintainer: python release.py 1.0.8 (outside Maya)."""
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parent
TOOLS=[
    dict(id='sketchfab',module='sketchfab_asset_browser',entry='show',label='Sketchfab Asset Browser',short='SF',version='1.2',icon='sketchfab.png',description='Search and import static glTF assets; OpenPBR'),
    dict(id='polyhaven',module='polyhaven_asset_browser',entry='show',label='PolyHaven Asset Browser',short='PH',version='5.2',icon='polyhaven.png',description='Poly Haven assets, HDRI, local library and OpenPBR'),
    dict(id='city',module='maya_city_builder',entry='show',label='Maya City Builder',short='CITY',version='2.4.1',icon='city.png',description='OSM, PLATEAU, Procedural and Procedural Japan city geometry'),
    dict(id='material',module='material_creator',entry='show',label='Material Creator',short='MAT',version='1.3',icon='material.png',description='Create OpenPBR materials from local textures or JSON'),
    dict(id='quadruped',module='quadruped_quick_rig',entry='show_ui',label='Quadruped Quick Rig',short='RIG',version='2.4.0',icon='quadruped.png',description='Four-legged guides, IK/FK and experimental retarget',opens_on_import=True),
]

def main(version):
    if not re.fullmatch(r'\d+\.\d+\.\d+',version):raise ValueError('Use x.y.z, e.g. 1.0.8')
    pkg=ROOT/'scripts'/'ntools'
    paths=[ROOT/'install.py',pkg/'__init__.py']+sorted((pkg/'tools').glob('*.py'))+sorted((pkg/'icons').glob('*.png'))
    for p in paths:
        if p.suffix=='.py':compile(p.read_bytes(),str(p),'exec')
    for t in TOOLS:
        if not (pkg/'tools'/(t['module']+'.py')).is_file() or not (pkg/'icons'/t['icon']).is_file():raise ValueError('Missing '+t['id'])
    m=dict(schema=1,package='nTools',version=version,tools=TOOLS,files={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (ROOT/'version.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Manifest generated:',version)

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: python release.py 1.0.8')
    main(sys.argv[1])
