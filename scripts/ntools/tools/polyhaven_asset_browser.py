# -*- coding: utf-8 -*-
"""PolyHaven Asset Browser v5.4.8.
Paste into Maya Python Script Editor, or import polyhaven_asset_browser; call show().
Poly Haven public API, local library, OpenPBR and Arnold. No Fab UI.
"""
import os
import re
import json
import math
import shutil
import struct
import hashlib
import uuid
import traceback
from pathlib import Path
from collections import defaultdict, Counter

# The catalog/selection functions deliberately work outside Maya for testing.
try:
    import maya.cmds as cmds
    import maya.api.OpenMaya as om
    import maya.OpenMayaUI as omui
except ImportError:
    cmds = om = omui = None
try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import wrapInstance
except ImportError:
    try:
        from PySide2 import QtCore, QtGui, QtWidgets
        from shiboken2 import wrapInstance
    except ImportError:
        QtCore = QtGui = QtWidgets = wrapInstance = None

VERSION = '5.4.8'
MESH_EXT = {'.fbx', '.obj'}
IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.exr', '.tga', '.bmp', '.tx', '.hdr', '.webp'}
SKIP_DIRS = {'.git', '__pycache__', 'node_modules', 'maya_asset_browser', 'standins', 'sourceimages'}
# Practical first-pass warning thresholds, not Autodesk hard limits.
HEAVY_TRIANGLES = 500_000
VERY_HEAVY_TRIANGLES = 1_000_000
HEAVY_FBX_BYTES = 100 * 1024 * 1024
MAX_SPLIT_UNITS = 16

MAP_ALIASES = {
    'base': ('base_color','base_colour','basecolor','basecolour','albedo','diffuse','diff','color','colour'),
    'normal_gl': ('normal_opengl','normal_gl','normalgl','normalsgl','nor_gl','opengl_normal','normal','nrm','nor'),
    'normal_dx': ('normal_directx','normal_dx','normaldx','normalsdx','nor_dx','directx_normal'),
    'rough': ('specular_roughness','roughness','rough'),
    'metal': ('metallic','metalness','metal'),
    'disp': ('displacement','heightmap','height_map','height','disp'),
    'opacity': ('opacity','alpha_mask','alphamask','transparency','alpha','cutout'),
    'ao': ('ambient_occlusion','ambientocclusion','occlusion','ao'),
    'packed': ('occlusion_roughness_metallic','occlusionroughnessmetallic','orm','arm'),
    'ordp': ('occlusion_roughness_displacement','ordp'),
    'emission': ('emissive','emission','emit'),
    'translucency': ('translucency','transmission','translucent'),
    'gloss': ('glossiness','gloss'),
    'bump': ('bump','bumpmap'),
    'anisotropy': ('anisotropy_strength','anisotropic_strength','specular_anisotropy','anisotropy'),
    'anisotropy_rotation': ('anisotropy_rotation','anisotropic_rotation'),
    'ior': ('spec_ior','specular_ior','ior'),
    'rough_ao': ('rough_ao','roughness_ao'),
    'mask': ('mask',),
    'spec': ('specular','spec'),
}
ALIASES = sorted(((alias, key) for key, names in MAP_ALIASES.items() for alias in names), key=lambda v: -len(v[0]))
ROLE_RE = re.compile(r'(?<![a-z0-9])(' + '|'.join(re.escape(a) for a, k in ALIASES) + r')(?![a-z0-9])', re.I)
ALIAS_ROLE = dict(ALIASES)
LOD_RE = re.compile(r'(?<![a-z0-9])lod[_ -]*(\d+)(?!\d)', re.I)
TIER_RE = re.compile(r'(?<![a-z0-9])tier[_ -]*(\d+)(?!\d)', re.I)
RES_RE = re.compile(r'(?<![a-z0-9])(1|2|4|8|16)k(?![a-z0-9])', re.I)
PIX_RE = re.compile(r'(?<!\d)(1024|2048|4096|8192|16384)(?!\d)')
PREVIEW_RE = re.compile(r'(?<![a-z0-9])(preview|thumbnail|thumb|render|beauty)(?![a-z0-9])', re.I)
GENERIC_DIR = re.compile(r'^(textures?|maps?|images?|meshes?|models?|geometry|geo|fbx|obj|source|assets?|downloads?|previews?|thumbnails?|(?:tier|lod)[_ -]*\d+|(?:1|2|4|8|16)k|(?:1024|2048|4096|8192|16384)|high|medium|low)$', re.I)


def normalized(s):
    return re.sub(r'[^a-z0-9]+', '_', str(s).lower()).strip('_')


def clean_name(s):
    s = re.sub(r'[^A-Za-z0-9_]+', '_', str(s)).strip('_') or 'Asset'
    return ('A_' + s if s[0].isdigit() else s)[:90]


def strip_variant(s):
    s = LOD_RE.sub('', str(s)); s = TIER_RE.sub('', s)
    s = RES_RE.sub('', s); s = PIX_RE.sub('', s)
    return normalized(s)


def lod_of(path, root=None):
    parts = [path.stem] + list(reversed(path.relative_to(root).parts[:-1])) if root else [path.stem, path.parent.name]
    for part in parts:
        m = LOD_RE.search(part)
        if m: return ('LOD', int(m.group(1)))
    for part in parts:
        m = TIER_RE.search(part)
        if m: return ('Tier', int(m.group(1)))
    return ('Original', None)


def tier_of(path, root):
    for part in [path.stem] + list(reversed(path.relative_to(root).parts[:-1])):
        m = TIER_RE.search(part)
        if m: return int(m.group(1))
    return None


def mesh_family(path):
    return strip_variant(path.stem) or 'model'


def image_resolution(path, root=None):
    """Resolution from path or header; no full-size image allocation."""
    parts = [path.stem] + (list(reversed(path.relative_to(root).parts[:-1])) if root else [path.parent.name])
    for part in parts:
        m = RES_RE.search(part)
        if m: return int(m.group(1))
        m = PIX_RE.search(part)
        if m: return int(m.group(1)) // 1024
    try:
        with path.open('rb') as f:
            header = f.read(32)
            if header.startswith(b'\x89PNG\r\n\x1a\n') and len(header) >= 24:
                return max(1, round(max(struct.unpack('>II', header[16:24])) / 1024))
            if header[:4] == b'\x76\x2f\x31\x01':  # OpenEXR display/data window
                f.seek(8)
                def cstr():
                    data = bytearray()
                    while len(data) < 1024:
                        c = f.read(1)
                        if not c or c == b'\0': break
                        data.extend(c)
                    return bytes(data)
                for _ in range(256):
                    name = cstr()
                    if not name: break
                    typ = cstr(); raw = f.read(4)
                    if len(raw) != 4: break
                    size = struct.unpack('<I', raw)[0]
                    if size > 16 * 1024 * 1024: break
                    if name == b'dataWindow' and typ == b'box2i' and size == 16:
                        x0,y0,x1,y1 = struct.unpack('<iiii', f.read(16))
                        return max(1, round(max(x1-x0+1,y1-y0+1) / 1024))
                    f.seek(size, 1)
        if QtGui is not None:
            size = QtGui.QImageReader(str(path)).size()
            if size.isValid(): return max(1, round(max(size.width(), size.height()) / 1024))
    except (OSError, ValueError, struct.error):
        pass
    return None


# Some legacy Poly Haven assets ship colour variants instead of a _diff map.
# e.g. fabric_pattern_07_col_1_2k.jpg, _col_2, _col_03.
COLOR_VARIANT_RE = re.compile(r'(^|_)(?:col|color|colour|diff|diffuse|albedo|basecolor|base_color)(?:_?(\d+))?$', re.I)


def color_variant(path):
    stem = strip_variant(path.stem)
    m = COLOR_VARIANT_RE.search(stem)
    return (m, int(m.group(2)) if m and m.group(2) else None)


def base_variant_rank(path):
    # Prefer standard diffuse/albedo; otherwise col_1 is the primary/red
    # variant in Fabric Pattern 07. Keep all variants in one texture set.
    m, number = color_variant(path)
    if not m: return (0, 0)
    if number is None: return (1, 0) if m.group(0).strip('_') == 'col' else (0, 0)
    return (2, 0 if number == 1 else number + 1)


def classify(path, metadata_role=None):
    stripped = strip_variant(path.stem)
    variant, _ = color_variant(path)
    if variant:
        return 'base', stripped[:variant.start()].strip('_') or 'default'
    # Book Pattern's page image is a separate book-edge atlas, not a cover
    # base-colour variant. Do not create a second incomplete material set.
    if stripped == 'book_pattern_page':
        return 'page_color', 'book_pattern'
    # Match complete suffixes, longest first. ROLE_RE's final match alone
    # would mistake e.g. rough_ao for AO or anisotropy_rotation for rotation.
    for alias, role in ALIASES:
        if stripped == alias or stripped.endswith('_'+alias):
            return role, stripped[:-len(alias)].strip('_') or 'default'
    if metadata_role:
        return metadata_role, 'default'
    # Backwards compatibility for local Megascans filenames with a map
    # token before a nonstandard suffix. Poly Haven API roots use an explicit
    # role as well (see ph_plan); no guessing from arbitrary image contents.
    stem = normalized(path.stem)
    matches = list(ROLE_RE.finditer(stem))
    if matches:
        m = matches[-1]
        return ALIAS_ROLE[m.group(1).lower()], strip_variant(stem[:m.start()] + '_' + stem[m.end():]) or 'default'
    return None, None


def metadata_info(paths, asset_files):
    """Read common JSON descriptors without depending on a fixed Fab schema."""
    result = {'name': None, 'category': '', 'roles': {}, 'normal_dx': False}
    by_name = defaultdict(list)
    for p in asset_files: by_name[p.name.lower()].append(p)
    for path in sorted(paths):
        try:
            if path.stat().st_size > 8 * 1024 * 1024: continue
            data = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError, UnicodeError): continue
        if not isinstance(data, dict): continue
        for k in ('name','title','assetName','displayName'):
            if isinstance(data.get(k), str) and data[k].strip():
                result['name'] = result['name'] or data[k]; break
        for k in ('type','category','categories','tags','assetType','semanticTags'):
            if k in data: result['category'] += ' ' + str(data[k])[:2000]
        def visit(v, inherited=None):
            if isinstance(v, str) and inherited:
                filename=v.split('?')[0].replace('\\','/').split('/')[-1].lower()
                hits=by_name.get(filename, [])
                if len(hits)==1: result['roles'][hits[0]]=inherited
            elif isinstance(v, list):
                for item in v: visit(item, inherited)
            elif isinstance(v, dict):
                role = inherited
                for k in ('type','mapType','textureType','semantic','channel','name','componentType'):
                    x = v.get(k)
                    if isinstance(x, str):
                        key = normalized(x)
                        if key in ALIAS_ROLE: role = ALIAS_ROLE[key]; break
                if role == 'normal_gl' and any('directx' in str(v.get(k, '')).lower() for k in ('format','normalFormat','convention','space')):
                    role = 'normal_dx'
                if role:
                    for k in ('uri','path','file','filename','fileName','relativePath','url','name'):
                        value = v.get(k)
                        if not isinstance(value, str): continue
                        filename = value.split('?')[0].replace('\\','/').split('/')[-1].lower()
                        hits = by_name.get(filename, [])
                        if len(hits) == 1: result['roles'][hits[0]] = role
                for k, val in v.items():
                    visit(val, ALIAS_ROLE.get(normalized(k), role))
        visit(data)
    return result


class Texture:
    def __init__(self, path, root, role, key):
        self.path = path; self.role = role; self.key = key
        self.res = image_resolution(path, root); self.tier = tier_of(path, root)
        kind, level = lod_of(path,root); self.lod = level if kind=='LOD' else None


class Asset:
    def __init__(self, folder, files):
        self.folder = folder; self.files = sorted(set(files))
        self.meshes = [p for p in self.files if p.suffix.lower() in MESH_EXT]
        self.metadata = metadata_info([p for p in self.files if p.suffix.lower()=='.json'], self.files)
        self.name = self.metadata['name'] or folder.name
        ph_roles={}
        marker=folder/'native_asset_info.json'
        if marker.is_file():
            try:
                ph_info=json.loads(marker.read_text(encoding='utf-8'))
                if ph_info.get('source')=='Poly Haven' and ph_info.get('surface_schema')==2:
                    ph_roles=ph_info.get('map_roles',{})
            except (OSError, ValueError): pass
        self.textures = defaultdict(lambda: defaultdict(list))
        self.previews = []
        self.unknown = []
        for p in self.files:
            if p.suffix.lower() not in IMAGE_EXT: continue
            if PREVIEW_RE.search(normalized(p.stem)) or p.parent.name.lower() in ('preview','previews','thumbnail','thumbnails'):
                self.previews.append(p); continue
            role, key = classify(p, self.metadata['roles'].get(p))
            explicit=ph_roles.get(p.relative_to(folder).as_posix())
            if ph_roles and not explicit:
                continue
            if isinstance(explicit,list) and len(explicit)==2 and explicit[0] in set(MAP_ALIASES)|{'page_color'}:
                role,key=explicit
            if not role:
                self.unknown.append(p); continue
            if self.metadata['roles'].get(p) == 'normal_dx' and role == 'normal_gl': role='normal_dx'
            self.textures[key][role].append(Texture(p, folder, role, key))
        text = (self.name + ' ' + str(folder) + ' ' + self.metadata['category']).lower()
        plant_terms = r'(^|[^a-z])(plant|plants|vegetation|foliage|tree|trees|grass|fern|flower|shrub|leaf|leaves|bush)([^a-z]|$)'
        plant = bool(re.search(plant_terms, text)) or any(re.search(plant_terms,k) for k in self.textures)
        self.category = 'Plants' if self.meshes and plant else ('3D' if self.meshes else 'Surfaces')
        self.source = 'Megascans' if any(TIER_RE.search(str(p)) or LOD_RE.search(p.stem) for p in self.meshes) or any('megascans' in str(p).lower() or 'quixel' in str(p).lower() for p in [folder]) else ('Poly Haven' if any(re.search(r'_(diff|nor_gl|nor_dx|rough|arm)(_|$)', normalized(p.stem)) for p in self.files) else 'Local')

    def preview_path(self):
        if self.previews: return sorted(self.previews, key=lambda p: (p.suffix.lower() not in ('.jpg','.jpeg','.png'), len(p.name)))[0]
        candidates = [t for roles in self.textures.values() for t in roles.get('base', []) if t.path.suffix.lower() in ('.jpg','.jpeg','.png','.webp')]
        return min(candidates, key=lambda t: (t.res or 999, str(t.path))).path if candidates else None


def scan_library(root):
    root = Path(root).expanduser().resolve()
    if not root.is_dir(): raise ValueError('Folder does not exist: ' + str(root))
    paths = []
    for directory, dirs, files in os.walk(str(root), followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d.lower() not in SKIP_DIRS)
        for f in sorted(files):
            p = Path(directory) / f
            if p.suffix.lower() in MESH_EXT | IMAGE_EXT | {'.json'}: paths.append(p)
    def anchor(p):
        folder = p.parent
        while folder != root and GENERIC_DIR.match(folder.name): folder = folder.parent
        return folder
    anchors = {anchor(p) for p in paths if p.suffix.lower() in MESH_EXT}
    # JSON is an anchor only when accompanied by local images.
    image_anchors={anchor(p) for p in paths if p.suffix.lower() in IMAGE_EXT}
    for p in paths:
        if p.suffix.lower() == '.json':
            a = anchor(p)
            if a != root and a in image_anchors: anchors.add(a)
    groups = defaultdict(list)
    for p in paths:
        a = anchor(p)
        parents = [p.parent] + list(p.parent.parents)
        nearest = next((q for q in parents if q in anchors and (q == root or root in q.parents)), None)
        # Root-level models must not swallow unrelated asset subdirectories.
        if nearest == root and a != root: nearest = None
        groups[nearest or a].append(p)
    assets = []
    for folder, fs in sorted(groups.items(), key=lambda v: str(v[0]).lower()):
        a = Asset(folder, fs)
        if a.meshes or any('base' in roles or 'rough' in roles or 'normal_gl' in roles or 'packed' in roles or 'ordp' in roles for roles in a.textures.values()): assets.append(a)
    return sorted(assets, key=lambda a: (a.name.lower(), str(a.folder)))


def choose_mesh(asset, wanted_lod, family=None):
    if not asset.meshes: return None
    groups = defaultdict(list)
    for p in asset.meshes: groups[mesh_family(p)].append(p)
    if family not in groups:
        family = min(groups, key=lambda k: (not any(lod_of(p,asset.folder)[1]==wanted_lod for p in groups[k]), -len(groups[k]), len(k), k))
    def rank(p):
        typ, n = lod_of(p, asset.folder)
        return (0 if n == wanted_lod else 1 if n is not None else 2,
                abs(n-wanted_lod) if n is not None else 999,
                n is not None and n < wanted_lod,
                typ != 'LOD', p.suffix.lower() != '.fbx', str(p).lower())
    return min(groups[family], key=rank)


def pick_texture(options, resolution, tier=None, mesh_lod=None):
    def rank(t):
        r = t.res
        ext_rank = {'.exr':0,'.tif':1,'.tiff':1,'.png':2,'.tga':3,'.jpg':4,'.jpeg':4,'.tx':5}
        if t.role in ('base','emission','page_color'): ext_rank = {'.png':0,'.tif':1,'.tiff':1,'.jpg':2,'.jpeg':2,'.exr':3,'.tx':5}
        return (0 if t.lod == mesh_lod else 1 if t.lod is None else 2,
                0 if tier is not None and t.tier == tier else 1 if t.tier is None else 2,
                0 if r == resolution else 1 if r is not None else 2,
                abs(math.log2(r/resolution)) if r else 999,
                r is not None and r > resolution,
                abs(t.tier-tier) if tier is not None and t.tier is not None else 0,
                base_variant_rank(t.path) if t.role == 'base' else (0,0),
                ext_rank.get(t.path.suffix.lower(), 6), str(t.path).lower())
    return min(options, key=rank) if options else None


