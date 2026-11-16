# -*- coding: utf-8 -*-
"""Material Creator v1.3.
Paste into Maya Python Script Editor, or import material_creator; call show().
Create OpenPBR materials from a local texture folder or JSON; no model import.
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

VERSION = '1.3'
MESH_EXT = {'.fbx', '.obj'}
IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.exr', '.tga', '.bmp', '.tx', '.hdr', '.webp'}
SKIP_DIRS = {'.git', '__pycache__', 'node_modules', 'maya_asset_browser', 'standins', 'sourceimages'}
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
    def __init__(self, folder, files, use_metadata=True):
        self.folder = folder; self.files = sorted(set(files))
        self.meshes = [p for p in self.files if p.suffix.lower() in MESH_EXT]
        self.metadata = metadata_info([p for p in self.files if p.suffix.lower()=='.json'], self.files) if use_metadata else {'name':None,'category':'','roles':{},'normal_dx':False}
        self.name = self.metadata['name'] or folder.name
        ph_roles={}
        marker=folder/'native_asset_info.json'
        if use_metadata and marker.is_file():
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
    plant_leaf=bool(re.search(r'(^|_)(leaf|leaves|foliage|grass|fern|petal|flower|atlas)(_|$)',key))
    thin=plant_leaf or (asset.category=='Plants' and opacity and not re.search(r'(^|_)(bark|trunk|branch|wood)(_|$)',key))
    if thin: set_if(mat,'geometryThinWalled',True)
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
    return {'mat':mat,'sg':sg,'opacity':opacity,'displaced':displaced}


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


# ---------------- Megascans material-only input and UI ----------------
class JsonMaterialError(ValueError):
    """JSON cannot describe a usable material; folder-only scan is allowed."""


def find_folder_json(folder):
    """Only descriptors immediately in the selected folder; no other assets."""
    root=Path(folder).expanduser()
    if not root.is_dir(): return []
    return sorted((p for p in root.iterdir() if p.is_file() and not p.is_symlink()
                   and p.suffix.lower()=='.json'), key=lambda p:p.name.casefold())


def texture_files(root):
    files=[]
    for directory,dirs,names in os.walk(str(root),followlinks=False):
        dirs[:]=sorted(d for d in dirs if not d.startswith('.') and d.lower() not in SKIP_DIRS and not (Path(directory)/d).is_symlink())
        for name in names:
            f=Path(directory)/name
            if not f.is_symlink() and f.suffix.lower() in IMAGE_EXT:files.append(f)
    return sorted(files)


def fab_catalog_roles(data, files, root):
    """Resolve Fab's multi-tier catalog against the *downloaded* package.

    URI matches win; renamed delivery files require the asset ID AND a
    declared map role. Never transfer catalog resolution/tier/scale to a
    different physical file. A catalog lists alternatives, not requirements.
    """
    from urllib.parse import unquote, urlsplit
    ident = normalized(data.get('id', ''))
    if not ident or not isinstance(data.get('maps'), list):
        return None
    records = [m for m in data['maps'] if isinstance(m, dict)
               and isinstance(m.get('uri'), str) and isinstance(m.get('type'), str)]
    # Only enable relaxed matching for an identifiable tiered Megascans
    # catalog, not arbitrary user-authored material JSON.
    if not records or not any(isinstance(m.get('tier'), int) for m in records):
        return None
    declared = defaultdict(list)
    for m in records:
        role = ALIAS_ROLE.get(normalized(m['type']))
        if role:
            if role == 'normal_gl' and any('directx' in str(m.get(k, '')).lower() for k in ('format','normalFormat','convention','space')):
                role = 'normal_dx'
            declared[role].append(m)
    if not declared.get('base'):
        raise JsonMaterialError('Fab JSONにBase Colorのマップ定義がありません。')
    by_rel = defaultdict(list); by_name = defaultdict(list)
    for f in files:
        by_rel[f.relative_to(root).as_posix().casefold()].append(f)
        by_name[f.name.casefold()].append(f)
    roles = {}; notes = []; exact = set()
    def add(f, role):
        if f in roles and roles[f] != role:
            raise JsonMaterialError('同じ画像に異なるマップ種別が指定されています: '+f.name)
        roles[f] = role
    for role, entries in declared.items():
        for m in entries:
            uri = unquote(m['uri'].split('?', 1)[0].replace('\\', '/'))
            if '://' in uri: uri = urlsplit(uri).path
            uri = uri.lstrip('/')
            hits = by_rel.get(uri.casefold(), [])
            if not hits:
                # Permit a unique basename if the actual explicitly numbered
                # tier does not contradict the catalog tier.
                hits = [f for f in by_name.get(uri.rsplit('/',1)[-1].casefold(), [])
                        if tier_of(f, root) in (None, m.get('tier'))]
            if len(hits) == 1:
                f=hits[0]
                named,_=classify(f)
                add(f, 'normal_dx' if role=='normal_gl' and named=='normal_dx' else role)
                exact.add(f)
    # Fab distribution ZIPs can flatten and rename every file. Only use
    # files carrying the exact asset ID token and a JSON-declared semantic.
    # Keep actual quality families independent (High != Tier 1, etc.).
    def same_id(f):
        return re.search(r'(?<![a-z0-9])'+re.escape(ident)+r'(?![a-z0-9])', normalized(f.stem)) is not None
    for f in files:
        if f in exact or not same_id(f) or PREVIEW_RE.search(normalized(f.stem)):
            continue
        role,key=classify(f)
        if role in declared or (role=='normal_dx' and 'normal_gl' in declared):
            add(f,role)
            notes.append('Fab catalog match (asset ID + map type): '+f.relative_to(root).as_posix())
    if not any(r=='base' for r in roles.values()):
        raise JsonMaterialError('Fab JSONのアセットID '+ident+' に一致するBase Colorがありません。JSONのURIまたは同じIDを含む実ファイルを確認してください。')
    if notes:
        notes.insert(0,'Fab package: JSON map semantics retained; actual file resolution/quality used. High/Medium/Low are not assumed to equal numbered tiers.')
    missing=[r for r in declared if r not in roles.values() and not (r=='normal_gl' and 'normal_dx' in roles.values())]
    if missing:
        notes.append('Catalog maps not included in this download (optional): '+', '.join(sorted(missing)))
    return roles,notes


def fab_texture_key(f,root):
    """Include folder quality labels when they are absent from the filename."""
    _,key=classify(f)
    if not key: return None
    for part in reversed(f.relative_to(root).parts[:-1]):
        q=re.fullmatch(r'(raw|high|medium|low)', normalized(part))
        if q:
            if q.group(1) not in key.split('_'): key += '_'+q.group(1)
            break
    return key


def descriptor_roles(path, files, root):
    """Resolve only explicit local texture references in the chosen JSON.
    Never silently interpret an invalid descriptor as a successful JSON scan.
    """
    from urllib.parse import unquote, urlsplit
    try:
        if path.stat().st_size > 8*1024*1024: raise JsonMaterialError('JSONが8MBを超えています。')
        data=json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError, ValueError) as e:
        raise JsonMaterialError('JSONの読み込み・構文エラー: '+str(e)) from e
    if not isinstance(data,(dict,list)):
        raise JsonMaterialError('JSONのルートがオブジェクトまたは配列ではありません。')
    if isinstance(data,dict):
        fab=fab_catalog_roles(data,files,root)
        if fab is not None:
            roles,notes=fab
            return data,roles,notes,True
    by_name=defaultdict(list)
    for f in files: by_name[f.name.casefold()].append(f)
    roles={}; declared=defaultdict(list); unresolved=defaultdict(list)
    role_fields=('type','mapType','textureType','semantic','channel','name','componentType')
    def role_of(value):
        if not isinstance(value,str):return None
        k=normalized(value)
        return ALIAS_ROLE.get(k) or ( 'base' if re.fullmatch(r'(?:col|color|colour)_?\d+',k) else None)
    def resolve(value):
        value=unquote(value.split('?',1)[0].replace('\\','/'))
        if '://' in value:value=urlsplit(value).path
        parts=[x for x in value.split('/') if x not in ('','.')] 
        if not parts or Path(parts[-1]).suffix.lower() not in IMAGE_EXT:return None,False
        hits=by_name.get(parts[-1].casefold(),[])
        if len(hits)==1:return hits[0],True
        if len(hits)>1:
            for count in range(min(len(parts),max(len(f.relative_to(root).parts) for f in hits)),1,-1):
                tail=[x.casefold() for x in parts[-count:]]
                matches=[f for f in hits if [x.casefold() for x in f.relative_to(root).parts[-count:]]==tail]
                if len(matches)==1:return matches[0],True
        return None,True
    def visit(v,inherited=None):
        if isinstance(v,list):
            for item in v:visit(item,inherited)
        elif isinstance(v,dict):
            role=next((r for k in role_fields for r in [role_of(v.get(k))] if r),inherited)
            if role=='normal_gl' and any('directx' in str(v.get(k,'')).lower() for k in ('format','normalFormat','convention','space')):role='normal_dx'
            for k,val in v.items():visit(val,role_of(k) or role)
        elif isinstance(v,str):
            f,is_image=resolve(v)
            if not is_image:return
            role=inherited
            if not role:
                role,_=classify(Path(unquote(v.split('?',1)[0].replace('\\','/'))))
            if not role:return
            # Generic 'normal' descriptors may still identify DirectX in the filename.
            named,_=classify(Path(unquote(v.split('?',1)[0].replace('\\','/'))))
            if role=='normal_gl' and named=='normal_dx':role='normal_dx'
            declared[role].append(v)
            if f is None:unresolved[role].append(v);return
            if f in roles and roles[f]!=role:
                raise JsonMaterialError('同じ画像に異なるマップ種別が指定されています: '+f.name+' ('+roles[f]+' / '+role+')')
            roles[f]=role
    visit(data)
    if not any(r=='base' for r in roles.values()):
        detail=' / '.join(unresolved.get('base',[])[:4])
        raise JsonMaterialError('JSONから使用可能なBase Color画像を特定できません。'+(' 見つからない画像: '+detail if detail else ' Base Colorの参照またはマップ種別がありません。'))
    missing=[r for r in declared if r not in roles.values()]
    if missing:
        detail='\n'.join(r+': '+', '.join(unresolved[r][:3]) for r in missing)
        raise JsonMaterialError('JSONに指定されたマップの画像が見つからない、または同名ファイルが複数あります。\n'+detail)
    return data,roles,[],False


def load_megascans_input(path, json_mode=False):
    """JSON mode is explicit; folder mode never reads JSON, including markers."""
    p=Path(path).expanduser().resolve()
    if json_mode:
        if not p.is_file() or p.suffix.lower()!='.json':
            raise JsonMaterialError('JSONファイルを指定してください。')
        root=p.parent
    else:
        if not p.is_dir():raise ValueError('テクスチャフォルダを指定してください。')
        root=p
    files=texture_files(root)
    asset=Asset(root,files,use_metadata=False)
    asset.json_path=p if json_mode else None
    asset.json_notes=[]
    if json_mode:
        data,roles,asset.json_notes,is_fab=descriptor_roles(p,files,root)
        if isinstance(data,dict):
            asset.name=next((data[k] for k in ('name','title','assetName','displayName') if isinstance(data.get(k),str) and data[k].strip()),root.name)
        # Explicit role takes precedence over filename. Preserve distinct named
        # material families; anonymous names join a single unambiguous base set.
        base_keys={(fab_texture_key(f,root) if is_fab else classify(f)[1]) for f,r in roles.items() if r=='base' and classify(f)[0]=='base'}
        common=next(iter(base_keys)) if len(base_keys)==1 else 'default'
        asset.textures=defaultdict(lambda: defaultdict(list))
        asset.unknown=[f for f in files if f not in roles]
        for f,role in sorted(roles.items()):
            named_role,key=classify(f)
            if is_fab and key: key=fab_texture_key(f,root)
            key=key if named_role and (named_role==role or {named_role,role}<={'normal_gl','normal_dx'}) else common
            asset.textures[key][role].append(Texture(f,root,role,key))
        # JSON references can have a shared but differently named map family.
        # Merge only if there is exactly one base family; never guess between bases.
        bases=[k for k,r in asset.textures.items() if r.get('base')]
        if len(bases)==1 and not is_fab:
            dst=asset.textures[bases[0]]
            for k in list(asset.textures):
                if k!=bases[0] and not any(r in dst for r in asset.textures[k]):
                    for r,ts in asset.textures.pop(k).items():dst[r].extend(ts)
        if is_fab:
            # A catalog may mention variants with no local base map; do not
            # merge their channels into a different download.
            for k in list(asset.textures):
                if not asset.textures[k].get('base'): del asset.textures[k]
        asset.metadata['roles']=roles
    root_tier=TIER_RE.search(root.name)
    for roles in asset.textures.values():
        for textures in roles.values():
            for t in textures:
                if t.tier is None and root_tier:t.tier=int(root_tier.group(1))
    asset.source='Megascans'
    if not any(r.get('base') for r in asset.textures.values()):
        raise (JsonMaterialError if json_mode else ValueError)('Base Colorとして認識できる画像がありません。')
    return asset


def megascans_maps(asset,key,resolution,wanted_tier=None):
    """Choose one tier with usable base color; no mixing incompatible tiers."""
    roles=asset.textures[key]
    tiers=sorted({t.tier for ts in roles.values() for t in ts if t.tier is not None})
    def filtered(tier):
        return {r:[t for t in ts if t.tier==tier] for r,ts in roles.items()}
    if wanted_tier is not None:
        if wanted_tier not in tiers:
            raise ValueError('指定したTier '+str(wanted_tier)+'のテクスチャがありません。Autoを選択してください。')
        tier=wanted_tier
    elif tiers:
        # Tier 0 is preferred only when it actually supplies base color.
        tier=next((t for t in tiers if filtered(t).get('base')),tiers[0])
        if not filtered(tier).get('base') and filtered(None).get('base'):tier=None
    else:tier=None
    # Unlabelled files may be shared across tiers, but never import another
    # explicitly numbered tier's maps. Prefer same-tier files first.
    chosen={}
    for role,ts in roles.items():
        candidates=[t for t in ts if t.tier==tier] or ([t for t in ts if t.tier is None] if tier is not None else [])
        if candidates:chosen[role]=pick_texture(candidates,resolution,tier)
    return tier,chosen


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


class MaterialBuildError(RuntimeError):
    def __init__(self, reason, rolled_back):
        super().__init__(str(reason)); self.rolled_back=rolled_back


def create_megascans_material(asset,key,settings,tier=None,log=print):
    members,shapes=selected_mesh_members() if settings['assign'] else ([],[])
    if settings['assign'] and not members:
        raise SelectionRequiredError(SELECTION_REQUIRED)
    tier,maps=megascans_maps(asset,key,settings['resolution'],tier)
    if not maps.get('base'):
        raise ValueError('Base Colorが見つかりません。フォルダ、JSON、Tier、テクスチャセットを確認してください。')
    for t in maps.values():
        if not t.path.is_file() or t.path.stat().st_size==0:
            raise ValueError('テクスチャが存在しないか空です: '+str(t.path))
    ensure_arnold()
    if 'openPBRSurface' not in (cmds.allNodeTypes() or []):raise RuntimeError('openPBRSurfaceが利用できません。Maya 2027で実行してください。')
    # Restrict build_material to the chosen maps, so it cannot fall back to
    # another Tier independently for a missing channel.
    import copy
    selected_asset=copy.copy(asset)
    selected_asset.textures={key:{r:[t] for r,t in maps.items()}}
    old_selection=cmds.ls(selection=True,long=True) or []
    namespace=cmds.namespaceInfo(currentNamespace=True)
    before=set(cmds.ls(long=True) or [])
    success=False; failure=None; rolled_back=False
    cmds.undoInfo(openChunk=True,chunkName='Material Creator')
    try:
        cmds.namespace(setNamespace=':')
        log('Texture set: '+key+' | '+('Tier '+str(tier) if tier is not None else 'No Tier label'))
        mat=build_material(selected_asset,key,settings,tier,None,log)
        if settings['assign']:
            cmds.sets(members,edit=True,forceElement=mat['sg'])
            for shape in shapes:setup_shape(shape,mat,settings)
            log('Assigned to '+str(len(shapes))+' mesh shape(s).')
        else:log('Material created only; no geometry or assignments changed.')
        if old_selection:cmds.select(old_selection,replace=True)
        else:cmds.select(clear=True)
        success=True
        return mat
    except Exception as e:
        failure=e
    finally:
        try:
            if cmds.namespace(exists=namespace):cmds.namespace(setNamespace=namespace)
        finally:cmds.undoInfo(closeChunk=True)
        if not success:
            if set(cmds.ls(long=True) or [])==before:
                rolled_back=True  # no created nodes; failure before graph creation
            elif cmds.undoInfo(query=True,state=True):
                try:
                    cmds.undo(); rolled_back=set(cmds.ls(long=True) or [])==before
                except Exception as e:log('WARNING: Undo failed: '+str(e))
    if failure is not None:raise MaterialBuildError(failure,rolled_back) from failure


if QtWidgets is not None:
    class MaterialCreator(QtWidgets.QDialog):
        def __init__(self,parent=None):
            super(MaterialCreator,self).__init__(parent)
            self.setObjectName('MaterialCreatorV13'); self.setWindowTitle('Material Creator | 1.3')
            self.resize(740,700); self.setMinimumSize(570,520)
            self._confirmed_copy_root=None; self.asset=None; self._busy=False; self._folder_choice=None
            layout=QtWidgets.QVBoxLayout(self); layout.setSpacing(9)
            title=QtWidgets.QLabel('MATERIAL CREATOR'); title.setStyleSheet('font-size:18px;font-weight:bold;'); layout.addWidget(title)
            layout.addWidget(QtWidgets.QLabel('OpenPBR / Arnold  |  Material only  |  Maya 2027'))
            form=QtWidgets.QFormLayout(); layout.addLayout(form)
            self.mode=QtWidgets.QComboBox(); self.mode.addItems(['Texture Folder','JSON File']); form.addRow('Input type',self.mode)
            row=QtWidgets.QHBoxLayout(); self.path=QtWidgets.QLineEdit(); self.path.setPlaceholderText('One asset texture folder'); row.addWidget(self.path,1)
            b=QtWidgets.QPushButton('Browse…'); b.clicked.connect(self.browse); row.addWidget(b)
            b=QtWidgets.QPushButton('Scan'); b.clicked.connect(self.scan); row.addWidget(b); form.addRow('Input path',row)
            self.mode.currentIndexChanged.connect(self.change_mode); self.path.textChanged.connect(self.invalidate); self.path.returnPressed.connect(self.scan)
            self.texture_set=QtWidgets.QComboBox(); self.texture_set.currentIndexChanged.connect(self.update_preview); form.addRow('Texture set',self.texture_set)
            self.tier=QtWidgets.QComboBox(); self.tier.addItem('Auto (prefer complete base color)',None); self.tier.currentIndexChanged.connect(self.update_preview); form.addRow('Texture Tier',self.tier)
            self.res=QtWidgets.QComboBox(); self.res.addItems(['1K','2K','4K','8K','16K']); self.res.setCurrentIndex(1); self.res.currentIndexChanged.connect(self.update_preview); form.addRow('Texture resolution',self.res)
            self.normal=QtWidgets.QComboBox(); self.normal.addItems(['Auto (file name)','OpenGL','DirectX']); form.addRow('Normal convention',self.normal)
            self.assign=QtWidgets.QCheckBox('Assign to Selection'); self.assign.setChecked(True); form.addRow(self.assign)
            self.copy=QtWidgets.QCheckBox('Copy textures to Maya project'); self.copy.setChecked(True); form.addRow(self.copy)
            self.disp=QtWidgets.QCheckBox('Enable Displacement'); self.disp.setChecked(False); form.addRow(self.disp)
            self.height=QtWidgets.QDoubleSpinBox(); self.height.setRange(0.001,10000); self.height.setDecimals(3); self.height.setValue(0.2); form.addRow('Height (scene units)',self.height)
            self.mid=QtWidgets.QDoubleSpinBox(); self.mid.setRange(-10000,10000); self.mid.setDecimals(3); self.mid.setValue(0.5); form.addRow('Height midpoint',self.mid)
            self.subdiv=QtWidgets.QSpinBox(); self.subdiv.setRange(0,8); self.subdiv.setValue(2); form.addRow('Subdivision iterations',self.subdiv)
            self.disp.toggled.connect(self.toggle_disp); self.toggle_disp(False)
            self.project_label=QtWidgets.QLabel(); self.project_label.setWordWrap(True); layout.addWidget(self.project_label)
            self.preview=QtWidgets.QPlainTextEdit(); self.preview.setReadOnly(True); self.preview.setPlaceholderText('Detected texture maps / selected files'); layout.addWidget(self.preview,1)
            self.import_btn=QtWidgets.QPushButton('CREATE OPENPBR / ASSIGN'); self.import_btn.setMinimumHeight(36); self.import_btn.clicked.connect(self.run_import); self.import_btn.setEnabled(False); layout.addWidget(self.import_btn)
            self.assign.toggled.connect(lambda on:self.import_btn.setText('CREATE OPENPBR / ASSIGN' if on else 'CREATE OPENPBR MATERIAL ONLY'))
            self.logbox=QtWidgets.QPlainTextEdit(); self.logbox.setReadOnly(True); self.logbox.setMaximumHeight(130); self.logbox.setPlaceholderText('Import log / warnings'); layout.addWidget(self.logbox)
            self.update_project()
        def log(self,text):self.logbox.appendPlainText(str(text)); print('[Material Creator] '+str(text))
        def update_project(self):self.project_label.setText('Current project: '+str(workspace_root()))
        def toggle_disp(self,on):
            for w in (self.height,self.mid,self.subdiv):w.setEnabled(on)
        def invalidate(self,*_):
            self.asset=None; self.import_btn.setEnabled(False); self.preview.clear()
            for w in (self.texture_set,self.tier):
                w.blockSignals(True); w.clear(); w.blockSignals(False)
        def change_mode(self,*_):
            self._folder_choice=None
            self.path.clear(); self.path.setPlaceholderText('Select asset JSON (textures must be nearby)' if self.mode.currentIndex()==1 else 'One asset texture folder'); self.invalidate()
        def set_input(self,mode,path):
            self.mode.blockSignals(True); self.mode.setCurrentIndex(mode); self.mode.blockSignals(False)
            self.path.setPlaceholderText('Select asset JSON (textures must be nearby)' if mode==1 else 'One asset texture folder')
            self.path.setText(str(path))
        def browse(self):
            start=self.path.text().strip() or str(workspace_root())
            if self.mode.currentIndex()==1:
                p,_=QtWidgets.QFileDialog.getOpenFileName(self,'Choose asset JSON',start,'JSON (*.json)')
            else:p=QtWidgets.QFileDialog.getExistingDirectory(self,'Choose texture folder',start)
            if p:
                self._folder_choice=None; self.path.setText(p); self.scan()
        def choose_folder_input(self,folder):
            candidates=find_folder_json(folder)
            if not candidates:return None
            if len(candidates)>1:
                name,ok=QtWidgets.QInputDialog.getItem(self,'JSONファイルを選択','複数のJSONが見つかりました。使用候補を選択してください（キャンセルでフォルダ解析）。',[p.name for p in candidates],0,False)
                if not ok:return None
                chosen=next(p for p in candidates if p.name==name)
            else:chosen=candidates[0]
            box=QtWidgets.QMessageBox(self); box.setWindowTitle('JSONファイルの確認'); box.setIcon(QtWidgets.QMessageBox.Question)
            box.setText(chosen.name+' というJsonファイルが見つかりました。\nこのJsonファイルの内容を基にマテリアルを構築してよろしいですか？')
            box.setStandardButtons(QtWidgets.QMessageBox.Yes|QtWidgets.QMessageBox.No)
            box.button(QtWidgets.QMessageBox.Yes).setText('はい'); box.button(QtWidgets.QMessageBox.No).setText('いいえ')
            box.setDefaultButton(QtWidgets.QMessageBox.Yes); box.setEscapeButton(QtWidgets.QMessageBox.No)
            reply=box.exec() if hasattr(box,'exec') else box.exec_()
            return chosen if reply==QtWidgets.QMessageBox.Yes else None
        def fallback_notice(self,reason):
            message='不具合内容：\n'+str(reason)+'\n\nこれが原因のためJsonは使用せずマテリアルを構築します。'
            self.log(message); QtWidgets.QMessageBox.warning(self,'JSONの使用を中止します',message)
        def install_asset(self,a,preferred=None,tier=None):
            self.asset=a
            keys=sorted(a.textures,key=lambda k:(not bool(a.textures[k].get('base')),k))
            self.texture_set.blockSignals(True); self.texture_set.clear(); self.texture_set.addItems(keys)
            if preferred in keys:self.texture_set.setCurrentText(preferred)
            self.texture_set.blockSignals(False)
            self.tier.blockSignals(True); self.tier.clear(); self.tier.addItem('Auto (prefer complete base color)',None)
            for t in sorted({t.tier for roles in a.textures.values() for ts in roles.values() for t in ts if t.tier is not None}):self.tier.addItem('Tier '+str(t),t)
            if tier is not None:
                idx=self.tier.findData(tier)
                if idx>=0:self.tier.setCurrentIndex(idx)
            self.tier.blockSignals(False); self.update_preview(); self.log('Scanned '+a.name+(' [JSON]' if a.json_path else ' [Folder only]'))
            for note in a.json_notes:self.log(note)
        def folder_fallback(self,folder,reason,preferred=None,tier=None,for_import=False):
            self.fallback_notice(reason)
            self._folder_choice=str(Path(folder).resolve())
            self.set_input(0,folder)
            a=load_megascans_input(folder,False)
            keys=[k for k,r in a.textures.items() if r.get('base')]
            if for_import and preferred not in keys and len(keys)>1:
                chosen,ok=QtWidgets.QInputDialog.getItem(self,'Texture set','JSONなしで使用するテクスチャセットを選択してください。',sorted(keys),0,False)
                if not ok:raise UserCancelled('フォルダ解析による作成を中止しました。')
                preferred=chosen
            self.install_asset(a,preferred,tier)
            if for_import:
                _,maps=megascans_maps(a,self.texture_set.currentText(),int(self.res.currentText()[:-1]),self.tier.currentData())
                if not maps.get('base'):
                    self.tier.setCurrentIndex(0)
                    self.log('JSONなしの解析では選択TierにBase ColorがないためAutoを使用します。')
            return a
        def scan(self):
            if self._busy:return
            self.invalidate()
            try:
                if not self.path.text().strip():raise ValueError('入力フォルダまたはJSONを指定してください。')
                p=Path(self.path.text().strip()).expanduser().resolve()
                json_mode=self.mode.currentIndex()==1
                if not json_mode and p.is_dir() and self._folder_choice!=str(p):
                    chosen=self.choose_folder_input(p)
                    self._folder_choice=str(p)
                    if chosen:
                        p=chosen; json_mode=True; self.set_input(1,p)
                try:a=load_megascans_input(p,json_mode)
                except Exception as e:
                    if not json_mode:raise
                    self.folder_fallback(p.parent,e); return
                self.install_asset(a)
            except Exception as e:self.log(str(e)); QtWidgets.QMessageBox.warning(self,'Scan failed',str(e))
        def update_preview(self,*_):
            if not self.asset or not self.texture_set.currentText():return
            try:
                tier,maps=megascans_maps(self.asset,self.texture_set.currentText(),int(self.res.currentText()[:-1]),self.tier.currentData())
                lines=['Asset: '+self.asset.name,'Input: '+('JSON '+self.asset.json_path.name if self.asset.json_path else 'Folder only (no JSON)'),'Tier: '+(str(tier) if tier is not None else 'not labelled'),'']
                for role,t in sorted(maps.items()):lines.append(role+' : '+str(t.path.relative_to(self.asset.folder))+' ['+(str(t.res)+'K' if t.res else 'unknown resolution')+']')
                if self.asset.json_notes:lines.extend(['','JSON matching:']+self.asset.json_notes)
                if not maps.get('base'):lines.append('\nWARNING: Base Color not found.')
                if self.asset.unknown:lines.append('\nUnclassified images: '+str(len(self.asset.unknown)))
                self.preview.setPlainText('\n'.join(lines)); self.import_btn.setEnabled((bool(maps.get('base')) or bool(self.asset.json_path)) and not self._busy)
            except Exception as e:self.preview.setPlainText(str(e)); self.import_btn.setEnabled(bool(self.asset.json_path) and not self._busy)
        def run_import(self):
            if self._busy or not self.asset:return
            self.update_project()
            if self.assign.isChecked() and not selected_mesh_members()[0]:
                QtWidgets.QMessageBox.warning(self,'マテリアルアサイン先の確認',SELECTION_REQUIRED); return
            if not confirm_project_copy(self,self.copy.isChecked()):return
            settings=dict(resolution=int(self.res.currentText()[:-1]),normal=self.normal.currentText(),assign=self.assign.isChecked(),copy=self.copy.isChecked(),displacement=self.disp.isChecked(),height=self.height.value(),mid=self.mid.value(),subdiv=self.subdiv.value())
            self._busy=True; self.import_btn.setEnabled(False)
            try:
                asset=self.asset; key=self.texture_set.currentText(); tier=self.tier.currentData()
                try:
                    mat=create_megascans_material(asset,key,settings,tier,self.log)
                except Exception as e:
                    # Retry only when JSON was used and the failed graph was
                    # rolled back (or validation failed before creating nodes).
                    safe=(isinstance(e,MaterialBuildError) and e.rolled_back) or isinstance(e,(ValueError,FileNotFoundError))
                    if not asset.json_path:raise
                    if not safe:
                        if isinstance(e,MaterialBuildError):
                            raise RuntimeError(str(e)+'\n\n失敗した処理を安全に元に戻せなかったため、自動再試行を中止しました。Undoを確認してからTexture Folderで再実行してください。') from e
                        raise
                    self.folder_fallback(asset.folder,e,key,tier,for_import=True)
                    mat=create_megascans_material(self.asset,self.texture_set.currentText(),settings,self.tier.currentData(),self.log)
                self.log('Finished: '+mat['mat'])
            except UserCancelled as e:self.log(str(e))
            except SelectionRequiredError as e:QtWidgets.QMessageBox.warning(self,'マテリアルアサイン先の確認',str(e))
            except Exception as e:self.log(traceback.format_exc()); QtWidgets.QMessageBox.warning(self,'Import failed',str(e))
            finally:self._busy=False; self.update_preview()

_WINDOW=None

def show():
    global _WINDOW
    if cmds is None or QtWidgets is None:raise RuntimeError('Run inside Maya with PySide6 or PySide2.')
    for w in QtWidgets.QApplication.topLevelWidgets():
        if w.objectName() in ('MaterialCreatorV13','MaterialCreatorV12','MaterialCreatorV11','MegascansMaterialImporterV1'):
            w.close(); w.deleteLater()
    ptr=omui.MQtUtil.mainWindow(); parent=wrapInstance(int(ptr),QtWidgets.QWidget) if ptr else None
    _WINDOW=MaterialCreator(parent); _WINDOW.show(); _WINDOW.raise_(); _WINDOW.activateWindow(); return _WINDOW

if __name__=='__main__' and cmds is not None:
    show()