def texture_set(asset, key, resolution, tier=None, mesh_lod=None):
    roles = asset.textures[key]
    return {role: pick_texture(values, resolution, tier, mesh_lod) for role, values in roles.items() if values}


def match_set(keys, hints):
    """Return only a confident match; ambiguous assets require user mapping."""
    keys = list(keys)
    if len(keys) == 1: return keys[0]
    scores = {}
    for key in keys:
        kn = strip_variant(key)
        kt = set(kn.split('_')) - {'default','mat','material','mesh','sg','phong','lambert','standard','surface'}
        best = 0
        for hint in hints:
            hn = strip_variant(str(hint).split(':')[-1].split('|')[-1])
            ht = set(hn.split('_')) - {'mat','material','mesh','sg','phong','lambert','standard','surface'}
            if hn == kn and kn != 'default': score = 100
            elif len(kn) >= 4 and ('_'+kn+'_' in '_'+hn+'_' or (len(hn)>=4 and '_'+hn+'_' in '_'+kn+'_')): score = 60 + len(kt & ht)
            elif ht and ht <= kt and any(len(t)>=3 for t in ht): score=40+len(ht)
            else: score = 0
            best = max(best,score)
        scores[key] = best
    ordered = sorted(scores, key=lambda k: scores[k], reverse=True)
    if ordered and scores[ordered[0]] > 0 and (len(ordered)==1 or scores[ordered[0]] > scores[ordered[1]]): return ordered[0]
    return None

# ---------------- Maya / Arnold implementation ----------------
class UserCancelled(Exception): pass


def attr(node, name):
    return cmds.attributeQuery(name, node=node, exists=True)


def set_if(node, name, value):
    if attr(node, name):
        cmds.setAttr(node+'.'+name, value)
        return True
    return False


def plug(src, dst):
    cmds.connectAttr(src, dst, force=True)


def ensure_arnold():
    if not cmds.pluginInfo('mtoa', query=True, loaded=True): cmds.loadPlugin('mtoa', quiet=True)


def workspace_root():
    return Path(cmds.workspace(query=True, rootDirectory=True)).resolve()




def confirm_project_copy(owner, enabled=True):
    """No persistent preference; suppress only for this window and workspace."""
    if not enabled:
        return True
    root = str(workspace_root())
    if getattr(owner, '_confirmed_copy_root', None) == root:
        return True
    box = QtWidgets.QMessageBox(owner)
    box.setWindowTitle('Set Projectの確認')
    box.setIcon(QtWidgets.QMessageBox.Question)
    box.setText('Set Projectをしたフォルダにテクスチャをコピーします。Set Projectはしましたか？')
    box.setInformativeText('現在のプロジェクト：\n' + root + '\n\n「いいえ」で中止し、File → Set Projectを実行してください。')
    check = QtWidgets.QCheckBox('次のツール起動時まで表示しない', box)
    box.setCheckBox(check)
    box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
    box.button(QtWidgets.QMessageBox.Yes).setText('はい')
    box.button(QtWidgets.QMessageBox.No).setText('いいえ（中止）')
    box.setDefaultButton(QtWidgets.QMessageBox.No)
    box.setEscapeButton(QtWidgets.QMessageBox.No)
    result = box.exec() if hasattr(box, 'exec') else box.exec_()
    if result != QtWidgets.QMessageBox.Yes:
        return False
    if check.isChecked(): owner._confirmed_copy_root = root
    return True


def project_path(path):
    """Return a workspace-root-relative Maya path; reject outside paths."""
    return Path(path).resolve().relative_to(workspace_root()).as_posix()


def project_images():
    rule = Path(cmds.workspace(fileRuleEntry='sourceImages') or 'sourceimages')
    root = workspace_root()
    target = (rule if rule.is_absolute() else root/rule).resolve()
    try: target.relative_to(root)
    except ValueError: target = root/'sourceimages'
    return target


def file_digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def copy_project_image(source,relative):
    source=Path(source).resolve()
    if not source.is_file(): raise FileNotFoundError(str(source))
    dest=(project_images()/'AssetBrowser'/relative).resolve()
    # Resolve symlinks and reject accidental external write paths.
    project_path(dest)
    if source==dest: return project_path(dest)
    dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists() and file_digest(source)!=file_digest(dest):
        dest=dest.with_name(dest.stem+'_'+file_digest(source)[:16]+dest.suffix)
    if dest.exists():
        if file_digest(source)!=file_digest(dest): raise IOError('Destination content conflict: '+str(dest))
    else:
        tmp=dest.with_name('.'+dest.name+'.'+uuid.uuid4().hex+'.tmp')
        try: shutil.copy2(str(source),str(tmp)); os.replace(str(tmp),str(dest))
        finally:
            if tmp.exists(): tmp.unlink()
    return project_path(dest)


def asset_image_relative(path,asset):
    folder_id=hashlib.sha1(str(asset.folder).encode('utf-8')).hexdigest()[:9]
    return Path(clean_name(asset.name)+'_'+folder_id)/Path(path).resolve().relative_to(Path(asset.folder).resolve())


def texture_path(texture, asset, copy_files):
    p=texture.path
    if not copy_files: return p.resolve().as_posix()
    return copy_project_image(p,asset_image_relative(p,asset))


def resolve_file_texture(raw,asset=None,mesh=None):
    raw=os.path.expandvars(os.path.expanduser(raw)).replace('\\','/')
    p=Path(raw); root=workspace_root()
    candidates=[p] if p.is_absolute() else [root/p,project_images()/p]
    if asset is not None:
        if not p.is_absolute():
            candidates += [asset.folder/p]
            if mesh: candidates.insert(0,mesh.parent/p)
    for c in candidates:
        if c.is_file(): return c.resolve()
    if asset is not None:
        matches=[x for x in asset.files if x.name.casefold()==p.name.casefold() and x.is_file()]
        if len(matches)==1:return matches[0].resolve()
    raise FileNotFoundError(raw)


def localize_file_nodes(nodes,log,asset=None,mesh=None,strict=False):
    """Copy single-file Maya file textures, preserve color space and node connections.
    No mutation of referenced/locked nodes or UDIM/sequence patterns.
    """
    count=0; skipped=[]
    for n in sorted(set(nodes)):
        try:
            if not cmds.objExists(n):continue
            plugname=n+'.fileTextureName'; raw=cmds.getAttr(plugname) or ''
            if not raw:continue
            if (attr(n,'uvTilingMode') and cmds.getAttr(n+'.uvTilingMode')) or (attr(n,'useFrameExtension') and cmds.getAttr(n+'.useFrameExtension')) or re.search(r'<[^>]+>|%0?\d*d|#+',raw):
                raise ValueError('UDIM/sequence not automatically repathed')
            if cmds.referenceQuery(n,isNodeReferenced=True) or cmds.getAttr(plugname,lock=True) or cmds.connectionInfo(plugname,isDestination=True):
                raise ValueError('referenced, locked or driven path')
            src=resolve_file_texture(raw,asset,mesh)
            # Keep textures in the project sourceimages folder, including FBX originals.
            try:
                src.relative_to(project_images()); new=project_path(src)
            except ValueError:
                if asset is not None:
                    try: rel=asset_image_relative(src,asset)
                    except ValueError: rel=Path('ImportedTextures')/file_digest(src)[:16]/src.name
                else:
                    # Reuse an identical file already copied by an earlier OpenPBR import.
                    rel=None; digest=file_digest(src)
                    for candidate in (project_images()/'AssetBrowser').rglob(src.name):
                        try:
                            if candidate.is_file() and candidate.stat().st_size==src.stat().st_size and file_digest(candidate)==digest:
                                project_path(candidate); rel=candidate.resolve().relative_to((project_images()/'AssetBrowser').resolve()); break
                        except (OSError,ValueError):pass
                    if rel is None:rel=Path('ImportedTextures')/digest[:16]/src.name
                new=copy_project_image(src,rel)
            if raw.replace('\\','/')==new:continue
            color=cmds.getAttr(n+'.colorSpace') if attr(n,'colorSpace') else None
            ignore=cmds.getAttr(n+'.ignoreColorSpaceFileRules') if attr(n,'ignoreColorSpaceFileRules') else None
            if ignore is not None:set_if(n,'ignoreColorSpaceFileRules',True)
            try:
                cmds.setAttr(plugname,new,type='string')
                if color:cmds.setAttr(n+'.colorSpace',color,type='string')
            finally:
                if ignore is not None:set_if(n,'ignoreColorSpaceFileRules',ignore)
            count+=1; log('Project texture: '+n+' -> '+new)
        except Exception as e:
            msg=n+': '+str(e); skipped.append(msg); log('WARNING: '+msg)
    if strict and skipped: raise RuntimeError('Some imported texture paths could not be localized. See import log. '+skipped[0])
    return count,skipped


def repair_scene_textures(log=print):
    cmds.undoInfo(openChunk=True,chunkName='Asset Browser Repair Texture Paths')
    try:
        count,skipped=localize_file_nodes(cmds.ls(type='file',long=True) or [],log)
        log('Texture repair: %d updated; %d skipped. Save the scene after checking warnings.'%(count,len(skipped)))
        return count,skipped
    finally:cmds.undoInfo(closeChunk=True)


def choose_space(role, path):
    try: spaces=cmds.colorManagementPrefs(query=True,inputSpaceNames=True) or []
    except RuntimeError: spaces=[]
    if role not in ('base','emission','page_color'):
        candidates=['Raw','Utility - Raw','data','Utility - Data']
    elif path.lower().endswith(('.exr','.hdr')):
        candidates=['Linear Rec.709 (sRGB)','Utility - Linear - sRGB','Linear sRGB','Linear Rec.709','scene-linear Rec.709-sRGB','scene-linear Rec-709-sRGB','Raw']
    else:
        candidates=['sRGB','sRGB - Texture','Utility - sRGB - Texture','sRGB Texture']
    for c in candidates:
        for s in spaces:
            if s.lower()==c.lower(): return s
    for s in spaces:
        sl=s.lower()
        if role not in ('base','emission') and ('raw' in sl or sl=='data'): return s
        if role in ('base','emission','page_color') and 'srgb' in sl and 'texture' in sl and 'linear' not in sl and not path.lower().endswith(('.exr','.hdr')): return s
    return candidates[0]


def create_file(t, asset, prefix, placement, copy_files, log):
    path=texture_path(t,asset,copy_files)
    f=cmds.shadingNode('file',asTexture=True,isColorManaged=True,name=prefix+'_'+t.role+'_TEX')
    set_if(f,'ignoreColorSpaceFileRules',True)
    cmds.setAttr(f+'.fileTextureName',path,type='string')
    space=choose_space(t.role,path)
    try: cmds.setAttr(f+'.colorSpace',space,type='string')
    except RuntimeError: log('WARNING: color space not available: '+space+' / '+path)
    for a in ('coverage','translateFrame','rotateFrame','mirrorU','mirrorV','stagger','wrapU','wrapV','repeatUV','offset','rotateUV','noiseUV','vertexUvOne','vertexUvTwo','vertexUvThree','vertexCameraOne'):
        if attr(placement,a) and attr(f,a): plug(placement+'.'+a,f+'.'+a)
    plug(placement+'.outUV',f+'.uvCoord'); plug(placement+'.outUvFilterSize',f+'.uvFilterSize')
    return f



# nTools Plant SSS: new foliage is prepared with editable color controls, but
# Weight remains 0. Existing materials keep their artist-authored settings.
# This is based on material/asset metadata and texture names, not image analysis.
_FOLIAGE_WORDS = re.compile(
    r'(^|_)(leaf|leaves|foliage|grass|fern|petal|petals|flower|flowers|needles|needle)(_|$)', re.I)
_WOODY_WORDS = re.compile(
    r'(^|_)(bark|trunk|branch|branches|wood|stem|stems)(_|$)', re.I)
_PLANT_CATEGORY_WORDS = re.compile(
    r'(^|_)(plant|plants|vegetation|tree|trees|shrub|shrubs|bush|bushes)(_|$)', re.I)


def is_plant_sss_target(material_key, category='', has_opacity=False):
    """Conservative metadata/name-based foliage classification.

    ``twig`` and ``atlas`` are only classified when an opacity mask is present
    and the asset belongs to the Plants category. Never classify woody names.
    """
    key = normalized(material_key)
    cat = normalized(category)
    if _WOODY_WORDS.search(key):
        return False
    if _FOLIAGE_WORDS.search(key):
        return True
    return bool(has_opacity and _PLANT_CATEGORY_WORDS.search(cat)
                and (re.search(r'(^|_)(twig|twigs|atlas)(_|$)', key)
                     or not key or key in ('default', 'material')))


def setup_plant_sss_color(mat, diffuse_output_plug, log=None, reset_weight=True):
    """Add Diffuse -> aiColorCorrect -> OpenPBR Subsurface Color safely.

    The new network is intentionally visually inactive (SSS Weight 0). The
    Multiply/Saturation controls remain editable in Hypershade. In an existing
    scene reset_weight=False preserves Weight, Thin Walled and all other user
    attributes. Existing SSS input connections are never overwritten.
    """
    if log is None:
        log = print
    if not cmds or not mat or not diffuse_output_plug:
        return False
    try:
        if not cmds.objExists(mat) or not cmds.objExists(diffuse_output_plug):
            log('[Plant SSS] Skipped missing material or Diffuse source: ' + str(mat))
            return False
        if not attr(mat, 'subsurfaceColor'):
            log('[Plant SSS] Skipped: OpenPBR subsurfaceColor not found on ' + mat)
            return False
        if cmds.listConnections(mat+'.subsurfaceColor', source=True,
                                destination=False, plugs=True):
            log('[Plant SSS] Skipped existing SSS network: ' + mat)
            return False
    except Exception as e:
        log('[Plant SSS] Cannot check '+str(mat)+': '+str(e))
        return False
    cc = None
    try:
        # Other Arnold utilities in this importer require mtoa too.
        try:
            if not cmds.pluginInfo('mtoa', query=True, loaded=True):
                cmds.loadPlugin('mtoa', quiet=True)
        except Exception:
            pass
        cc = cmds.shadingNode('aiColorCorrect', asUtility=True,
                              name=mat+'_SSS_ColorAdjust')
        in_plug = next((a for a in ('input','inputColor','inColor') if attr(cc,a)), None)
        out_plug = next((a for a in ('outColor','outValue') if attr(cc,a)), None)
        if not in_plug or not out_plug or not attr(cc,'multiply') or not attr(cc,'saturation'):
            raise RuntimeError('aiColorCorrect lacks expected color/multiply/saturation attributes')
        # Wire the SAME color source to Base Color and SSS so the original
        # Base Color connection, color-space rules and UVs remain unchanged.
        plug(diffuse_output_plug, cc+'.'+in_plug)
        cmds.setAttr(cc+'.saturation', 1.0)
        value_type = cmds.getAttr(cc+'.multiply', type=True)
        if value_type in ('float3','double3'):
            cmds.setAttr(cc+'.multiply',1.0,1.0,1.0,type=value_type)
        elif value_type in ('float','double'):
            cmds.setAttr(cc+'.multiply',1.0)
        else:
            raise RuntimeError('Unexpected aiColorCorrect.multiply type: '+str(value_type))
        # Never force a new connection over an artist's existing network.
        cmds.connectAttr(cc+'.'+out_plug, mat+'.subsurfaceColor', force=False)
        if reset_weight and attr(mat,'subsurfaceWeight'):
            if not cmds.listConnections(mat+'.subsurfaceWeight',source=True,
                                        destination=False,plugs=True):
                cmds.setAttr(mat+'.subsurfaceWeight',0.0)
        log('[Plant SSS] '+mat+': Diffuse -> '+cc+
            ' (Multiply 1 / Saturation 1) -> Subsurface Color; Weight '+
            ('0 for new import' if reset_weight else 'preserved'))
        return True
    except Exception as e:
        if cc and cmds.objExists(cc):
            try: cmds.delete(cc)
            except Exception: pass
        log('[Plant SSS] Skipped '+mat+': '+str(e))
        return False


def add_plant_sss_to_scene_materials(log=None):
    """Opt-in retrofit: add missing SSS network, never change Weight/Thin Walled."""
    if log is None: log=print
    changed=skipped=0
    mats = cmds.ls(type='openPBRSurface') or []
    cmds.undoInfo(openChunk=True, chunkName='nTools Plant SSS Setup')
    try:
        for mat in mats:
            key = normalized(mat)
            try:
                opacity = bool(cmds.listConnections(mat+'.geometryOpacity',
                               source=True,destination=False,plugs=True)) if attr(mat,'geometryOpacity') else False
                # Already assigned twig textures can have alpha masks. Restrict
                # these patterns to avoid applying SSS to wooden materials.
                foliage = bool(_FOLIAGE_WORDS.search(key)) and not _WOODY_WORDS.search(key)
                if not foliage and opacity and not _WOODY_WORDS.search(key):
                    foliage = bool(re.search(r'(^|_)(twig|twigs)(_|$)',key))
                if not foliage:
                    continue
                source = cmds.listConnections(mat+'.baseColor',source=True,
                                              destination=False,plugs=True) or []
                if not source:
                    skipped+=1
                    continue
                if setup_plant_sss_color(mat, source[0], log, reset_weight=False):
                    changed+=1
                else:
                    skipped+=1
            except Exception as e:
                skipped+=1
                log('[Plant SSS] Retrofit skipped '+mat+': '+str(e))
    finally:
        cmds.undoInfo(closeChunk=True)
    return changed,skipped

def build_material(asset,key,settings,tier,mesh_lod,log):
    maps=texture_set(asset,key,settings['resolution'],tier,mesh_lod)
    prefix=clean_name(asset.name+'_'+key)[:80]
    mat=cmds.shadingNode('openPBRSurface',asShader=True,name=prefix+'_OpenPBR')
    sg=cmds.sets(renderable=True,noSurfaceShader=True,empty=True,name=mat+'_SG')
    plug(mat+'.outColor',sg+'.surfaceShader')
    placement=cmds.shadingNode('place2dTexture',asUtility=True,name=prefix+'_UV')
    files={}
    def tex(role):
        if role not in maps: return None
        if role not in files:
            t=maps[role]
            files[role]=create_file(t,asset,prefix,placement,settings['copy'],log)
            log('  '+role+' : '+str(t.path.relative_to(asset.folder))+' ['+(str(t.res)+'K' if t.res else 'unknown resolution')+']')
            if t.res is not None and t.res!=settings['resolution']: log('    -> requested resolution not present; using '+str(t.res)+'K')
            if tier is not None and t.tier is not None and t.tier!=tier: log('    WARNING: texture from a different Tier; check UV compatibility.')
            if mesh_lod is not None and t.lod is not None and t.lod!=mesh_lod: log('    WARNING: texture from a different LOD; check UV compatibility.')
        return files[role]
    if tex('base'): plug(files['base']+'.outColor',mat+'.baseColor')
    else: log('  WARNING: No Base Color found in texture set '+key)
    packed=tex('packed') if ('rough' not in maps or 'metal' not in maps) else None
    if tex('rough'): plug(files['rough']+'.outColorR',mat+'.specularRoughness')
    elif tex('gloss'):
        rev=cmds.shadingNode('reverse',asUtility=True,name=prefix+'_GlossToRough')
        plug(files['gloss']+'.outColorR',rev+'.inputX'); plug(rev+'.outputX',mat+'.specularRoughness')
    elif packed: plug(packed+'.outColorG',mat+'.specularRoughness')
    elif tex('ordp'): plug(files['ordp']+'.outColorG',mat+'.specularRoughness')
    if tex('metal'): plug(files['metal']+'.outColorR',mat+'.baseMetalness')
    elif packed: plug(packed+'.outColorB',mat+'.baseMetalness')
    else: set_if(mat,'baseMetalness',0.0)
    if 'anisotropy' in maps:
        if attr(mat,'specularRoughnessAnisotropy'):
            f=tex('anisotropy'); plug(f+'.outColorR',mat+'.specularRoughnessAnisotropy')
        else: log('  WARNING: OpenPBR anisotropy input unavailable in this Maya version.')
    if 'ior' in maps:
        # IOR is an absolute index (normally >1), not specular weight.
        # Preserve HDR values in EXR. Never assume a normalized LDR image
        # encodes physical IOR. Guard samples below 1 with the default 1.5.
        if attr(mat,'specularIOR') and maps['ior'].path.suffix.lower()=='.exr':
            f=tex('ior'); c=cmds.shadingNode('condition',asUtility=True,name=prefix+'_IORGuard')
            cmds.setAttr(c+'.operation',3)  # >=
            plug(f+'.outColorR',c+'.firstTerm'); cmds.setAttr(c+'.secondTerm',1.0)
            plug(f+'.outColorR',c+'.colorIfTrueR'); cmds.setAttr(c+'.colorIfFalseR',1.5)
            plug(c+'.outColorR',mat+'.specularIOR')
            log('    IOR: EXR absolute values; samples below 1 use 1.5 (check source encoding).')
        else: log('  NOTE: IOR needs an absolute-value EXR and a supported OpenPBR input; using shader default.')
    if 'anisotropy_rotation' in maps:
        log('  NOTE: Anisotropy rotation downloaded but not wired: OpenPBR needs a tangent-vector conversion, not a scalar angle.')
    if 'page_color' in maps:
        # The page photograph uses different UVs from the cloth cover.
        # Expose a separate material, without assigning it over the cover.
        page=cmds.shadingNode('openPBRSurface',asShader=True,name=prefix+'_Pages_OpenPBR')
        page_sg=cmds.sets(renderable=True,noSurfaceShader=True,empty=True,name=page+'_SG')
        plug(page+'.outColor',page_sg+'.surfaceShader')
        page_uv=cmds.shadingNode('place2dTexture',asUtility=True,name=prefix+'_Pages_UV')
        page_file=create_file(maps['page_color'],asset,prefix+'_Pages',page_uv,settings['copy'],log)
        plug(page_file+'.outColor',page+'.baseColor')
        set_if(page,'baseMetalness',0.0); set_if(page,'specularRoughness',0.7)
        log('  Book page atlas: separate material '+page+' (not auto-assigned; adjust page UVs).')
    if 'rough_ao' in maps and 'rough' not in maps:
        log('  NOTE: rough_ao contains baked AO; not substituted for physical roughness.')
    if 'spec' in maps or 'mask' in maps:
        log('  NOTE: Additional spec/mask map detected; not auto-wired because its meaning depends on the source material.')
    normal_role='normal_dx' if settings['normal']=='DirectX' and 'normal_dx' in maps else ('normal_gl' if 'normal_gl' in maps else ('normal_dx' if 'normal_dx' in maps else None))
    if normal_role:
        f=tex(normal_role); n=cmds.shadingNode('aiNormalMap',asUtility=True,name=prefix+'_Normal')
        dx=normal_role=='normal_dx'
        if settings['normal']=='DirectX': dx=True
        elif settings['normal']=='OpenGL': dx=False
        if attr(n,'invertY'):
            plug(f+'.outColor',n+'.input'); cmds.setAttr(n+'.invertY',dx)
        elif dx:
            # Explicit green-channel inversion if a future MtoA changes the switch.
            rev=cmds.shadingNode('reverse',asUtility=True,name=prefix+'_FlipNormalY')
            plug(f+'.outColorR',n+'.inputR'); plug(f+'.outColorB',n+'.inputB')
            plug(f+'.outColorG',rev+'.inputX'); plug(rev+'.outputX',n+'.inputG')
        else: plug(f+'.outColor',n+'.input')
        plug(n+'.outValue',mat+'.normalCamera')
        log('    Normal convention: '+('DirectX (Y flipped)' if dx else 'OpenGL'))
    elif tex('bump'):
        b=cmds.shadingNode('bump2d',asUtility=True,name=prefix+'_Bump')
        set_if(b,'bumpInterp',0); set_if(b,'bumpDepth',0.1)
        plug(files['bump']+'.outColorR',b+'.bumpValue'); plug(b+'.outNormal',mat+'.normalCamera')
    opacity=bool(tex('opacity'))
    if opacity:
        # Standalone opacity maps are usually grayscale in RGB, not in alpha.
        plug(files['opacity']+'.outColorR',mat+'.geometryOpacity')
    # Keep existing thin-walled vegetation behavior; exclude woody components.
    foliage = is_plant_sss_target(key, asset.category, opacity)
    thin = foliage or (asset.category=='Plants' and opacity and not _WOODY_WORDS.search(normalized(key)))
    if thin: set_if(mat,'geometryThinWalled',True)
    # New imports: prepare color correction, but keep SSS Weight OFF by default.
    # Non-foliage (bark/trunk/wood, stone, ground, etc.) is unchanged.
    if foliage and 'base' in files:
        setup_plant_sss_color(mat, files['base']+'.outColor', log, reset_weight=True)
    if tex('emission'):
        plug(files['emission']+'.outColor',mat+'.emissionColor'); set_if(mat,'emissionLuminance',1.0)
    if 'translucency' in maps:
        log('  NOTE: Translucency detected; not auto-wired (varies by asset and leaf shading model).')
    if 'ao' in maps or 'packed' in maps or 'ordp' in maps:
        log('  NOTE: AO not multiplied into Base Color (avoid double darkening in Arnold).')
    displaced=False
    if settings['displacement']:
        disp_file=tex('disp')
        disp_plug=disp_file+'.outColorR' if disp_file else None
        if not disp_plug and tex('ordp'): disp_plug=files['ordp']+'.outColorB'
        if disp_plug:
            height=cmds.shadingNode('plusMinusAverage',asUtility=True,name=prefix+'_HeightCenter')
            cmds.setAttr(height+'.operation',2)
            plug(disp_plug,height+'.input1D[0]')
            cmds.setAttr(height+'.input1D[1]',settings['mid'])
            scale=cmds.shadingNode('multiplyDivide',asUtility=True,name=prefix+'_HeightScale')
            plug(height+'.output1D',scale+'.input1X'); cmds.setAttr(scale+'.input2X',settings['height'])
            dis=cmds.shadingNode('displacementShader',asShader=True,name=prefix+'_Displacement')
            plug(scale+'.outputX',dis+'.displacement'); plug(dis+'.displacement',sg+'.displacementShader')
            displaced=True
        else: log('  WARNING: Displacement enabled, but no height map or ORDp found.')
    return {'mat':mat,'sg':sg,'opacity':opacity,'displaced':displaced,'foliage':foliage}


def mesh_faces(shape):
    sel=om.MSelectionList(); sel.add(shape); dag=sel.getDagPath(0)
    fn=om.MFnMesh(dag); engines, indices=fn.getConnectedShaders(dag.instanceNumber())
    names=[om.MFnDependencyNode(obj).name() for obj in engines]
    groups=defaultdict(list)
    for i,idx in enumerate(indices): groups[names[idx] if 0<=idx<len(names) else ''].append(i)
    if not groups: groups['']=list(range(fn.numPolygons))
    return groups,fn.numPolygons


def components(shape, faces, total):
    if len(faces)==total: return [shape]
    if not faces: return []
    result=[]; start=prev=faces[0]
    for n in faces[1:]+[None]:
        if n is not None and n==prev+1: prev=n; continue
        result.append(shape+'.f['+str(start)+(':'+str(prev) if prev!=start else '')+']')
        if n is not None: start=prev=n
    return result


def safe_auto_material_key(keys, hints):
    """Return a uniquely supported texture-set match, never guess by SG index.

    Maya FBX can generate synthetic SG names (e.g. fir_tree_01_a_LOD0SG1).
    Numbers or the mesh tree-variant suffix are NOT trustworthy material IDs.
    """
    return match_set(keys, hints)


def mapping_summary(settings, log, parent=None):
    """Report unresolved bindings once, rather than asking students many times."""
    unresolved=settings.get('_unresolved_materials', [])
    if not unresolved:return
    unique=list(dict.fromkeys((sg,shape) for sg,shape in unresolved))
    log('WARNING: %d material assignment(s) could not be identified reliably.'%len(unique))
    log('FBX materials were preserved, NOT verified against the Poly Haven thumbnail.')
    log('If needles look opaque or bark looks wrong, check texture connections and alpha maps.')
    if QtWidgets is not None and parent is not None:
        box=QtWidgets.QMessageBox(parent)
        box.setWindowTitle('マテリアルの確認が必要です')
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setText('%d件のマテリアルを自動判定できませんでした。'%len(unique))
        box.setInformativeText('元のFBXマテリアルは維持していますが、サムネイルと同じ見た目は保証されません。\n'
                               '誤ったテクスチャを自動割り当てしないため、推測での置き換えは行いません。\n\n'
                               '特に木の葉の透過（alpha）と幹の質感をご確認ください。\n'
                               '必要な場合は「Advanced: Ask for ambiguous materials」を有効にして取り込み直してください。\n'
                               '詳細なノード名は下部のログに表示されています。')
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        box.exec() if hasattr(box,'exec') else box.exec_()


def fir_tree_01_standin_suggestions(asset, unresolved, keys):
    """Suggest (never silently apply) the three Fir Tree 01 trunk material sets.

    This rule only covers the *specific* Poly Haven Fir Tree 01 layout:
    fir_tree_01_{a,b,c}_LOD*Shape / fir_tree_01_{a,b,c}_LOD*SG*.
    A matching variant letter is useful evidence, not proof of shader identity.
    Other models and uncertain/duplicate bindings are never guessed.
    """
    if re.sub(r'[^a-z0-9]+', '_', str(asset.name).lower()).strip('_') != 'fir_tree_01':
        return []
    if not unresolved or len(unresolved)>3:return []
    keys=set(keys)
    result=[]; used=set()
    for sg,shape,faces,total in unresolved:
        leaf=str(shape).split('|')[-1].split(':')[-1].lower()
        shader=str(sg).split('|')[-1].split(':')[-1].lower()
        shape_m=re.fullmatch(r'fir_tree_01_([abc])_lod\d+shape',leaf)
        shader_m=re.fullmatch(r'fir_tree_01_([abc])_lod\d+sg\d*',shader)
        if not shape_m or not shader_m or shape_m.group(1)!=shader_m.group(1):return []
        key='fir_tree_01_trunk_'+shape_m.group(1)
        if key not in keys or key in used:return []
        used.add(key);result.append((shape,faces,total,key))
    return result


def unresolved_standin_decision(parent,asset,unresolved,suggestions):
    """Explicit confirmation: do not silently override the user's Stand-in choice.

    'suggested': user accepts an asset-specific *unverified* material inference
    'original': preserve unresolved FBX shaders and still export ASS
    'editable': keep the imported editable mesh, without writing an ASS
    'cancel': undo the import transaction
    """
    if QtWidgets is None:return 'editable'
    box=QtWidgets.QMessageBox(parent)
    box.setIcon(QtWidgets.QMessageBox.Warning)
    box.setWindowTitle('ASS書き出し前のマテリアル確認')
    box.setText('Stand-inを選択しましたが、%d件のマテリアルを自動判定できません。'%len(unresolved))
    detail=('このままASSを書き出すと、元のFBXシェーダーが正しくレンダリングされない可能性があります。\n'
            'ASS書き出し後はマテリアルの修正が難しくなります。\n\n')
    guessed=None
    if suggestions and len(suggestions)==len(unresolved):
        detail+='ファイル名から推定した候補（確定情報ではありません）:\n'
        detail+='\n'.join('  '+str(shape).split('|')[-1]+' → '+key for shape,_,_,key in suggestions)
        detail+='\n\n候補の採用後もArnoldレンダリングで見た目をご確認ください。\n\n'
        guessed=box.addButton('推定素材を適用してASS化',QtWidgets.QMessageBox.AcceptRole)
    detail+='「現状のままASS化」は未確定マテリアルを残します。外観は保証されません。'
    box.setInformativeText(detail)
    original=box.addButton('現状のままASS化（外観未確認）',QtWidgets.QMessageBox.ActionRole)
    editable=box.addButton('編集可能メッシュで保持',QtWidgets.QMessageBox.ActionRole)
    cancel=box.addButton('取り込みをキャンセル',QtWidgets.QMessageBox.RejectRole)
    box.setDefaultButton(editable)
    box.exec() if hasattr(box,'exec') else box.exec_()
    clicked=box.clickedButton()
    if guessed is not None and clicked is guessed:return 'suggested'
    if clicked is original:return 'original'
    if clicked is editable:return 'editable'
    return 'cancel'


def shader_hints(sg,shape):
    hints=[shape,sg]
    if sg and cmds.objExists(sg):
        shaders=cmds.listConnections(sg+'.surfaceShader',source=True,destination=False) or []
        hints+=shaders
        for s in shaders:
            for f in cmds.ls(cmds.listHistory(s,pruneDagObjects=True) or [],type='file') or []:
                try:
                    p=Path(cmds.getAttr(f+'.fileTextureName') or '')
                    role,key=classify(p)
                    if key: hints.append(key)
                    hints.append(p.stem)
                except RuntimeError: pass
    return hints


def setup_shape(shape,material,settings):
    if material['opacity']: set_if(shape,'aiOpaque',False)
    if material['displaced']:
        if attr(shape,'aiSubdivType'):
            choices=cmds.attributeQuery('aiSubdivType',node=shape,listEnum=True) or []
            names=choices[0].split(':') if choices else []
            # Linear subdivision preserves the scanned silhouette and UVs better.
            index=next((i for i,v in enumerate(names) if 'linear' in v.lower()),None)
            if index is not None: cmds.setAttr(shape+'.aiSubdivType',index)
            else: cmds.setAttr(shape+'.aiSubdivType',1)
        set_if(shape,'aiSubdivIterations',settings['subdiv'])
        set_if(shape,'aiDispPadding',max(abs(settings['height']),0.01))
        set_if(shape,'aiDispHeight',1.0); set_if(shape,'aiDispZeroValue',0.0)


def import_mesh(path,root):
    suffix=path.suffix.lower()
    if suffix=='.fbx' and not cmds.pluginInfo('fbxmaya',query=True,loaded=True): cmds.loadPlugin('fbxmaya',quiet=True)
    ns='AB_'+uuid.uuid4().hex[:10]
    before=set(cmds.ls(type='mesh',long=True) or [])
    kwargs=dict(i=True,namespace=ns,mergeNamespacesOnClash=False,returnNewNodes=True,ignoreVersion=True)
    if suffix=='.fbx': kwargs['type']='FBX'
    elif suffix=='.obj': kwargs['type']='OBJ'
    try: nodes=cmds.file(path.as_posix(),**kwargs) or []
    except RuntimeError:
        if suffix!='.obj': raise
        # OBJ importer is built in on many versions; do not retry a partial import.
        if set(cmds.ls(type='mesh',long=True) or [])-before: raise
        cmds.loadPlugin('objExport',quiet=True)
        nodes=cmds.file(path.as_posix(),**kwargs) or []
    all_new=set(cmds.ls(type='mesh',long=True) or [])-before
    new_meshes=sorted(p for p in all_new if not cmds.getAttr(p+'.intermediateObject'))
    if not new_meshes: raise RuntimeError('No polygon mesh was imported: '+str(path))
    top=sorted({p.split('|')[1] for p in new_meshes})
    root_long=(cmds.ls(root,long=True) or [root])[0]
    for node in top:
        p='|'+node
        if p==root_long: continue
        cmds.parent(p,root_long,absolute=True)
    return [s for s in (cmds.listRelatives(root_long,allDescendents=True,type='mesh',fullPath=True) or []) if not cmds.getAttr(s+'.intermediateObject')]


def _safe_polycount(value):
    try:
        value = int(value)
        return value if 0 < value < 2_000_000_000 else None
    except (ValueError, TypeError, OverflowError):
        return None


def heavy_asset_hint(asset=None, mesh=None, catalog_meta=None):
    """Conservative *pre-import* hint; never treat texture/package MB as geometry MB.

    Official Poly Haven polycount is a high-detail asset-wide statistic; the
    selected FBX LOD may contain far fewer triangles.
    """
    meta = catalog_meta if isinstance(catalog_meta, dict) else {}
    tris = _safe_polycount(meta.get('polycount'))
    if tris is None and asset is not None:
        marker = Path(asset.folder) / 'native_asset_info.json'
        if marker.is_file():
            try:
                info = json.loads(marker.read_text(encoding='utf-8'))
                tris = _safe_polycount(info.get('polycount'))
            except (OSError, ValueError, UnicodeError):
                pass
    mesh_bytes = None
    if mesh is not None:
        try:
            if Path(mesh).is_file():mesh_bytes = Path(mesh).stat().st_size
        except OSError:pass
    reason=[]
    if tris is not None and tris >= HEAVY_TRIANGLES:
        reason.append('Poly Haven掲載値: 約%s万三角形（選択したLODの実測値とは限りません）' % ('%.1f' % (tris/10000)))
    if mesh_bytes is not None and mesh_bytes >= HEAVY_FBX_BYTES:
        reason.append('選択FBX/OBJ: %.1f MiB（テクスチャを含まないファイル容量）' % (mesh_bytes/1024**2))
    return {'warn':bool(reason),'reason':reason,'triangles':tris,'mesh_bytes':mesh_bytes}


def imported_triangles(shapes):
    """Count triangles AFTER geometry import only when no early warning was possible."""
    total=0
    for shape in shapes:
        try:total+=int(cmds.polyEvaluate(shape,triangle=True) or 0)
        except (RuntimeError,ValueError,TypeError):continue
    return total


def _mesh_shapes(node):
    return [s for s in (cmds.listRelatives(node,allDescendents=True,type='mesh',fullPath=True) or [])
            if not cmds.getAttr(s+'.intermediateObject')]


def _child_transforms(node):
    return cmds.listRelatives(node,children=True,type='transform',fullPath=True) or []


def _bbox(node):
    values=cmds.exactWorldBoundingBox(node)
    if len(values)!=6 or not all(math.isfinite(float(v)) for v in values):
        raise ValueError('Invalid bounding box: '+node)
    return tuple(float(x) for x in values)


def _footprint_overlap(a,b):
    """Fraction of the smaller horizontal bbox covered by the other bbox."""
    x=max(0.,min(a[3],b[3])-max(a[0],b[0]))
    z=max(0.,min(a[5],b[5])-max(a[2],b[2]))
    aa=max(1e-6,(a[3]-a[0])*(a[5]-a[2]))
    bb=max(1e-6,(b[3]-b[0])*(b[5]-b[2]))
    return (x*z)/min(aa,bb)


def standin_units(root,log):
    """Identify independent top-level model groups; never split by mesh/material.

    Avoid separating trunks from leaves when an FBX contains overlapping
    subgroups. A flattened / combined mesh is deliberately not auto-separated.
    """
    parent=root
    for _ in range(24):
        children=[c for c in _child_transforms(parent) if _mesh_shapes(c)]
        if len(children)!=1:break
        # Only walk through a wrapper when it has no own mesh shapes.
        direct=cmds.listRelatives(parent,children=True,type='mesh',fullPath=True) or []
        if any(not cmds.getAttr(s+'.intermediateObject') for s in direct):break
        parent=children[0]
    children=[c for c in _child_transforms(parent) if _mesh_shapes(c)]
    own=cmds.listRelatives(parent,children=True,type='mesh',fullPath=True) or []
    if any(not cmds.getAttr(s+'.intermediateObject') for s in own):
        log('ASS: direct mesh at common root; one archive is safer than splitting material parts.')
        return [root]
    if not 2 <= len(children) <= MAX_SPLIT_UNITS:return [root]
    boxes=[]
    try:
        for child in children:boxes.append(_bbox(child))
    except (ValueError,RuntimeError):return [root]
    for i,aa in enumerate(boxes):
        for bb in boxes[i+1:]:
            # Overlapping branches/leaves are typically *parts* of one tree.
            if _footprint_overlap(aa,bb) > .25:
                log('ASS: overlapping FBX groups; refusing uncertain tree/branch split.')
                return [root]
    log('ASS: %d spatially separate model groups recognized.' % len(children))
    return children


def _export_ass_file(selection,dest):
    cmds.select(selection,replace=True)
    cmds.arnoldExportAss(filename=dest.as_posix(),selected=True,mask=24,lightLinks=0,shadowLinks=0)
    if not dest.is_file() or dest.stat().st_size == 0:
        raise RuntimeError('ASS export failed: '+str(dest))


def export_standin(root,asset,log,split_mode='auto',materials=None):
    """Export scene groups as independent ASS files, safely retaining source on failure.

    Temporary translation moves each part's bbox bottom-center to world zero
    for export; the proxy is placed back at that original pivot. Individual
    Stand-ins can then be transformed or instanced independently.
    """
    if split_mode not in ('auto','single'):raise ValueError('Invalid stand-in split mode.')
    units=standin_units(root,log) if split_mode=='auto' else [root]
    folder=workspace_root()/'data'/'AssetBrowser'/'standins';folder.mkdir(parents=True,exist_ok=True)
    proxies=[];exports=[]; old_sel=cmds.ls(selection=True,long=True) or []
    # Enable non-destructive per-Stand-in look adjustments in NEW archives only.
    # This must run before exporting shaders to ASS; existing archives stay intact.
    look_profile={'schema':1,'producer':'nTools/PolyHaven','controls':[]}
    _look=None
    try:
        from ntools.tools import standin_look_controller as _look
        look_profile=_look.prepare_export_materials(materials or {},log)
    except Exception as exc:
        # Look controls are optional; they must never block ASS export.
        log('WARNING: Stand-in Look Controller was not prepared: '+str(exc))
        _look=None
    try:
        for index,unit in enumerate(units,1):
            # Preserve existing world transform and return it even on export error.
            matrix=cmds.xform(unit,query=True,worldSpace=True,matrix=True)
            bbox=_bbox(unit)
            pivot=((bbox[0]+bbox[3])*.5,bbox[1],(bbox[2]+bbox[5])*.5)
            position=cmds.xform(unit,query=True,worldSpace=True,translation=True)
            dest=folder/(clean_name(asset.name)+'_%02d_'%index+uuid.uuid4().hex[:8]+'.ass')
            try:
                cmds.xform(unit,worldSpace=True,translation=[position[i]-pivot[i] for i in range(3)])
                _export_ass_file(unit,dest)
                exports.append(dest)
            except Exception:
                if dest.exists():
                    try:dest.unlink()
                    except OSError:pass
                raise
            finally:
                cmds.xform(unit,worldSpace=True,matrix=matrix)
            proxy=cmds.createNode('transform',name=clean_name(asset.name)+'_%02d_StandIn'%index)
            proxies.append(proxy)
            shape=cmds.createNode('aiStandIn',name=clean_name(asset.name)+'_%02d_StandInShape'%index,parent=proxy)
            cmds.setAttr(shape+'.dso',project_path(dest),type='string')
            if _look is not None and look_profile['controls']:
                try:
                    _look.attach_profile(shape,look_profile)
                except Exception as exc:
                    log('WARNING: Stand-in Look attributes unavailable: '+str(exc))
                    log('WARNING: Archive created, but look controls may be unavailable.')
            set_if(shape,'overrideShaders',False)
            cmds.xform(proxy,worldSpace=True,translation=list(pivot))
            log('ASS %d/%d: %s' % (index,len(units),dest.as_posix()))
        if len(proxies)>1:
            parent=cmds.group(empty=True,name=clean_name(asset.name)+'_StandIns')
            try:cmds.parent(proxies,parent,absolute=True)
            except Exception:cmds.delete(parent);raise
            result=parent
        else:result=proxies[0]
        # Delete editable source only after *every* archive and proxy succeeds.
        cmds.delete(root)
        log('NOTE: ASS archives can contain absolute texture paths. Collect external dependencies before project transfer.')
        return result
    except Exception:
        for proxy in proxies:
            if cmds.objExists(proxy):cmds.delete(proxy)
        for dest in exports:
            try:dest.unlink()
            except OSError:pass
        raise
    finally:
        try:
            if old_sel:cmds.select([n for n in old_sel if cmds.objExists(n)],replace=True)
            else:cmds.select(clear=True)
        except (RuntimeError,ValueError):pass


def selected_mesh_members(selection=None):
    """Return assignment members and non-intermediate mesh shapes; faces allowed."""
    members=[]; shapes=[]
    for item in (cmds.ls(selection=True,long=True) or []) if selection is None else selection:
        obj=item.split('.',1)[0]
        if not cmds.objExists(obj):continue
        typ=cmds.nodeType(obj)
        if '.' in item:
            if not re.search(r'\.f\[',item):continue
            if typ=='mesh': ss=[obj]
            elif typ=='transform': ss=cmds.listRelatives(obj,shapes=True,type='mesh',fullPath=True) or []
            else:continue
            ss=[s for s in ss if not cmds.getAttr(s+'.intermediateObject')]
            if ss: members.append(item); shapes.extend(ss)
        else:
            if typ=='mesh':ss=[obj]
            elif typ=='transform':ss=cmds.listRelatives(obj,allDescendents=True,type='mesh',fullPath=True) or []
            else:continue
            ss=[s for s in ss if not cmds.getAttr(s+'.intermediateObject')]
            members.extend(ss); shapes.extend(ss)
    return list(dict.fromkeys(members)),list(dict.fromkeys(shapes))


SELECTION_REQUIRED = 'マテリアルアサイン先のオブジェクトが選ばれていません'


class SelectionRequiredError(RuntimeError):
    pass


def import_asset(asset,settings,choose_mapping,log):
    old_selection=cmds.ls(selection=True,long=True) or []
    target_selection=settings.get('_selection',old_selection)
    mesh=choose_mesh(asset,settings['lod'],settings['family'])
    target_shapes=[]
    if not mesh and settings['assign']:
        target_selection,target_shapes=selected_mesh_members(target_selection)
        if not target_selection:raise SelectionRequiredError(SELECTION_REQUIRED)
    ensure_arnold()
    if 'openPBRSurface' not in (cmds.allNodeTypes() or []): raise RuntimeError('This Maya does not provide openPBRSurface.')
    old_files=set(cmds.ls(type='file',long=True) or [])
    old_namespace=cmds.namespaceInfo(currentNamespace=True)
    root=None; changed=False; success=False
    cmds.undoInfo(openChunk=True,chunkName='Asset Browser Import')
    try:
        cmds.namespace(setNamespace=':')
        selected_shapes=[]
        if mesh:
            root=cmds.group(empty=True,name=clean_name(asset.name)+'_GRP'); changed=True
            selected_shapes=import_mesh(mesh,root)
            mesh_kind,mesh_level=lod_of(mesh,asset.folder)
            log('Model: '+str(mesh.relative_to(asset.folder))+' ['+mesh_kind+' '+str(mesh_level if mesh_level is not None else '')+']')
            if mesh_level != settings['lod'] or mesh_kind=='Tier': log('  NOTE: selected available '+mesh_kind+'; Fab Tier is not identical to LOD.')
        else:
            log('Surface asset: generating OpenPBR material(s).')
        tier=tier_of(mesh,asset.folder) if mesh else None
        mesh_lod=lod_of(mesh,asset.folder)[1] if mesh and lod_of(mesh,asset.folder)[0]=='LOD' else None
        keys=sorted(asset.textures)
        settings['_unresolved_materials']=[]
        unresolved_bindings=[]
        materials={}
        def material_for(key):
            nonlocal changed
            if key not in materials:
                log('Material set: '+key); changed=True
                materials[key]=build_material(asset,key,settings,tier,mesh_lod,log)
            return materials[key]
        if mesh:
            if not keys: log('WARNING: No supported texture maps. Keeping imported materials.')
            # Collect original assignments before modifying any of them.
            plans=[]; remembered={}
            for shape in selected_shapes:
                groups,total=mesh_faces(shape)
                for sg,faces in groups.items():
                    if not keys: continue
                    hints=shader_hints(sg,shape)
                    # Trust only uniquely matching source shader/texture names.
                    # Synthetic FBX SG1, SG2 etc are not meaningful texture-set IDs.
                    key=safe_auto_material_key(keys,hints[1:]) or safe_auto_material_key(keys,[shape])
                    if key is None:
                        cache_key=sg or shape
                        if cache_key not in remembered:
                            if settings.get('manual_mapping',False):
                                remembered[cache_key]=choose_mapping(sg,shape,keys)
                            else:
                                remembered[cache_key]=None
                        key=remembered[cache_key]
                    if key is not None:
                        plans.append((shape,faces,total,key))
                        log('  Auto / approved mapping: '+str(sg)+' -> '+key)
                    else:
                        unresolved_bindings.append((sg,shape,faces,total))
                        settings['_unresolved_materials'].append((str(sg),str(shape)))
                        log('  UNRESOLVED (kept FBX shader, not preview-verified): '+str(sg)+' / '+shape)
            for shape,faces,total,key in plans:
                material=material_for(key)
                members=components(shape,faces,total)
                for i in range(0,len(members),2000): cmds.sets(members[i:i+2000],edit=True,forceElement=material['sg'])
                setup_shape(shape,material,settings)
            if settings['copy']:
                localize_file_nodes(set(cmds.ls(type='file',long=True) or [])-old_files,log,asset,mesh,strict=False)
            if not settings['standin'] and not settings.get('_heavy_confirmed'):
                tri_count=imported_triangles(selected_shapes)
                if tri_count>=HEAVY_TRIANGLES:
                    choice=standin_warning(settings.get('_parent'),['読み込み後の実測: 約%.1f万三角形'%(tri_count/10000)],settings)
                    if choice=='cancel':raise UserCancelled('Heavy model import cancelled.')
                    if choice=='standin':settings['standin']=True
            if settings['standin']:
                permit_export=True
                if unresolved_bindings:
                    suggestions=fir_tree_01_standin_suggestions(asset,unresolved_bindings,keys)
                    decision=unresolved_standin_decision(settings.get('_parent'),asset,unresolved_bindings,suggestions)
                    if decision=='cancel':
                        raise UserCancelled('Stand-in import cancelled; undoing imported mesh.')
                    elif decision=='editable':
                        permit_export=False
                        log('ASS: user chose to keep editable mesh after material warning.')
                    elif decision=='suggested':
                        # This is a *user-approved*, asset-specific inference, not automatic mapping.
                        for shape,faces,total,key in suggestions:
                            material=material_for(key)
                            members=components(shape,faces,total)
                            for i in range(0,len(members),2000):
                                cmds.sets(members[i:i+2000],edit=True,forceElement=material['sg'])
                            setup_shape(shape,material,settings)
                            log('  USER-APPROVED INFERRED mapping: '+shape+' -> '+key)
                        settings['_unresolved_materials']=[]
                        log('WARNING: Fir Tree 01 variant mapping is an inference. Confirm Arnold appearance against source.')
                    elif decision=='original':
                        log('WARNING: User explicitly approved ASS with unresolved original FBX materials; render appearance is NOT verified.')
                    else:
                        raise RuntimeError('Unexpected Stand-in material choice: '+str(decision))
                elif not plans:
                    permit_export=False
                    log('WARNING: ASS export skipped: no materials identified. Keeping editable mesh.')
                if permit_export:
                    try:
                        root=export_standin(root,asset,log,settings.get('standin_split','auto'),materials)
                    except Exception as e:
                        log('WARNING: Stand-in failed; keeping editable geometry. '+str(e))
                        if QtWidgets is not None and settings.get('_parent') is not None:
                            QtWidgets.QMessageBox.warning(settings['_parent'],'ASS export failed',
                               'ASS書き出しに失敗しました。編集可能メッシュは保持されています。\n'+str(e))
            cmds.select(root,replace=True)
        else:
            for key in keys: material_for(key)
            if settings['assign'] and target_selection and materials:
                key=next(iter(materials)) if len(materials)==1 else choose_mapping('Selected objects','',list(materials))
                if key:
                    mat=materials[key]; cmds.sets(target_selection,edit=True,forceElement=mat['sg'])
                    for shape in target_shapes: setup_shape(shape,mat,settings)
                if old_selection:cmds.select(old_selection,replace=True)
                else:cmds.select(clear=True)
            elif materials:
                cmds.select([x['mat'] for x in materials.values()],replace=True)
        success=True
        return root or list(materials.values())
    finally:
        try:
            if cmds.namespace(exists=old_namespace): cmds.namespace(setNamespace=old_namespace)
        finally: cmds.undoInfo(closeChunk=True)
        if not success and changed:
            try:
                if cmds.undoInfo(query=True,state=True): cmds.undo()
            except Exception as e: log('WARNING: Undo failed: '+str(e))

def standin_warning(parent, reasons, settings=None):
    """Ask about heavy geometry and optional per-import ASS splitting.

    The checkbox is *off* for each new asset by default.  A user may already
    have explicitly enabled the advanced split option for this particular
    asset; in that case the confirmation reflects their existing choice.
    The result is written to the captured import settings, not the persistent
    browser checkbox, so it cannot leak into the next asset/queued download.
    """
    dialog = QtWidgets.QMessageBox(parent)
    dialog.setIcon(QtWidgets.QMessageBox.Warning)
    dialog.setWindowTitle('高負荷モデルの確認 / Arnold Stand-in')
    dialog.setText('このモデルは重い可能性があります。\nArnold Stand-inとして取り込まなくていいですか？')
    dialog.setInformativeText(
        '\n'.join(reasons)
        + '\n\nStand-inはMayaのビューポート負荷を減らしますが、直接ポリゴン編集できなくなります。'
        + '\n\n一つのアセットに複数の木や草などが存在する場合は、以下をチェックしてください。'
        + '\n※ 元データ内で独立したグループを識別できた場合のみ個別ASSを作成します。'
    )
    separate = QtWidgets.QCheckBox('Separate independent trees / groups into ASS', dialog)
    separate.setChecked(bool(settings and settings.get('standin_split') == 'auto'))
    separate.setToolTip('初期値OFF。木・草などが独立したFBXグループとして判別できる場合に、個別ASS化します。')
    dialog.setCheckBox(separate)
    yes = dialog.addButton('Stand-inで取り込む（推奨）', QtWidgets.QMessageBox.AcceptRole)
    no = dialog.addButton('通常のメッシュで取り込む', QtWidgets.QMessageBox.DestructiveRole)
    dialog.addButton('キャンセル', QtWidgets.QMessageBox.RejectRole)
    dialog.setDefaultButton(yes)
    dialog.exec() if hasattr(dialog, 'exec') else dialog.exec_()
    button = dialog.clickedButton()
    choice = 'standin' if button is yes else ('editable' if button is no else 'cancel')
    if settings is not None:
        # The checkbox is meaningful only for Stand-in.  On any other action,
        # ignore it and keep normal editable-mesh behavior unchanged.
        settings['standin_split'] = 'auto' if choice == 'standin' and separate.isChecked() else 'single'
    return choice


# ---------------- PySide browser ----------------
if QtWidgets is not None:
    class AssetBrowser(QtWidgets.QDialog):
        def __init__(self,parent=None):
            super(AssetBrowser,self).__init__(parent)
            self.setObjectName('MayaLocalAssetBrowserWindow')
            self.setWindowTitle('PolyHaven Asset Browser  |  '+VERSION)
            self.resize(1060,740)
            self.setMinimumSize(740,520)
            self.assets=[]; self.roots=[]; self.icon_cache={}; self._busy=False; self._standin_selection_key=None
            self._make_ui()
            self._load_roots()
            if self.roots: QtCore.QTimer.singleShot(0,self.refresh)

        def _make_ui(self):
            v=QtWidgets.QVBoxLayout(self); v.setContentsMargins(12,12,12,12); v.setSpacing(8)
            title=QtWidgets.QLabel('LOCAL ASSET LIBRARY'); title.setStyleSheet('font-size: 18px; font-weight: bold;'); v.addWidget(title)
            sub=QtWidgets.QLabel('Poly Haven  ·  OpenPBR / Arnold'); v.addWidget(sub)
            rootrow=QtWidgets.QHBoxLayout(); self.root_combo=QtWidgets.QComboBox(); self.root_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon); self.root_combo.setMinimumContentsLength(18); self.root_combo.setToolTip('All registered folders are scanned. Select a folder here to remove it.')
            rootrow.addWidget(self.root_combo,1)
            for label,action in [('Add Folder…',self.add_root),('Remove',self.remove_root),('Refresh',self.refresh)]:
                b=QtWidgets.QPushButton(label); b.clicked.connect(action); rootrow.addWidget(b)
            v.addLayout(rootrow)
            filters=QtWidgets.QHBoxLayout(); self.search=QtWidgets.QLineEdit(); self.search.setPlaceholderText('Search name / source / folder…'); self.search.textChanged.connect(self.rebuild)
            self.category=QtWidgets.QComboBox(); self.category.addItems(['All','3D','Surfaces','Plants']); self.category.currentIndexChanged.connect(self.rebuild)
            filters.addWidget(self.search,1); filters.addWidget(self.category); v.addLayout(filters); self._base_filter_row=filters
            splitter=QtWidgets.QSplitter(QtCore.Qt.Horizontal); v.addWidget(splitter,1)
            self.list=QtWidgets.QListWidget(); self.list.setViewMode(QtWidgets.QListView.IconMode); self.list.setResizeMode(QtWidgets.QListView.Adjust); self.list.setMovement(QtWidgets.QListView.Static); self.list.setIconSize(QtCore.QSize(132,108)); self.list.setGridSize(QtCore.QSize(162,155)); self.list.setWordWrap(True); self.list.setSpacing(3); self.list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
            self.list.currentItemChanged.connect(self.on_selected); self.list.itemDoubleClicked.connect(lambda _item:self.run_import())
            splitter.addWidget(self.list)
            panel=QtWidgets.QWidget(); pv=QtWidgets.QVBoxLayout(panel); pv.setContentsMargins(9,0,3,0); pv.setSpacing(6)
            self.preview=QtWidgets.QLabel('Select an asset'); self.preview.setAlignment(QtCore.Qt.AlignCenter); self.preview.setMinimumHeight(125); self.preview.setMaximumHeight(155); self.preview.setStyleSheet('background: palette(base); border: 1px solid palette(mid);'); pv.addWidget(self.preview)
            self.asset_label=QtWidgets.QLabel('No asset selected'); self.asset_label.setWordWrap(True); self.asset_label.setStyleSheet('font-weight:bold; font-size: 14px;'); pv.addWidget(self.asset_label)
            form=QtWidgets.QFormLayout(); form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
            self.family=QtWidgets.QComboBox(); self.family.currentIndexChanged.connect(self.update_details); form.addRow('Model variant',self.family)
            self.lod=QtWidgets.QComboBox(); self.lod.addItems(['LOD 0','LOD 1','LOD 2','LOD 3','LOD 4','LOD 5','LOD 6']); self.lod.setCurrentIndex(1); self.lod.currentIndexChanged.connect(self.update_details); form.addRow('Mesh LOD / Tier',self.lod)
            self.res=QtWidgets.QComboBox(); self.res.addItems(['1K','2K','4K','8K','16K']); self.res.setCurrentIndex(1); self.res.currentIndexChanged.connect(self.update_details); form.addRow('Texture resolution',self.res)
            self.normal=QtWidgets.QComboBox(); self.normal.addItems(['Auto (file name)','OpenGL','DirectX']); form.addRow('Normal convention',self.normal)
            self.disp=QtWidgets.QCheckBox('Enable Displacement'); self.disp.setChecked(False); self.disp.toggled.connect(self.toggle_displacement); form.addRow(self.disp)
            self.height=QtWidgets.QDoubleSpinBox(); self.height.setRange(0.001,10000); self.height.setDecimals(3); self.height.setSingleStep(0.1); self.height.setValue(0.2); form.addRow('Height (scene units)',self.height)
            self.mid=QtWidgets.QDoubleSpinBox(); self.mid.setRange(-10000,10000); self.mid.setDecimals(3); self.mid.setSingleStep(0.1); self.mid.setValue(0.5); form.addRow('Height midpoint',self.mid)
            self.subdiv=QtWidgets.QSpinBox(); self.subdiv.setRange(0,5); self.subdiv.setValue(2); form.addRow('Subdiv iterations',self.subdiv)
            self.proxy=QtWidgets.QCheckBox('Import as Arnold Stand-in'); self.proxy.setChecked(False); self.proxy.setToolTip('1回限りの設定です。インポート開始後に自動でOFFへ戻ります。\n警告でStand-inを選んでも、次のアセットには引き継ぎません。'); form.addRow(self.proxy)
            self.split_standin=QtWidgets.QCheckBox('Separate independent trees / groups into ASS'); self.split_standin.setChecked(False); self.split_standin.setToolTip('初期値OFF。必要なアセットでのみONにしてください。\nASS読み込み時に限り、明確に独立したFBXグループを別々に書き出します。\n選択アセットの切り替えやインポート開始後にOFFへ戻ります。'); form.addRow(self.split_standin)
            self.copy=QtWidgets.QCheckBox('Copy textures to Maya project'); self.copy.setChecked(True); form.addRow(self.copy)
            self.assign=QtWidgets.QCheckBox('Surfaces: assign to selection'); self.assign.setChecked(True); form.addRow(self.assign)
            self.manual_mapping=QtWidgets.QCheckBox('Advanced: Ask for ambiguous materials')
            self.manual_mapping.setChecked(False)
            self.manual_mapping.setToolTip('OFF (recommended): never guess from FBX shading group numbers.\n'
                                           'Keep unknown original shaders and report once after import.\n'
                                           'ON (advanced): choose missing material assignments by hand.')
            form.addRow(self.manual_mapping)
            pv.addLayout(form); self.toggle_displacement(False)
            self.detail=QtWidgets.QPlainTextEdit(); self.detail.setReadOnly(True); self.detail.setMinimumHeight(100); self.detail.setMaximumHeight(200); pv.addWidget(self.detail,1)
            self.import_btn=QtWidgets.QPushButton('IMPORT  /  CREATE OPENPBR'); self.import_btn.setMinimumHeight(40); self.import_btn.setEnabled(False); self.import_btn.clicked.connect(self.run_import); pv.addWidget(self.import_btn)
            splitter.addWidget(panel); splitter.setSizes([610,410]); panel.setMinimumWidth(310)
            bottom=QtWidgets.QHBoxLayout(); self.status=QtWidgets.QLabel('Add a folder containing extracted assets.'); bottom.addWidget(self.status,1)
            b=QtWidgets.QPushButton('Open Asset Folder'); b.clicked.connect(self.open_folder); bottom.addWidget(b); v.addLayout(bottom)
            self.logbox=QtWidgets.QPlainTextEdit(); self.logbox.setReadOnly(True); self.logbox.setMaximumHeight(125); self.logbox.setPlaceholderText('Import log / warnings'); v.addWidget(self.logbox)

        def toggle_displacement(self,on):
            for w in (self.height,self.mid,self.subdiv): w.setEnabled(on)

        def _load_roots(self):
            try:
                raw=cmds.optionVar(query='PolyHavenAssetBrowserRootsV1') if cmds.optionVar(exists='PolyHavenAssetBrowserRootsV1') else '[]'
                self.roots=[p for p in json.loads(raw) if Path(p).is_dir()]
            except Exception: self.roots=[]
            self._roots_ui()

        def _roots_ui(self):
            self.root_combo.clear(); self.root_combo.addItems(self.roots)
            if not self.roots: self.root_combo.addItem('No library folder configured')
            cmds.optionVar(stringValue=('PolyHavenAssetBrowserRootsV1',json.dumps(self.roots,ensure_ascii=False)))

        def add_root(self):
            start=self.roots[-1] if self.roots else str(workspace_root())
            folder=QtWidgets.QFileDialog.getExistingDirectory(self,'Choose library folder',start)
            if not folder:return
            folder=str(Path(folder).resolve())
            if folder not in self.roots: self.roots.append(folder)
            self._roots_ui(); self.root_combo.setCurrentIndex(self.roots.index(folder)); self.refresh()

        def remove_root(self):
            i=self.root_combo.currentIndex()
            if 0<=i<len(self.roots): self.roots.pop(i); self._roots_ui(); self.refresh()

        def log(self,message):
            self.logbox.appendPlainText(str(message)); print('[AssetBrowser] '+str(message))

        def refresh(self):
            if self._busy:return
            self._busy=True; self.status.setText('Scanning local folders…'); QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                assets={}; self.icon_cache={}
                for root in self.roots:
                    try:
                        for a in scan_library(root): assets[str(a.folder)]=a
                    except Exception as e: self.log('Scan warning: '+str(e))
                self.assets=sorted(assets.values(),key=lambda a:(a.name.lower(),str(a.folder)))
                self.rebuild()
                self.log('Scanned '+str(len(self.assets))+' asset folder(s).')
            finally:
                self._busy=False; QtWidgets.QApplication.restoreOverrideCursor()

        def thumbnail(self,a):
            key=str(a.folder)
            if key in self.icon_cache:return self.icon_cache[key]
            p=a.preview_path(); pm=QtGui.QPixmap()
            if p:
                reader=QtGui.QImageReader(str(p)); reader.setAutoTransform(True)
                size=reader.size()
                if size.isValid(): reader.setScaledSize(size.scaled(QtCore.QSize(264,216),QtCore.Qt.KeepAspectRatio))
                image=reader.read()
                if not image.isNull(): pm=QtGui.QPixmap.fromImage(image)
            if pm.isNull():
                pm=QtGui.QPixmap(132,108); pm.fill(QtGui.QColor('#555b63'))
                painter=QtGui.QPainter(pm); painter.setPen(QtGui.QColor('#e5e7eb')); painter.drawText(pm.rect(),QtCore.Qt.AlignCenter,a.category); painter.end()
            self.icon_cache[key]=pm
            return pm

        def rebuild(self,*_):
            current=self.selected(); last=str(current.folder) if current else None
            self.list.clear(); term=self.search.text().strip().lower(); cat=self.category.currentText(); count=0
            for i,a in enumerate(self.assets):
                if cat!='All' and cat!=a.category: continue
                if term and term not in (a.name+' '+a.source+' '+str(a.folder)).lower(): continue
                item=QtWidgets.QListWidgetItem(QtGui.QIcon(self.thumbnail(a)),a.name+'\n'+a.category)
                item.setData(QtCore.Qt.UserRole,i); item.setToolTip(str(a.folder)); self.list.addItem(item); count+=1
                if str(a.folder)==last: self.list.setCurrentItem(item)
            if self.list.count() and self.list.currentItem() is None:self.list.setCurrentRow(0)
            self.status.setText(str(count)+' shown  /  '+str(len(self.assets))+' total')
            if not self.list.count():self.on_selected(None,None)

        def selected(self):
            item=self.list.currentItem()
            if item is None:return None
            i=item.data(QtCore.Qt.UserRole)
            return self.assets[i] if isinstance(i,int) and 0<=i<len(self.assets) else None

        def _reset_standin_for_selection(self, key):
            """Do not carry an explicit Stand-in choice into a different asset.

            Ignore empty/intermediate selection during thumbnail list rebuilds.
            Never reset during ordinary refresh of the same selected asset.
            """
            if key is None or key==self._standin_selection_key:return
            self._standin_selection_key=key
            self.proxy.setChecked(False)
            self.split_standin.setChecked(False)

        def on_selected(self,*_):
            a=self.selected()
            self._reset_standin_for_selection(('local', str(a.folder)) if a is not None else None)
            self.family.blockSignals(True); self.family.clear(); self.family.addItem('Auto (recommended)',None)
            if a:
                for key in sorted({mesh_family(p) for p in a.meshes}):self.family.addItem(key,key)
            self.family.blockSignals(False)
            self.import_btn.setEnabled(a is not None)
            self.family.setEnabled(bool(a and a.meshes)); self.lod.setEnabled(bool(a and a.meshes)); self.proxy.setEnabled(bool(a and a.meshes)); self.assign.setEnabled(bool(a and not a.meshes))
            self.split_standin.setEnabled(bool(a and a.meshes))
            if a:
                self.preview.setPixmap(self.thumbnail(a).scaled(290,150,QtCore.Qt.KeepAspectRatio,QtCore.Qt.SmoothTransformation))
                self.asset_label.setText(a.name+'  |  '+a.source+'  |  '+a.category)
            else:
                self.preview.clear(); self.preview.setText('Select an asset'); self.asset_label.setText('No asset selected')
            self.update_details()

        def settings(self):
            return dict(lod=self.lod.currentIndex(),family=self.family.currentData(),resolution=int(self.res.currentText().rstrip('K')),normal=self.normal.currentText(),displacement=self.disp.isChecked(),height=self.height.value(),mid=self.mid.value(),subdiv=self.subdiv.value(),standin=self.proxy.isChecked(),standin_split='auto' if self.split_standin.isChecked() else 'single',copy=self.copy.isChecked(),assign=self.assign.isChecked(),manual_mapping=self.manual_mapping.isChecked())

        def update_details(self,*_):
            a=self.selected()
            if not a:self.detail.clear();return
            s=self.settings(); mesh=choose_mesh(a,s['lod'],s['family'])
            lines=['Folder: '+str(a.folder)]
            if mesh:
                kind,level=lod_of(mesh,a.folder); lines+=['Mesh: '+str(mesh.relative_to(a.folder)),'Quality: '+kind+' '+str(level if level is not None else '(only original)')]
                if kind=='Tier':lines.append('Note: Fab Tier != traditional LOD.')
                elif level!=s['lod']:lines.append('Requested LOD unavailable; using available model.')
            else:lines.append('Surface: no mesh. Create material; Assign to Selection applies it to selected geometry.')
            tier=tier_of(mesh,a.folder) if mesh else None
            mlod=lod_of(mesh,a.folder)[1] if mesh and lod_of(mesh,a.folder)[0]=='LOD' else None
            for key in sorted(a.textures):
                lines.append('\n['+key+']')
                maps=texture_set(a,key,s['resolution'],tier,mlod)
                for role,t in sorted(maps.items()):
                    lines.append(role+': '+t.path.name+'  ('+(str(t.res)+'K' if t.res else 'unknown')+')'+('  [fallback]' if t.res and t.res!=s['resolution'] else ''))
            if a.unknown:lines.append('\nUnclassified image files: '+str(len(a.unknown)))
            self.detail.setPlainText('\n'.join(lines))

        def mapping(self,sg,shape,keys):
            # Student default: no per-material dialog; Stand-in requires explicit confirmation if unresolved.
            # Multiple surface-only materials still require choosing what to apply
            # to the user's selected polygon; this is not FBX material ambiguity.
            if sg!='Selected objects' and not self.manual_mapping.isChecked():return None
            options=['Keep original (NOT preview verified)']+list(keys)
            text=('元マテリアル: '+str(sg or '(none)')+'\nMesh: '+str(shape)+'\n'
                  '対応するテクスチャセットを選択（不明なら Keep original）')
            choice,ok=QtWidgets.QInputDialog.getItem(self,'Texture set assignment — Advanced',text,options,0,False)
            if not ok: raise UserCancelled('Import cancelled by user.')
            return None if choice==options[0] else choice

        def open_folder(self):
            a=self.selected()
            if a:QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(a.folder)))

        def run_import(self):
            a=self.selected()
            if not a or self._busy:return
            settings=self.settings()
            if not self.proxy.isChecked() and a.meshes:
                mesh=choose_mesh(a,settings['lod'],settings['family'])
                hint=heavy_asset_hint(a,mesh)
                if hint['warn']:
                    choice=standin_warning(self,hint['reason'],settings)
                    if choice=='cancel':return
                    settings['_heavy_confirmed']=True
                    if choice=='standin':settings['standin']=True
            settings['_parent']=self
            self._busy=True; self.import_btn.setEnabled(False); self.log('--- '+a.name+' ---')
            try:
                import_asset(a,settings,self.mapping,self.log)
                self.log('Finished. Review warnings above.'); self.status.setText('Import finished: '+a.name)
                mapping_summary(settings,self.log,self)
            except UserCancelled as e:self.log(str(e))
            except Exception as e:
                self.log('ERROR: '+str(e)); self.log(traceback.format_exc()); QtWidgets.QMessageBox.warning(self,'Asset import failed',str(e)+'\nSee the import log for details.')
            finally:
                self._busy=False
                self.proxy.setChecked(False)  # Stand-in is one-shot, even for manual checkbox use.
                self.split_standin.setChecked(False)  # One-shot split preference; avoid affecting the next import.
                self.import_btn.setEnabled(self.selected() is not None)


# ---------------- Local Poly Haven cache ----------------
import time
import concurrent.futures
import tempfile
ASSET_EXT = MESH_EXT | IMAGE_EXT | {'.json', '.mtl'}

MAX_UNPACK = 64 * 1024**3
WINDOWS_RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', re.I)

def safe_member(name):
    """Validate ZIP paths on all platforms, including Windows aliases and ADS."""
    name = name.replace('\\', '/')
    parts = name.rstrip('/').split('/')
    if not parts or any(not p or p in ('.','..') or p.endswith(('.', ' ')) or
                        WINDOWS_RESERVED.match(p) or re.search(r'[\x00-\x1f<>:"|?*]',p)
                        for p in parts):
        raise ValueError('Unsafe archive path: '+repr(name))
    return parts


def package_assets(folder):
    """Preserve a cached Poly Haven asset layout and texture sets."""
    folder=Path(folder).resolve()
    files=[]
    for directory, dirs, names in os.walk(str(folder),followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__MACOSX' and not (Path(directory)/d).is_symlink()]
        for name in names:
            p=Path(directory)/name
            if not p.is_symlink() and p.suffix.lower() in ASSET_EXT: files.append(p)
    if not files: raise ValueError('No supported asset files found (FBX/OBJ/PBR textures).')
    a=Asset(folder, files)
    if not a.metadata['name']:
        a.name=re.sub(r'_[0-9a-f]{10}$','',a.name)
    if not a.meshes and not any(set(roles)&{'base','rough','normal_gl','normal_dx','packed','ordp','disp'} for roles in a.textures.values()):
        raise ValueError('No FBX/OBJ or recognizable PBR textures found. Choose FBX or a supported texture set.')
    return a


# ---------------- Native online catalog and persistent acquisition ----------------
from urllib.request import Request, urlopen
from urllib.parse import urlsplit, unquote, quote
from urllib.error import HTTPError
import threading

PH_API='https://api.polyhaven.com'
PH_AGENT='PolyHavenAssetBrowser/5.2'
PH_FORMATS={'.fbx','.obj','.mtl','.jpg','.jpeg','.png','.tif','.tiff','.exr','.tga','.bmp','.webp'}


def ph_url_ok(url):
    u=urlsplit(url)
    h=(u.hostname or '').lower()
    return u.scheme=='https' and not u.username and not u.password and (h=='polyhaven.com' or h.endswith('.polyhaven.com') or h=='polyhaven.org' or h.endswith('.polyhaven.org'))


# macOS: use the system curl TLS implementation, not Maya's bundled SSL.
import sys as _ph_sys
import subprocess as _ph_subprocess
import tempfile as _ph_tempfile
import select as _ph_select
from urllib.parse import urljoin as _ph_urljoin


class _PHCurlResponse:
    """Streaming response; curl errors are checked before reporting EOF."""
    def __init__(self, url, cancel=None):
        self.url = url
        self.cancel = cancel
        self.buf = bytearray()
        self.eof = False
        self.proc = None
        self.err = _ph_tempfile.TemporaryFile(mode='w+b')
        # Do not let Maya-specific dynamic libraries or CA paths override the
        # macOS system curl defaults. The parent process is not modified.
        env = os.environ.copy()
        for key in list(env):
            if key.startswith('DYLD_') or key in ('SSL_CERT_FILE', 'SSL_CERT_DIR', 'CURL_CA_BUNDLE'):
                env.pop(key, None)
        args = ['/usr/bin/curl', '--disable', '--silent', '--show-error',
                '--include', '--no-buffer', '--http1.1', '--globoff',
                '--suppress-connect-headers', '--proto', '=https',
                '--connect-timeout', '15', '--speed-limit', '1',
                '--speed-time', '30', '--user-agent', PH_AGENT,
                '--header', 'Accept: */*', '--url', url]
        try:
            self.proc = _ph_subprocess.Popen(args, stdout=_ph_subprocess.PIPE,
                    stderr=self.err, bufsize=0, env=env)
            self.status, self.headers = self._read_headers()
        except BaseException:
            self.close()
            raise

    def _check_cancel(self):
        if self.cancel is not None and self.cancel.is_set():
            raise UserCancelled('Download cancelled.')

    def _pull(self):
        if self.eof:
            return b''
        self._check_cancel()
        fd = self.proc.stdout.fileno()
        while not _ph_select.select([fd], [], [], 0.2)[0]:
            self._check_cancel()
        self._check_cancel()
        data = os.read(fd, 65536)
        if not data:
            rc = self.proc.wait()
            self.eof = True
            if rc:
                self.err.seek(0)
                detail = self.err.read(4096).decode('utf-8', 'replace').strip()
                raise IOError('macOS curl error (%s): %s' % (rc, detail or 'HTTPS transfer failed'))
        return data

    def _line(self):
        while True:
            pos = self.buf.find(b'\n')
            if pos >= 0:
                if pos > 65536:
                    raise IOError('Poly Haven HTTP header too large.')
                line = bytes(self.buf[:pos+1]); del self.buf[:pos+1]
                return line
            if len(self.buf) > 65536:
                raise IOError('Poly Haven HTTP header too large.')
            data = self._pull()
            if not data:
                raise IOError('Incomplete Poly Haven HTTP response.')
            self.buf.extend(data)

    def _read_headers(self):
        # Handle informational HTTP responses before the final response.
        for _ in range(8):
            status_line = self._line().decode('iso-8859-1').strip().split()
            if len(status_line) < 2 or not status_line[0].startswith('HTTP/'):
                raise IOError('Invalid Poly Haven HTTP response.')
            status = int(status_line[1]); headers = {}; total = 0
            while True:
                line = self._line(); total += len(line)
                if total > 262144:
                    raise IOError('Poly Haven HTTP headers too large.')
                if line in (b'\r\n', b'\n'):
                    break
                key, sep, val = line.partition(b':')
                if sep:
                    headers[key.decode('iso-8859-1').strip().lower()] = val.decode('iso-8859-1').strip()
            if not 100 <= status < 200:
                return status, headers
        raise IOError('Too many informational HTTP responses.')

    def read(self, size=-1):
        self._check_cancel()
        if size == 0:
            return b''
        if size < 0:
            parts = [bytes(self.buf)]; self.buf.clear()
            while True:
                block = self._pull()
                if not block:
                    return b''.join(parts)
                parts.append(block)
        while len(self.buf) < size and not self.eof:
            block = self._pull()
            if not block:
                break
            self.buf.extend(block)
        data = bytes(self.buf[:size]); del self.buf[:size]
        return data

    def geturl(self):
        return self.url

    def close(self):
        p = self.proc
        self.proc = None
        try:
            if p is not None:
                if p.poll() is None:
                    p.terminate()
                    try:
                        p.wait(timeout=2)
                    except _ph_subprocess.TimeoutExpired:
                        p.kill(); p.wait()
                if p.stdout is not None:
                    p.stdout.close()
        finally:
            self.err.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _ph_open_mac(url, cancel=None):
    # Follow redirects ourselves so every destination is checked BEFORE contact.
    for _ in range(6):
        if not ph_url_ok(url):
            raise ValueError('Unexpected Poly Haven URL: '+str(url))
        r = _PHCurlResponse(url, cancel)
        if 200 <= r.status < 300:
            return r
        status = r.status; headers = r.headers
        r.close()
        if status in (301, 302, 303, 307, 308):
            location = headers.get('location')
            if not location:
                raise IOError('Poly Haven redirect has no Location header.')
            url = _ph_urljoin(url, location)
            continue
        if status == 429:
            raise RuntimeError('Poly Haven rate limit. Retry after '+str(headers.get('retry-after','a short wait'))+' seconds.')
        raise IOError('Poly Haven HTTP error %s: %s' % (status, url))
    raise IOError('Too many Poly Haven redirects.')


def ph_open(url, cancel=None):
    if not ph_url_ok(url): raise ValueError('Unexpected Poly Haven URL: '+str(url))
    if _ph_sys.platform == 'darwin':
        return _ph_open_mac(url, cancel)
    try:
        r=urlopen(Request(url,headers={'User-Agent':PH_AGENT,'Accept':'*/*'}),timeout=30)
    except HTTPError as e:
        if e.code==429: raise RuntimeError('Poly Haven rate limit. Retry after '+str(e.headers.get('Retry-After','a short wait'))+' seconds.') from e
        raise
    if not ph_url_ok(r.geturl()): r.close(); raise ValueError('Unexpected download redirect.')
    return r


def ph_json(url):
    with ph_open(url) as r:
        data=r.read(64*1024**2+1)
    if len(data)>64*1024**2: raise ValueError('API response too large.')
    obj=json.loads(data.decode('utf-8'))
    if not isinstance(obj,dict): raise ValueError('Unexpected Poly Haven response.')
    return obj


def atomic_json(path,data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8'); os.replace(str(tmp),str(path))
    finally:
        if tmp.exists(): tmp.unlink()


def ph_catalog(cache,force=False):
    path=Path(cache)/'catalog_v4.json'
    if not force and path.exists() and time.time()-path.stat().st_mtime<86400:
        try:return json.loads(path.read_text(encoding='utf-8')),False
        except Exception:pass
    try:
        data=ph_json(PH_API+'/assets')
        data={k:v for k,v in data.items() if re.fullmatch(r'[A-Za-z0-9_-]+',k) and isinstance(v,dict) and v.get('type') in (0,1,2)}
        if not data: raise ValueError('No supported assets returned.')
        atomic_json(path,data); return data,False
    except Exception:
        if path.exists():return json.loads(path.read_text(encoding='utf-8')),True
        raise


def ph_name(url):
    name=unquote(urlsplit(url).path.rsplit('/',1)[-1]); parts=safe_member(name)
    if len(parts)!=1:raise ValueError('Unsafe download file name.')
    return parts[0]


def ph_resolution(name):
    m=re.fullmatch(r'(\d+)k',str(name),re.I)
    return int(m.group(1)) if m else None


def ph_rank(res,wanted):
    return (abs(math.log2(res/wanted)) if res else 999, res is not None and res>wanted)


def ph_leaves(obj,path=()):
    if not isinstance(obj,dict):return
    if isinstance(obj.get('url'),str):
        yield path,obj; return
    for k,v in obj.items():
        if isinstance(v,dict):yield from ph_leaves(v,path+(str(k),))


PH_SURFACE_SCHEMA = 2


def ph_root_role(root):
    k=normalized(root)
    if k=='page': return 'page_color'
    if k in ('ao_rough_metal','ao_roughness_metallic','occlusion_roughness_metalness'): return 'packed'
    if COLOR_VARIANT_RE.fullmatch(k): return 'base'
    return ALIAS_ROLE.get(k)


def ph_plan(tree,kind,res,lod,slug=None):
    """Select FBX plus dependencies or individual maps. Return (relative path, metadata)."""
    if not isinstance(tree,dict):raise ValueError('Invalid files response.')
    result={}
    def put(rel,meta):
        rel='/'.join(safe_member(rel)); ext=Path(rel).suffix.lower()
        if ext not in PH_FORMATS:return
        if not ph_url_ok(meta.get('url','')):raise ValueError('Unexpected file host.')
        previous=result.get(rel.casefold())
        if previous and previous[1]['url']!=meta['url']:raise ValueError('Conflicting file paths: '+rel)
        result[rel.casefold()]=(rel,meta)
    if kind==2:
        candidates=[]
        for keys,meta in ph_leaves(tree.get('fbx',{})):
            name=ph_name(meta['url'])
            if Path(name).suffix.lower()!='.fbx':continue
            r=next((ph_resolution(k) for k in keys if ph_resolution(k)),None)
            m=LOD_RE.search(name); level=int(m.group(1)) if m else None
            candidates.append((r,level,name,meta))
        if not candidates:raise ValueError('This model has no direct FBX in the public API. Use an FBX package in Local Library instead.')
        r,level,name,meta=min(candidates,key=lambda x:(ph_rank(x[0],res),abs(x[1]-lod) if x[1] is not None else 999,x[2]))
        put(name,meta)
        includes=meta.get('include') or {}
        for rel,dep in includes.items():
            if isinstance(dep,dict) and isinstance(dep.get('url'),str):
                # API relative dependency paths may start with ./; never accept traversal.
                rel=rel.replace('\\','/')
                while rel.startswith('./'):rel=rel[2:]
                put(rel,dep)
    # Direct maps supplement FBX dependencies, or form the surface asset itself.
    # Prefer files included by the chosen FBX to avoid mixing texture sets/resolutions.
    image_keys=set()
    for rel,meta in result.values():
        role,key=classify(Path(rel))
        if role:image_keys.add((key,role))
    groups=defaultdict(list)
    for root,value in tree.items():
        if root.lower() in {'fbx','blend','gltf','usd','mtlx','hdri','backplates','colorchart','tonemapped'}:continue
        for keys,meta in ph_leaves(value,(root,)):
            name=ph_name(meta['url']); ext=Path(name).suffix.lower()
            if ext not in IMAGE_EXT or ext not in PH_FORMATS:continue
            role,key=classify(Path(name))
            if kind==1:
                # The API map key is authoritative for surfaces. The filename
                # still determines variant priority and is used by local scans.
                api_role=ph_root_role(root)
                if not api_role: continue
                role=api_role
                if slug: key=normalized(slug)
            if not role or (key,role) in image_keys:continue
            r=next((ph_resolution(k) for k in keys if ph_resolution(k)),None)
            ext_order=('.jpg','.jpeg','.png','.tif','.exr') if role in ('base','emission','page_color') else ('.exr','.png','.tif','.jpg','.jpeg')
            groups[(key,role)].append((ph_rank(r,res),base_variant_rank(Path(name)) if role=='base' else (0,0),ext_order.index(ext) if ext in ext_order else 99,name,meta))
    for variants in groups.values():
        _,_,_,name,meta=min(variants,key=lambda x:x[:4]); put('textures/'+name,meta)
    if kind==1 and not any(role=='base' for _,role in groups):
        raise ValueError('No recognized Base Color in Poly Haven surface. API map keys: '+', '.join(sorted(tree)))
    if not result:raise ValueError('No supported FBX or PBR files available.')
    if not any(Path(rel).suffix.lower() in IMAGE_EXT for rel,_ in result.values()):raise ValueError('No texture dependencies found in API response.')
    return list(result.values())


def ph_download_file(meta,dest,cancel,progress=None):
    dest=Path(dest); dest.parent.mkdir(parents=True,exist_ok=True)
    expected=meta.get('size'); checksum=meta.get('md5'); h=hashlib.md5(); n=0
    if isinstance(expected,int) and expected>MAX_UNPACK:raise ValueError('File too large.')
    with ph_open(meta['url'], cancel=cancel) as r,dest.open('xb') as f:
        while True:
            if cancel.is_set():raise UserCancelled('Download cancelled.')
            block=r.read(1024*1024)
            if not block:break
            n+=len(block)
            if n>MAX_UNPACK or (isinstance(expected,int) and n>expected):raise ValueError('Download exceeds expected size.')
            f.write(block); h.update(block)
            if progress:progress(len(block))
    if isinstance(expected,int) and n!=expected:raise IOError('Size mismatch: '+dest.name)
    if checksum and h.hexdigest().lower()!=str(checksum).lower():raise IOError('MD5 mismatch: '+dest.name)
    return n


def ph_thumbnail(slug,meta,cache):
    version=hashlib.sha1(str(meta.get('thumbnail_url','') or meta.get('img_version','')).encode()).hexdigest()[:10]
    path=Path(cache)/'thumbs'/(slug+'_'+version+'.img')
    if path.exists():return path.read_bytes()
    url=meta.get('thumbnail_url') or ('https://cdn.polyhaven.com/asset_img/thumbs/'+quote(slug)+'.png?width=256&height=256')
    with ph_open(url) as r:data=r.read(3*1024**2+1)
    if len(data)>3*1024**2:raise ValueError('Thumbnail too large.')
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex)
    try:tmp.write_bytes(data); os.replace(str(tmp),str(path))
    finally:
        if tmp.exists():tmp.unlink()
    return data


def cached_asset(folder,source=None):
    a=package_assets(folder)
    marker=Path(folder)/'native_asset_info.json'
    if marker.exists():
        try:
            info=json.loads(marker.read_text(encoding='utf-8')); a.name=info.get('name') or a.name; a.source=info.get('source') or a.source
        except Exception:pass
    if source:a.source=source
    return a


def ph_acquire(slug,meta,res,lod,cache,cancel,notify):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',slug):raise ValueError('Invalid asset ID.')
    cache=Path(cache); root=cache/'PolyHaven'; root.mkdir(parents=True,exist_ok=True)
    version=hashlib.sha1(str(meta.get('files_hash') or 'unversioned').encode()).hexdigest()[:10]
    dest=root/(slug+'_'+str(res)+'k_lod'+str(lod)+'_'+version)
    repair_cache=dest.is_dir()
    marker=dest/'native_asset_info.json'
    info={}
    if meta['type']==2 and _safe_polycount(meta.get('polycount')) is None:
        # Reuse cached official info; avoid a network request for every import.
        saved_count=None
        if marker.is_file():
            try:saved_count=_safe_polycount(json.loads(marker.read_text(encoding='utf-8')).get('polycount'))
            except (OSError,ValueError,UnicodeError):pass
        if saved_count is not None:
            meta=dict(meta,polycount=saved_count)
        else:
            # This runs in the download worker, never on Maya's UI thread.
            try:
                details=ph_json(PH_API+'/info/'+quote(slug))
                polycount=_safe_polycount(details.get('polycount'))
                if polycount is not None:meta=dict(meta,polycount=polycount)
            except Exception as exc:
                notify('NOTE: Poly Haven polygon count unavailable: '+str(exc))
    if repair_cache:
        try: info=json.loads(marker.read_text(encoding='utf-8'))
        except (OSError,ValueError): pass
        try: a=cached_asset(dest,'Poly Haven')
        except Exception:
            a=None
            if meta['type']!=1: raise ValueError('Cached package damaged; remove '+str(dest)+' and retry.')
        has_base=bool(a and any(roles.get('base') for roles in a.textures.values()))
        manifest=info.get('map_files',[])
        complete=bool(manifest) and all(dest.joinpath(*safe_member(rel)).is_file() for rel in manifest)
        if meta['type']!=1 or (has_base and info.get('surface_schema')==PH_SURFACE_SCHEMA and complete):
            if meta['type']==2 and _safe_polycount(meta.get('polycount')) and not _safe_polycount(info.get('polycount')):
                info['polycount']=_safe_polycount(meta['polycount'])
                atomic_json(marker,info)
            notify('Cache hit: '+a.name); return a
        notify('Updating surface cache to current map schema: '+slug)
    notify('Fetching file list: '+slug)
    if cancel.is_set():raise UserCancelled('Download cancelled.')
    tree=ph_json(PH_API+'/files/'+quote(slug)); full_plan=ph_plan(tree,meta['type'],res,lod,slug)
    map_roles={}
    if meta['type']==1:
        unknown=[k for k,v in tree.items() if not ph_root_role(k) and k.lower() not in {'fbx','blend','gltf','usd','mtlx','materialx','zip','hdri','backplates','colorchart','tonemapped'} and any(Path(ph_name(m['url'])).suffix.lower() in IMAGE_EXT for _,m in ph_leaves(v))]
        if unknown: notify('NOTE: Unmapped API image roles: '+', '.join(unknown))
        url_roles={m['url']:ph_root_role(root) for root,value in tree.items() if ph_root_role(root) for _,m in ph_leaves(value)}
        map_roles={rel:[url_roles[m['url']],normalized(slug)] for rel,m in full_plan if m['url'] in url_roles}
        info.update(surface_schema=PH_SURFACE_SCHEMA,map_files=[rel for rel,_ in full_plan],map_roles=map_roles)
    info.update(name=meta.get('name',slug),source='Poly Haven',category=meta.get('category',''),slug=slug,requested_resolution=res,requested_lod=lod,polycount=_safe_polycount(meta.get('polycount')))
    plan=full_plan
    if repair_cache:
        def good(rel,m):
            path=dest.joinpath(*safe_member(rel)); size=m.get('size')
            if not path.is_file() or (isinstance(size,int) and path.stat().st_size!=size):return False
            checksum=m.get('md5')
            if checksum:
                h=hashlib.md5()
                with path.open('rb') as f:
                    for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
                return h.hexdigest().lower()==str(checksum).lower()
            return True
        plan=[(rel,m) for rel,m in full_plan if not good(rel,m)]
    total=sum(m.get('size',0) for _,m in plan if isinstance(m.get('size'),int))
    if total>MAX_UNPACK or total+64*1024**2>shutil.disk_usage(str(root)).free:raise IOError('Insufficient disk space / package exceeds limit.')
    stage=Path(tempfile.mkdtemp(prefix='.download_',dir=str(root))); done=0; last=[0.0]
    def progress(n):
        nonlocal done
        done+=n
        if time.monotonic()-last[0]>=1:
            last[0]=time.monotonic(); notify('Downloading: %.1f / %.1f MB'%(done/1024**2,total/1024**2))
    try:
        for rel,m in plan:
            if cancel.is_set():raise UserCancelled('Download cancelled.')
            notify('File: '+rel); ph_download_file(m,stage.joinpath(*rel.split('/')),cancel,progress)
        if repair_cache:
            if cancel.is_set():raise UserCancelled('Download cancelled.')
            for rel,_ in plan:
                src=stage.joinpath(*rel.split('/')); target=dest.joinpath(*rel.split('/'))
                target.parent.mkdir(parents=True,exist_ok=True)
                os.replace(str(src),str(target))
            atomic_json(marker,info)
            repaired=cached_asset(dest,'Poly Haven')
            notify('Cache updated: '+repaired.name)
            if not any(roles.get('base') for roles in repaired.textures.values()):
                raise ValueError('Surface cache still has no Base Color map: '+slug)
            return repaired
        try:
            image=ph_thumbnail(slug,meta,cache); (stage/'preview.webp').write_bytes(image)
        except Exception:pass
        atomic_json(stage/'native_asset_info.json',info)
        a=package_assets(stage)
        if meta['type']==2 and not a.meshes:raise ValueError('FBX missing after download.')
        if meta['type']==1 and not any(roles.get('base') for roles in a.textures.values()):raise ValueError('Downloaded surface lacks Base Color: '+slug)
        if cancel.is_set():raise UserCancelled('Download cancelled.')
        stage.rename(dest); return cached_asset(dest,'Poly Haven')
    finally:
        if stage.exists():shutil.rmtree(str(stage),ignore_errors=True)


def ph_hdri_plan(tree,res):
    candidates=[]
    for keys,meta in ph_leaves(tree.get('hdri',{})):
        name=ph_name(meta['url']); ext=Path(name).suffix.lower()
        if ext!='.exr':continue
        r=next((ph_resolution(k) for k in keys if ph_resolution(k)),None)
        if not r:continue
        candidates.append((ph_rank(r,res),name,meta,r))
    if not candidates:raise ValueError('No EXR HDRI available for this asset.')
    _,name,meta,r=min(candidates,key=lambda x:(x[0],x[1]))
    return name,meta,r


def ph_acquire_hdri(slug,meta,res,cache,cancel,notify):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',slug):raise ValueError('Invalid asset ID.')
    version=hashlib.sha1(str(meta.get('files_hash') or 'unversioned').encode()).hexdigest()[:10]
    root=Path(cache)/'HDRIs'/slug/version/('%dk'%res); root.mkdir(parents=True,exist_ok=True)
    manifest=root/'download.json'
    if manifest.is_file():
        info=json.loads(manifest.read_text(encoding='utf-8')); path=root/ph_name(info['url'])
        if path.is_file() and path.stat().st_size==info.get('size'):
            notify('HDRI cache hit: '+path.name); return path
    if cancel.is_set():raise UserCancelled('Download cancelled.')
    name,entry,actual=ph_hdri_plan(ph_json(PH_API+'/files/'+quote(slug)),res)
    dest=root/name
    if cancel.is_set():raise UserCancelled('Download cancelled.')
    tmp=root/('.'+name+'.'+uuid.uuid4().hex+'.part')
    notify('Downloading HDRI: '+name+(' (fallback %dK)'%actual if actual!=res else ''))
    try:
        ph_download_file(entry,tmp,cancel)
        if cancel.is_set():raise UserCancelled('Download cancelled.')
        os.replace(str(tmp),str(dest)); atomic_json(manifest,dict(entry,size=dest.stat().st_size)); return dest
    finally:
        if tmp.exists():tmp.unlink()


def import_hdri(path,settings,log=print):
    ensure_arnold(); path=Path(path).resolve()
    if path.suffix.lower() not in ('.exr','.hdr') or not path.is_file():raise ValueError('Choose an existing EXR or HDR image.')
    # HDRIs always live in the project, independently of model copy toggle.
    rel=copy_project_image(path,Path('HDRIs')/path.name)
    prefix=clean_name(path.stem); old_selection=cmds.ls(selection=True,long=True) or []
    old=[n for n in (cmds.ls(type='aiSkyDomeLight',long=True) or []) if not cmds.referenceQuery(n,isNodeReferenced=True)]
    cmds.undoInfo(openChunk=True,chunkName='Asset Browser HDRI')
    changed=False; success=False
    try:
        if settings.get('replace_hdri') and old:
            # Reuse selected skydome if possible; otherwise first editable light.
            selected_shapes=set(old_selection)
            for n in old_selection:selected_shapes.update(cmds.listRelatives(n,shapes=True,fullPath=True) or [])
            shape=next((n for n in old if n in selected_shapes),old[0])
            transform=(cmds.listRelatives(shape,parent=True,fullPath=True) or [])[0]
            log('Replacing HDRI on '+shape+'; other lights are unchanged.')
        else:
            transform=cmds.createNode('transform',name=prefix+'_SkyDome'); changed=True
            shape=cmds.createNode('aiSkyDomeLight',name=prefix+'_SkyDomeShape',parent=transform)
            try:cmds.sets(transform,add='defaultLightSet')
            except RuntimeError:pass
        f=cmds.shadingNode('file',asTexture=True,isColorManaged=True,name=prefix+'_HDRI_TEX'); changed=True
        set_if(f,'ignoreColorSpaceFileRules',True)
        cmds.setAttr(f+'.fileTextureName',rel,type='string')
        cmds.setAttr(f+'.colorSpace',choose_space('base',rel),type='string')
        # No gamma conversion for linear Rec.709 EXR other than OCIO transform.
        plug(f+'.outColor',shape+'.color')
        set_if(shape,'intensity',1.0); set_if(shape,'exposure',settings.get('exposure',0.0))
        if not set_if(shape,'camera',float(settings.get('camera',True))):log('WARNING: camera visibility attribute not found.')
        if attr(shape,'format'):
            opts=cmds.attributeQuery('format',node=shape,listEnum=True) or []
            names=opts[0].split(':') if opts else []
            ix=next((i for i,n in enumerate(names) if 'lat' in n.lower() and 'long' in n.lower()),None)
            if ix is not None:cmds.setAttr(shape+'.format',ix)
        axis='rotateZ' if cmds.upAxis(query=True,axis=True)=='z' else 'rotateY'
        cmds.setAttr(transform+'.'+axis,settings.get('rotation',0.0))
        cmds.select(transform,replace=True); success=True; log('HDRI: '+rel); return transform
    finally:
        cmds.undoInfo(closeChunk=True)
        if changed and not success and cmds.undoInfo(query=True,state=True):cmds.undo()


# ---------------- Native Maya UI (all Qt and Maya calls on main thread) ----------------
import queue
if QtWidgets is not None:
    class NativeBrowser(AssetBrowser):
        def __init__(self,parent=None):
            self.native_ready=False
            super(NativeBrowser,self).__init__(parent)
            self.setObjectName('PolyHavenAssetBrowserV51'); self.setWindowTitle('PolyHaven Asset Browser | '+VERSION)
            self.resize(1220,870)
            self.cache=Path(cmds.internalVar(userAppDir=True))/'NativeAssetBrowser'
            (self.cache/'PolyHaven').mkdir(parents=True,exist_ok=True)
            self._confirmed_copy_root=None
            self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
            self.thumb_pool=concurrent.futures.ThreadPoolExecutor(max_workers=3)
            self.jobs=[]; self.thumb_jobs={}; self.catalog={}; self.catalog_job=None; self.page=0; self.page_size=36
            self.messages=queue.Queue(); self.cancel=threading.Event(); self.closing=False
            self.make_native_ui(); self.native_ready=True
            self.timer=QtCore.QTimer(self); self.timer.setInterval(700); self.timer.timeout.connect(self.tick_native); self.timer.start()
            QtCore.QTimer.singleShot(0,self.refresh)
            self.tabs.setCurrentIndex(1)

        def make_native_ui(self):
            v=self.layout(); title=v.itemAt(0).widget(); title.setText('POLYHAVEN ASSET BROWSER')
            v.itemAt(1).widget().setText('Poly Haven online & local library   |   OpenPBR / Arnold')
            v.takeAt(0); header=QtWidgets.QHBoxLayout(); header.addWidget(title,1); help_btn=QtWidgets.QPushButton('Help'); help_btn.setToolTip('日本語マニュアルを開く'); help_btn.clicked.connect(lambda checked=False: QtGui.QDesktopServices.openUrl(QtCore.QUrl('https://github.com/nmasaaki-web/nTools/blob/main/docs/tools/polyhaven.md'))); header.addWidget(help_btn); v.insertLayout(0,header)
            row=QtWidgets.QHBoxLayout()
            def button(layout,label,fn):
                b=QtWidgets.QPushButton(label); b.clicked.connect(fn); layout.addWidget(b); return b
            button(row,'Repair Texture Paths',self.repair_paths)
            button(row,'植物SSS（既存シーン）',self.setup_scene_plant_sss)
            button(row,'Stand-in Look Controller',self.open_standin_look_controller)
            button(row,'Open Cache',lambda:QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.cache/'PolyHaven'))))
            row.addStretch(1); v.insertLayout(2,row)
            # Native browser has one search row inside the active tab. Keep the
            # base class widgets hidden (but available to Local Library filtering).
            self.search.hide(); self.category.hide()
            v.removeItem(self._base_filter_row)
            # Keep original local library and existing import settings; switch only the list pane.
            splitter=self.list.parentWidget(); self.tabs=QtWidgets.QTabWidget(); self.local_page=QtWidgets.QWidget(); local=QtWidgets.QVBoxLayout(self.local_page); self.local_layout=local; local.setContentsMargins(0,0,0,0)
            self.list.setParent(self.local_page); local.addWidget(self.list); self.tabs.addTab(self.local_page,'Local Library')
            self.online_page=QtWidgets.QWidget(); self.online_layout=QtWidgets.QVBoxLayout(self.online_page); self.online_layout.setContentsMargins(0,0,0,0); self.online_content=QtWidgets.QWidget(); ol=QtWidgets.QVBoxLayout(self.online_content); self.online_content_layout=ol; ol.setContentsMargins(3,3,3,3); self.online_layout.addWidget(self.online_content)
            self.search_bar=QtWidgets.QWidget(); r=QtWidgets.QHBoxLayout(self.search_bar); r.setContentsMargins(0,0,0,0); self.ph_search=QtWidgets.QLineEdit(); self.ph_search.setPlaceholderText('Search local assets, models, surfaces or HDRIs…'); r.addWidget(self.ph_search,1)
            self.ph_kind=QtWidgets.QComboBox(); self.ph_kind.addItems(['All','3D Models','Plants','Surfaces']); r.addWidget(self.ph_kind)
            self.refresh_api_btn=button(r,'Refresh API',lambda:self.load_catalog(True)); ol.addWidget(self.search_bar)
            self.ph_list=QtWidgets.QListWidget(); self.ph_list.setViewMode(QtWidgets.QListView.IconMode); self.ph_list.setResizeMode(QtWidgets.QListView.Adjust); self.ph_list.setMovement(QtWidgets.QListView.Static); self.ph_list.setWordWrap(True); self.ph_list.setIconSize(QtCore.QSize(132,108)); self.ph_list.setGridSize(QtCore.QSize(162,155)); self.ph_list.setSpacing(3); ol.addWidget(self.ph_list,1)
            r=QtWidgets.QHBoxLayout(); self.prev_btn=button(r,'Previous',lambda:self.change_page(-1)); self.page_label=QtWidgets.QLabel('Not loaded'); r.addWidget(self.page_label,1); self.next_btn=button(r,'Next',lambda:self.change_page(1)); ol.addLayout(r)
            r=QtWidgets.QHBoxLayout(); self.cache_btn=button(r,'Download only',lambda:self.start_poly(False)); button(r,'Open asset page',self.open_poly_page); self.cancel_btn=button(r,'Cancel download',self.cancel_download); self.cancel_btn.setEnabled(False); ol.addLayout(r)
            ol.addWidget(QtWidgets.QLabel('Powered by Poly Haven  •  CC0 assets  •  Official public API'))
            self.tabs.addTab(self.online_page,'Poly Haven Assets'); self.hdri_page=QtWidgets.QWidget(); self.hdri_layout=QtWidgets.QVBoxLayout(self.hdri_page); self.hdri_layout.setContentsMargins(0,0,0,0); self.tabs.addTab(self.hdri_page,'Poly Haven HDRIs'); splitter.insertWidget(0,self.tabs); splitter.setSizes([680,440]); self.tabs.currentChanged.connect(self.source_changed)
            self.hdri_controls=QtWidgets.QGroupBox('HDRI lighting'); hf=QtWidgets.QFormLayout(self.hdri_controls)
            self.hdri_res=QtWidgets.QComboBox(); self.hdri_res.addItems(['1K','2K','4K','8K','16K']); self.hdri_res.setCurrentIndex(2); hf.addRow('HDRI resolution',self.hdri_res)
            self.hdri_exp=QtWidgets.QDoubleSpinBox(); self.hdri_exp.setRange(-15,15); self.hdri_exp.setSingleStep(0.1); hf.addRow('Exposure (EV)',self.hdri_exp)
            self.hdri_rot=QtWidgets.QDoubleSpinBox(); self.hdri_rot.setRange(-360,360); self.hdri_rot.setSingleStep(5); hf.addRow('Rotation (degrees)',self.hdri_rot)
            self.hdri_camera=QtWidgets.QCheckBox('Visible in camera'); self.hdri_camera.setChecked(True); hf.addRow(self.hdri_camera)
            self.hdri_replace=QtWidgets.QCheckBox('Replace selected / first existing Skydome'); self.hdri_replace.setChecked(True); hf.addRow(self.hdri_replace)
            b=QtWidgets.QPushButton('Import local EXR / HDR…'); b.clicked.connect(self.pick_local_hdri); hf.addRow(b)
            panel=self.detail.parentWidget().layout(); panel.insertWidget(panel.indexOf(self.detail),self.hdri_controls); self.hdri_controls.hide()
            self.hdri_res.currentIndexChanged.connect(self.update_details)
            # One visible search/category pair for all three tabs. The original
            # base-class fields remain hidden to preserve Local Library filtering.
            self.ph_search.setClearButtonEnabled(True)
            self.ph_search.textChanged.connect(self._shared_search_changed)
            self.ph_kind.currentIndexChanged.connect(self._shared_category_changed)
            self.ph_list.currentItemChanged.connect(self.on_selected)
            self.ph_list.itemDoubleClicked.connect(lambda _:self.run_import())
            self._quiet_text(self.ph_search,self.search.text())
            self._quiet_choice(self.ph_kind,self._online_category(self.category.currentText()))

        @staticmethod
        def _quiet_text(widget, text):
            if widget.text()==text:return
            was_blocked=widget.blockSignals(True)
            try:widget.setText(text)
            finally:widget.blockSignals(was_blocked)

        @staticmethod
        def _quiet_choice(widget, value):
            if widget.currentText()==value:return
            index=widget.findText(value)
            if index<0:return
            was_blocked=widget.blockSignals(True)
            try:widget.setCurrentIndex(index)
            finally:widget.blockSignals(was_blocked)

        @staticmethod
        def _online_category(value):
            return {'3D':'3D Models'}.get(value,value)

        @staticmethod
        def _local_category(value):
            return {'3D Models':'3D'}.get(value,value)

        def _shared_search_changed(self, text):
            self._quiet_text(self.search,text)
            if self.online():self.reset_page()
            else:self.rebuild()

        def _shared_category_changed(self, *_):
            self._quiet_choice(self.category,self._local_category(self.ph_kind.currentText()))
            if self.online():
                if not self.hdri_mode():self.reset_page()
            else:self.rebuild()

        def _move_search_bar(self, layout):
            # Reparent just the one search row rather than creating duplicate
            # QLineEdits. Search remains directly beneath the active tab bar.
            old=self.search_bar.parentWidget()
            if old is not None and old.layout() is not None:
                old.layout().removeWidget(self.search_bar)
            layout.insertWidget(0,self.search_bar)
            self.search_bar.show()  # Reparenting a QWidget can hide it until shown explicitly.

        def online(self):return self.native_ready and self.tabs.currentIndex() in (1,2)
        def hdri_mode(self):return self.native_ready and self.tabs.currentIndex()==2
        def source_changed(self,*_):
            # Keep the one search row immediately under whichever tab is active.
            # The term is preserved across Local / Assets / HDRIs.
            if self.online():
                layout=self.hdri_layout if self.hdri_mode() else self.online_layout
                layout.addWidget(self.online_content); self.online_content.show()
                self._move_search_bar(self.online_content_layout)
                self.ph_kind.setVisible(not self.hdri_mode())
                self.refresh_api_btn.setVisible(True)
                self.page=0; self.rebuild_online()
                if not self.catalog and self.catalog_job is None:self.load_catalog(False)
            else:
                self._move_search_bar(self.local_layout)
                self.ph_kind.setVisible(True)
                self.refresh_api_btn.setVisible(False) # Local: use the existing Refresh button.
                self.rebuild()
            self.on_selected()

        def open_standin_look_controller(self):
            if self._busy or self.jobs:
                QtWidgets.QMessageBox.information(self,'nTools',
                    '現在のダウンロードやインポートが完了してから開いてください。')
                return
            try:
                from ntools.tools import standin_look_controller
                # The source may have been hot-updated since it was first read.
                # The controller is opened on demand, not left running in background.
                import importlib
                old_dialog=getattr(standin_look_controller,'_WINDOW',None)
                if old_dialog is not None:
                    try:
                        old_dialog.close()
                        old_dialog.deleteLater()
                    except RuntimeError:
                        pass
                importlib.reload(standin_look_controller)
                standin_look_controller.show(self)
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self,'Stand-in Look Controller',str(exc))

        def setup_scene_plant_sss(self):
            if self._busy or self.jobs:
                return
            message = ('シーン内の草・葉と推定できるOpenPBRマテリアルに、'
                       'Diffuse → aiColorCorrect → Subsurface Colorを追加します。\n\n'
                       '既存のSSS接続、Weight、Thin Walledは変更しません。\n'
                       '名前で判別できない素材はスキップします。\n'
                       '実行前にシーンを保存してください。\n\n実行しますか？')
            answer = QtWidgets.QMessageBox.question(
                self, '植物SSSを既存マテリアルに追加', message,
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No)
            if answer != QtWidgets.QMessageBox.Yes:
                return
            self._busy = True
            try:
                changed, skipped = add_plant_sss_to_scene_materials(self.log)
                QtWidgets.QMessageBox.information(
                    self, '植物SSS設定の結果',
                    '追加: %d 件 / スキップ: %d 件\n'
                    'SSS Weightは変更していません。必要に応じて調整してください。' % (changed, skipped))
            except Exception as e:
                self.log('Plant SSS error: '+str(e))
                QtWidgets.QMessageBox.warning(self,'植物SSS設定に失敗',str(e))
            finally:
                self._busy = False

        def repair_paths(self):
            if self._busy:return
            answer=QtWidgets.QMessageBox.question(self,'Repair texture paths','Copy ordinary file textures into the current project and repath them? Existing files and materials will not be deleted. Save your scene afterward.')
            if answer!=QtWidgets.QMessageBox.Yes:return
            self._busy=True
            try:
                n,skipped=repair_scene_textures(self.log)
                QtWidgets.QMessageBox.information(self,'Repair complete','Updated %d paths; %d skipped. Check the log and save the scene.'%(n,len(skipped)))
            except Exception as e:self.log('Repair error: '+str(e))
            finally:self._busy=False; self.on_selected()

        def pick_local_hdri(self):
            if self._busy or self.jobs:return
            path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Choose HDRI',str(self.cache/'HDRIs'),'HDRI (*.exr *.hdr)')
            if path and confirm_project_copy(self, True):
                try:import_hdri(path,self.snapshot_settings(),self.log)
                except Exception as e:self.log('HDRI error: '+str(e)); QtWidgets.QMessageBox.warning(self,'HDRI import failed',str(e))


        def refresh(self):
            if not getattr(self,'native_ready',False) or self._busy:return
            self._busy=True; self.status.setText('Scanning local library…')
            try:
                items={}; self.icon_cache={}
                for root in self.roots:
                    try:
                        for a in scan_library(root):
                            if a.source!='Megascans': items[str(a.folder)]=a
                    except Exception as e:self.log('Scan warning: '+str(e))
                for root,source in [(self.cache/'PolyHaven','Poly Haven')]:
                    if not root.exists():continue
                    for p in root.iterdir():
                        if p.is_dir() and not p.name.startswith('.'):
                            try:items[str(p.resolve())]=cached_asset(p,source)
                            except Exception as e:self.log('Cache warning: '+p.name+' '+str(e))
                self.assets=sorted(items.values(),key=lambda a:(a.name.lower(),str(a.folder))); self.rebuild()
            finally:self._busy=False

        def online_slug(self):
            item=self.ph_list.currentItem() if self.native_ready else None
            return item.data(QtCore.Qt.UserRole) if item else None

        def on_selected(self,*args):
            if hasattr(self,'hdri_controls'):
                self.hdri_controls.setVisible(self.hdri_mode())
                for w in (self.res,self.normal,self.disp,self.copy):w.setEnabled(not self.hdri_mode())
                self.toggle_displacement(self.disp.isChecked() and not self.hdri_mode())
            if not self.online():
                super(NativeBrowser,self).on_selected(*args); self.import_btn.setText('IMPORT / CREATE OPENPBR'); return
            slug=self.online_slug(); m=self.catalog.get(slug,{})
            self._reset_standin_for_selection(('online', slug) if slug else None)
            self.family.blockSignals(True); self.family.clear(); self.family.addItem('Auto (FBX)',None); self.family.blockSignals(False); self.family.setEnabled(False)
            is_model=m.get('type')==2; self.lod.setEnabled(is_model); self.proxy.setEnabled(is_model); self.assign.setEnabled(m.get('type')==1); self.split_standin.setEnabled(is_model)
            enabled=bool(slug) and not self.jobs and not self._busy
            self.import_btn.setText('DOWNLOAD & CREATE SKYDOME' if self.hdri_mode() else 'DOWNLOAD & IMPORT'); self.import_btn.setEnabled(enabled); self.cache_btn.setEnabled(enabled)
            self.asset_label.setText(m.get('name','Select a Poly Haven asset'))
            item=self.ph_list.currentItem(); pm=item.icon().pixmap(290,150) if item else QtGui.QPixmap()
            if not pm.isNull():self.preview.setPixmap(pm)
            else:self.preview.clear(); self.preview.setText('Poly Haven')
            self.update_details()

        def update_details(self,*args):
            if not self.online():return super(NativeBrowser,self).update_details(*args)
            slug=self.online_slug(); m=self.catalog.get(slug,{})
            if not slug:self.detail.clear();return
            if self.hdri_mode():
                self.detail.setPlainText(str(m.get('description',''))+'\n\nID: '+slug+'\nEXR HDRI: '+self.hdri_res.currentText()+' (nearest available if missing)\nCopies to project sourceimages/AssetBrowser/HDRIs.'); return
            self.detail.setPlainText(str(m.get('description',''))+'\n\nID: '+slug+'\nCategory: '+str(m.get('category',m.get('categories','')))+'\nResolution: '+self.res.currentText()+' (nearest available if missing)\nFBX if available; LOD selection only for files with LOD labels.\nDownload & Import uses current settings. Surface assets create material only unless Assign is enabled.')

        def load_catalog(self,force=False):
            if self.catalog_job is not None:return
            self.page_label.setText('Loading official API…'); self.catalog_job=self.pool.submit(ph_catalog,self.cache,force)

        def reset_page(self,*_):self.page=0; self.rebuild_online()
        def change_page(self,delta):self.page=max(0,self.page+delta); self.rebuild_online()
        def rebuild_online(self):
            for f in self.thumb_jobs.values():f.cancel()
            self.thumb_jobs={}; self.ph_list.clear(); words=self.ph_search.text().lower().split(); kind=self.ph_kind.currentText()
            filtered=[]
            for slug,m in self.catalog.items():
                text=' '.join([slug.replace('_',' '),str(m.get('name','')),str(m.get('tags','')),str(m.get('category','')),str(m.get('categories','')),str(m.get('description',''))]).lower()
                if not all(w in text for w in words):continue
                if self.hdri_mode()!=(m['type']==0):continue
                if not self.hdri_mode() and kind=='3D Models' and m['type']!=2:continue
                if not self.hdri_mode() and kind=='Surfaces' and m['type']!=1:continue
                if not self.hdri_mode() and kind=='Plants' and (m['type']!=2 or not re.search(r'plant|vegetation|foliage|tree|grass|fern|flower|shrub',text)):continue
                filtered.append((slug,m))
            filtered.sort(key=lambda x:(-int(x[1].get('download_count') or 0),x[0]))
            pages=max(1,(len(filtered)+self.page_size-1)//self.page_size); self.page=min(self.page,pages-1)
            for slug,m in filtered[self.page*self.page_size:(self.page+1)*self.page_size]:
                item=QtWidgets.QListWidgetItem(m.get('name',slug)+'\n'+('HDRI' if m['type']==0 else ('Model' if m['type']==2 else 'Surface'))); item.setData(QtCore.Qt.UserRole,slug); item.setToolTip(slug); self.ph_list.addItem(item)
                self.thumb_jobs[slug]=self.thumb_pool.submit(ph_thumbnail,slug,m,self.cache)
            self.page_label.setText('%d / %d pages  ·  %d assets'%(self.page+1,pages,len(filtered))); self.prev_btn.setEnabled(self.page>0); self.next_btn.setEnabled(self.page+1<pages)
            if self.ph_list.count():self.ph_list.setCurrentRow(0)
            self.on_selected()

        def open_poly_page(self):
            slug=self.online_slug()
            if slug:QtGui.QDesktopServices.openUrl(QtCore.QUrl('https://polyhaven.com/a/'+quote(slug)))

        def run_import(self):
            if self.online():self.start_poly(True)
            else:
                a=self.selected()
                if not a or self._busy:return
                if not a.meshes and self.assign.isChecked() and not selected_mesh_members()[0]:
                    QtWidgets.QMessageBox.warning(self,'マテリアルアサイン先の確認',SELECTION_REQUIRED); return
                if confirm_project_copy(self,self.copy.isChecked()):
                    super(NativeBrowser,self).run_import()
                else:
                    self.proxy.setChecked(False)
                    self.split_standin.setChecked(False)

        def snapshot_settings(self):
            s=self.settings(); s['family']=None
            s.update(hdri_res=int(self.hdri_res.currentText()[:-1]),exposure=self.hdri_exp.value(),rotation=self.hdri_rot.value(),camera=self.hdri_camera.isChecked(),replace_hdri=self.hdri_replace.isChecked())
            s['_selection']=cmds.ls(selection=True,long=True) or []
            s['_scene']=cmds.file(query=True,sceneName=True) or ''
            s['_workspace']=str(workspace_root())
            return s

        def start_poly(self,auto):
            slug=self.online_slug()
            if not slug or self.jobs or self._busy:return
            if auto and self.catalog[slug]['type']==1 and self.assign.isChecked() and not selected_mesh_members()[0]:
                QtWidgets.QMessageBox.warning(self,'マテリアルアサイン先の確認',SELECTION_REQUIRED); return
            if auto and not confirm_project_copy(self, self.hdri_mode() or self.copy.isChecked()):return
            s=self.snapshot_settings()
            if auto and self.catalog[slug]['type']==2 and not s['standin']:
                hint=heavy_asset_hint(catalog_meta=self.catalog[slug])
                if hint['warn']:
                    choice=standin_warning(self,hint['reason'],s)
                    if choice=='cancel':return
                    s['_heavy_confirmed']=True
                    if choice=='standin':s['standin']=True
            s['_parent']=self
            self.cancel=threading.Event()
            if self.catalog[slug]['type']==0:
                self.jobs.append(('hdri',self.pool.submit(ph_acquire_hdri,slug,self.catalog[slug],s['hdri_res'],self.cache,self.cancel,self.messages.put),s,auto))
            else:self.jobs.append(('poly',self.pool.submit(ph_acquire,slug,self.catalog[slug],s['resolution'],s['lod'],self.cache,self.cancel,self.messages.put),s,auto))
            self.proxy.setChecked(False)  # Queue captured its settings; next asset defaults to editable.
            self.split_standin.setChecked(False)  # Do not carry split-ASS into the next asset.
            self.cancel_btn.setEnabled(True); self.on_selected(); self.log('Queued Poly Haven: '+slug)

        def cancel_download(self):self.cancel.set(); self.log('Cancel requested; partial download will be discarded.')

        def import_ready(self,a,s):
            if self._busy:return
            if not s['standin'] and not s.get('_heavy_confirmed') and a.meshes:
                mesh=choose_mesh(a,s['lod'],s.get('family'))
                hint=heavy_asset_hint(a,mesh)
                if hint['warn']:
                    choice=standin_warning(self,hint['reason'],s)
                    if choice=='cancel':return
                    s['_heavy_confirmed']=True
                    if choice=='standin':s['standin']=True
            s['_parent']=self
            self._busy=True; self.import_btn.setEnabled(False)
            try:
                import_asset(a,s,self.mapping,self.log)
                self.log('Import finished: '+a.name)
                mapping_summary(s,self.log,self)
            except SelectionRequiredError as e:self.log(str(e)); QtWidgets.QMessageBox.warning(self,'マテリアルアサイン先の確認',str(e))
            except UserCancelled as e:self.log('Cancelled: '+str(e))
            except Exception as e:self.log('IMPORT ERROR: '+str(e)); self.log(traceback.format_exc()); QtWidgets.QMessageBox.warning(self,'Import failed',str(e))
            finally:
                self._busy=False
                self.proxy.setChecked(False)
                self.split_standin.setChecked(False)
                self.on_selected()
        def tick_native(self):
            if self.closing or self._busy:return
            while True:
                try:self.log(self.messages.get_nowait())
                except queue.Empty:break
            if self.catalog_job and self.catalog_job.done():
                f=self.catalog_job; self.catalog_job=None
                try:self.catalog,stale=f.result(); self.rebuild_online(); self.log('Poly Haven: '+str(len(self.catalog))+' entries'+(' (offline cached catalog)' if stale else ''))
                except Exception as e:self.page_label.setText('API unavailable — Refresh API to retry'); self.log('Catalog error: '+str(e))
            for slug,f in list(self.thumb_jobs.items()):
                if not f.done():continue
                del self.thumb_jobs[slug]
                try:
                    pm=QtGui.QPixmap(); pm.loadFromData(f.result())
                    if pm.isNull():continue
                    for i in range(self.ph_list.count()):
                        item=self.ph_list.item(i)
                        if item.data(QtCore.Qt.UserRole)==slug:
                            item.setIcon(QtGui.QIcon(pm)); break
                    if self.online() and self.online_slug()==slug:self.preview.setPixmap(pm.scaled(290,150,QtCore.Qt.KeepAspectRatio,QtCore.Qt.SmoothTransformation))
                except Exception:pass
            if self.jobs and self.jobs[0][1].done():
                kind,f,s,auto=self.jobs.pop(0)
                if kind in ('poly','hdri'):self.cancel_btn.setEnabled(False)
                try:
                    a=f.result(); self.log('Ready: '+a.name+' | '+str(a if kind=='hdri' else a.folder)); self.refresh()
                    same_scene=(cmds.file(query=True,sceneName=True) or '')==s.get('_scene') and str(workspace_root())==s.get('_workspace')
                    if auto and same_scene and not (kind in ('poly','hdri') and self.cancel.is_set()):
                        if kind=='hdri':import_hdri(a,s,self.log)
                        else:self.import_ready(a,s)
                    else:self.log(('HDRI saved in cache; use Import local EXR / HDR or select it online again.' if kind=='hdri' else 'Saved in Local Library; select it to import.')+(' Scene/project changed; automatic import skipped.' if auto and not same_scene else ''))
                except Exception as e:self.log('Acquisition error: '+str(e)); self.log(traceback.format_exc())
                self.on_selected()

        def closeEvent(self,event):
            if self._busy:event.ignore(); return
            if self.jobs:
                answer=QtWidgets.QMessageBox.question(self,'Close browser?','A download is active. Cancel pending tasks and close?')
                if answer!=QtWidgets.QMessageBox.Yes:event.ignore();return
            self.closing=True; self.timer.stop(); self.cancel.set(); self.pool.shutdown(wait=False,cancel_futures=True); self.thumb_pool.shutdown(wait=False,cancel_futures=True); event.accept()

_NATIVE_WINDOW=None

def show():
    global _NATIVE_WINDOW
    if cmds is None or QtWidgets is None:raise RuntimeError('Run inside Maya with PySide6 or PySide2.')
    for widget in QtWidgets.QApplication.topLevelWidgets():
        if widget.objectName() in ('MayaNativeAssetBrowserV3','MayaNativeAssetBrowserV4','PolyHavenAssetBrowserV5','PolyHavenAssetBrowserV51'):
            if not widget.close():return widget
            widget.deleteLater()
    ptr=omui.MQtUtil.mainWindow(); parent=wrapInstance(int(ptr),QtWidgets.QWidget) if ptr else None
    _NATIVE_WINDOW=NativeBrowser(parent); _NATIVE_WINDOW.show(); _NATIVE_WINDOW.raise_(); _NATIVE_WINDOW.activateWindow(); return _NATIVE_WINDOW

if __name__=='__main__' and cmds is not None:
    show()
