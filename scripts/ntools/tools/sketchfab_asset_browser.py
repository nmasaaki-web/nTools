# -*- coding: utf-8 -*-
"""Sketchfab Asset Browser v1.2 (Windows/macOS, static glTF, Maya 2025+ OpenPBR).
Run entire file in Maya Python Script Editor, or import and call show().
No third-party Python packages. Sketchfab API token belongs to each user.
"""
import os, re, json, struct, base64, zipfile, shutil, tempfile, urllib.request, urllib.parse
import sys, subprocess, math
from pathlib import Path
import maya.cmds as c
import maya.api.OpenMaya as om

API = 'https://api.sketchfab.com/v3/'
WIN = 'SketchfabAssetBrowserV1'

def safe(s):
    return re.sub(r'[^a-zA-Z0-9_]', '_', str(s))[:80] or 'asset'

# On macOS, use the OS-provided curl rather than Maya's embedded SSL library.
# Keep certificate and hostname checks enabled on both platforms.
USER_AGENT = 'MayaSketchfabAssetBrowser/1.2'
MAC_CURL = '/usr/bin/curl'

def https_url(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('Only HTTPS URLs without embedded credentials are supported.')
    if any(ord(x) < 32 or ord(x) == 127 for x in url):
        raise ValueError('Invalid URL characters.')
    return parts

class SecureRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, authenticated=False):
        self.authenticated = authenticated
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        https_url(newurl)
        if self.authenticated:
            raise ValueError('Unexpected redirect from authenticated Sketchfab API.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def curl_quote(value):
    # curl --config syntax; credentials and signed URLs go through stdin,
    # not command-line arguments (which may be visible to other processes).
    if any(ord(x) < 32 or ord(x) == 127 for x in value):
        raise ValueError('Invalid control character in HTTP request.')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'

def mac_download(url, headers, destination, timeout, limit=None):
    https_url(url)
    authenticated = 'Authorization' in headers
    # -q must be the first option: ignore user curlrc, including unsafe defaults.
    args = [MAC_CURL, '-q', '--silent', '--show-error', '--fail',
            '--proto', '=https', '--proto-redir', '=https',
            '--connect-timeout', str(min(10, timeout)), '--max-time', str(timeout),
            '--max-redirs', '5', '--write-out', '%{http_code}', '--config', '-']
    if not authenticated: args.append('--location')
    if limit is not None: args += ['--max-filesize', str(limit)]
    cfg = ['url = ' + curl_quote(url), 'output = ' + curl_quote(str(destination))]
    cfg += ['header = ' + curl_quote(k + ': ' + v) for k, v in headers.items()]
    env = os.environ.copy()
    # Do not inherit Maya's private dynamic libraries or Python CA paths.
    for key in ('DYLD_LIBRARY_PATH','DYLD_FALLBACK_LIBRARY_PATH','DYLD_INSERT_LIBRARIES',
                'SSL_CERT_FILE','SSL_CERT_DIR'):
        env.pop(key, None)
    try:
        result = subprocess.run(args, input=('\n'.join(cfg)+'\n').encode('utf-8'),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout+5, env=env, check=False)
    except subprocess.TimeoutExpired:
        raise RuntimeError('macOS HTTPS request timed out.') from None
    except OSError as e:
        raise RuntimeError('Cannot launch macOS system curl: '+str(e)) from None
    code = result.stdout.decode('ascii', errors='replace').strip()
    if result.returncode or not (len(code)==3 and code.isdigit() and 200<=int(code)<300):
        # Do not display curl stderr: it can contain a signed download URL.
        if result.returncode in (35, 51, 58, 60, 77, 83, 90, 91):
            raise RuntimeError('macOS HTTPS certificate/TLS error (curl %s). Check system certificates, date and network proxy.' % result.returncode)
        if result.returncode == 28: raise RuntimeError('macOS HTTPS request timed out.')
        if result.returncode == 63: raise ValueError('Response exceeds size limit.')
        raise RuntimeError('macOS HTTPS request failed (HTTP %s, curl %s).' % (code or 'unknown', result.returncode))
    if limit is not None and Path(destination).stat().st_size > limit:
        raise ValueError('Response exceeds size limit.')

def download_bytes(url, headers, target=None, timeout=90, limit=None):
    https_url(url)
    timeout = max(1, int(math.ceil(timeout)))
    # Always write to a temporary file; failed transfers cannot leave a valid cache.
    directory = str(Path(target).parent) if target is not None else None
    fd, tmp = tempfile.mkstemp(prefix='sf_http_', dir=directory)
    os.close(fd)
    try:
        if sys.platform == 'darwin' and os.path.isfile(MAC_CURL):
            mac_download(url, headers, tmp, timeout, limit)
        else:
            opener = urllib.request.build_opener(SecureRedirect('Authorization' in headers))
            with opener.open(urllib.request.Request(url, headers=headers), timeout=timeout) as r, open(tmp,'wb') as f:
                https_url(r.geturl())
                total = 0
                while True:
                    data = r.read(64*1024)
                    if not data: break
                    total += len(data)
                    if limit is not None and total > limit: raise ValueError('Response exceeds size limit.')
                    f.write(data)
        if target is not None:
            os.replace(tmp, str(target)); return None
        return Path(tmp).read_bytes()
    finally:
        try: os.unlink(tmp)
        except OSError: pass

def request(url, token='', target=None, timeout=90):
    headers = {'User-Agent': USER_AGENT}
    if token:
        if not url.startswith(API): raise ValueError('Unexpected API URL')
        headers['Authorization'] = ('Bearer ' + token[7:] if token.startswith('Bearer ') else 'Token ' + token)
    data = download_bytes(url, headers, target=target, timeout=timeout,
                          limit=None if target is not None else 32*1024*1024)
    if target is None: return json.loads(data.decode('utf-8'))

def local(root, uri):
    p = (root / urllib.parse.unquote(uri)).resolve()
    if not p.is_relative_to(root.resolve()): raise ValueError('Unsafe archive path')
    return p

def extract(z, root):
    with zipfile.ZipFile(z) as archive:
        for f in archive.infolist():
            p = local(root, f.filename)
            if f.is_dir(): p.mkdir(parents=True, exist_ok=True); continue
            p.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(f) as src, open(p, 'wb') as dst: shutil.copyfileobj(src,dst)

def cache_dir():
    root = Path(c.workspace(q=True, rootDirectory=True)) / 'sourceimages' / 'Sketchfab'
    root.mkdir(parents=True, exist_ok=True)
    return root

def acquire(uid, token):
    if not re.fullmatch(r'[a-fA-F0-9]{32}',uid): raise ValueError('Invalid Sketchfab UID')
    root = cache_dir() / uid
    if (root/'_complete').exists():
        paths = list(root.rglob('*.gltf'))
        if paths: return paths[0]
    if not token: raise ValueError('Enter your own Sketchfab API token first.')
    result = request(API+'models/'+uid+'/download', token)
    url = result.get('gltf',{}).get('url')
    if not url: raise ValueError('No glTF download available.')
    with tempfile.TemporaryDirectory(dir=str(cache_dir())) as tmp:
        t=Path(tmp); z=t/'asset.zip'; unpack=t/'unpack'; unpack.mkdir()
        request(url, target=z); extract(z,unpack)
        paths=list(unpack.rglob('*.gltf'))
        if not paths: raise ValueError('No .gltf file in archive.')
        rel=paths[0].relative_to(unpack)
        if root.exists(): shutil.rmtree(root)
        shutil.move(str(unpack),str(root)); (root/'_complete').touch()
        return root/rel

class GLTF:
    def __init__(self,path):
        self.path=Path(path); self.root=self.path.parent
        self.d=json.loads(self.path.read_text(encoding='utf-8-sig'))
        self.buffers=[self.bytes(b['uri']) for b in self.d.get('buffers',[])]
        self.materials={}; self.files={}; self.warnings=set()
        self.unit={'mm':1000,'cm':100,'m':1,'km':.001,'in':39.37007874,'ft':3.280839895,'yd':1.0936133,'mi':.000621371}.get(c.currentUnit(q=True,linear=True),100)
        # OpenMaya points are always centimeters, regardless of UI units.
        self.preflight()
    def bytes(self,uri):
        if uri.startswith('data:'): return base64.b64decode(uri.split(',',1)[1])
        return local(self.root,uri).read_bytes()
    def preflight(self):
        unsupported=set(self.d.get('extensionsRequired',[]))-{'KHR_materials_unlit','KHR_texture_transform','KHR_materials_emissive_strength'}
        if unsupported: raise ValueError('Unsupported required glTF extensions: '+', '.join(sorted(unsupported)))
        if self.d.get('skins') or self.d.get('animations'): self.warnings.add('Skins/animations: static base pose only; no rig or animation imported.')
        for m in self.d.get('meshes',[]):
            for p in m.get('primitives',[]):
                if p.get('mode',4)!=4 or 'KHR_draco_mesh_compression' in p.get('extensions',{}): raise ValueError('Only uncompressed triangle meshes are supported.')
                if p.get('targets'): self.warnings.add('Morph targets omitted.')
                if 'COLOR_0' in p.get('attributes',{}): self.warnings.add('Vertex colors are not imported.')
        for m in self.d.get('materials',[]):
            if m.get('extensions'): self.warnings.add('Some material extensions are approximated or omitted.')
    def accessor(self,i):
        a=self.d['accessors'][i]
        if 'sparse' in a or 'bufferView' not in a: raise ValueError('Sparse accessors are not supported.')
        v=self.d['bufferViews'][a['bufferView']]
        fmt={5120:'b',5121:'B',5122:'h',5123:'H',5125:'I',5126:'f'}[a['componentType']]
        n={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[a['type']]
        s=struct.Struct('<'+fmt*n); stride=v.get('byteStride',s.size); off=v.get('byteOffset',0)+a.get('byteOffset',0)
        data=self.buffers[v['buffer']]; out=[s.unpack_from(data,off+j*stride) for j in range(a['count'])]
        if a.get('normalized') and fmt!='f':
            mx={'b':127,'B':255,'h':32767,'H':65535,'I':4294967295}[fmt]
            out=[tuple(max(-1,x/mx) for x in row) for row in out]
        return out
    def image(self,i):
        a=self.d['images'][i]; uri=a.get('uri','')
        if uri and not uri.startswith('data:'): return local(self.root,uri)
        if uri: data=self.bytes(uri)
        else:
            v=self.d['bufferViews'][a['bufferView']]; off=v.get('byteOffset',0); data=self.buffers[v['buffer']][off:off+v['byteLength']]
        mime=a.get('mimeType',uri.split(';')[0].replace('data:',''))
        ext={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp'}.get(mime)
        if not ext: raise ValueError('Unsupported embedded image: '+mime)
        p=self.root/('_embedded_'+str(i)+ext); p.write_bytes(data); return p
    def texture(self,info,space):
        idx=info['index']; tex=self.d['textures'][idx]; tr=info.get('extensions',{}).get('KHR_texture_transform',{})
        uv=tr.get('texCoord',info.get('texCoord',0))
        if uv!=0: raise ValueError('Material uses UV set other than TEXCOORD_0; unsupported in v1.')
        if tr: self.warnings.add('KHR_texture_transform omitted; texture placement may differ.')
        key=(idx,space)
        if key in self.files: return self.files[key]
        if 'source' not in tex: raise ValueError('Compressed or unsupported texture format.')
        f=c.shadingNode('file',asTexture=True,name='SF_tex#'); p=c.shadingNode('place2dTexture',asUtility=True,name='SF_place#')
        for a in ('coverage','translateFrame','rotateFrame','mirrorU','mirrorV','stagger','wrapU','wrapV','repeatUV','offset','rotateUV','noiseUV','vertexUvOne','vertexUvTwo','vertexUvThree','vertexCameraOne'):
            c.connectAttr(p+'.'+a,f+'.'+a,force=True)
        c.connectAttr(p+'.outUV',f+'.uvCoord',force=True); c.connectAttr(p+'.outUvFilterSize',f+'.uvFilterSize',force=True)
        sampler=self.d.get('samplers',[])
        if 'sampler' in tex:
            sm=sampler[tex['sampler']]
            for axis,prop in [('U','wrapS'),('V','wrapT')]:
                mode=sm.get(prop,10497)
                if mode==33071: c.setAttr(p+'.wrap'+axis,0)
                elif mode==33648: c.setAttr(p+'.mirror'+axis,1)
        c.setAttr(f+'.fileTextureName',str(self.image(tex['source'])).replace('\\','/'),type='string')
        if c.attributeQuery('ignoreColorSpaceFileRules',node=f,exists=True): c.setAttr(f+'.ignoreColorSpaceFileRules',1)
        spaces=c.colorManagementPrefs(q=True,inputSpaceNames=True) or []
        candidates=['sRGB','Utility - sRGB - Texture','sRGB - Texture'] if space=='sRGB' else ['Raw','Utility - Raw']
        chosen=next((x for x in candidates if x in spaces),None)
        if not chosen: raise ValueError('Cannot find '+space+' input color space in Maya.')
        c.setAttr(f+'.colorSpace',chosen,type='string'); self.files[key]=f; return f
    def scalar(self,src,dst,factor):
        if factor==1: c.connectAttr(src,dst,force=True); return
        n=c.createNode('multDoubleLinear',name='SF_factor#'); c.connectAttr(src,n+'.input1'); c.setAttr(n+'.input2',factor); c.connectAttr(n+'.output',dst,force=True)
    def color(self,src,dst,factor):
        if tuple(factor)==(1,1,1): c.connectAttr(src,dst,force=True); return
        n=c.shadingNode('multiplyDivide',asUtility=True,name='SF_colorFactor#'); c.connectAttr(src,n+'.input1'); c.setAttr(n+'.input2',*factor,type='double3'); c.connectAttr(n+'.output',dst,force=True)
    def material(self,i):
        if i in self.materials: return self.materials[i]
        m=self.d.get('materials',[])[i] if i is not None else {}; p=m.get('pbrMetallicRoughness',{})
        n=c.shadingNode('openPBRSurface',asShader=True,name='SF_'+safe(m.get('name','Material'))+'#')
        sg=c.sets(renderable=True,noSurfaceShader=True,empty=True,name=n+'SG'); c.connectAttr(n+'.outColor',sg+'.surfaceShader',force=True)
        bc=p.get('baseColorFactor',[1,1,1,1]); metal=p.get('metallicFactor',1); rough=p.get('roughnessFactor',1)
        c.setAttr(n+'.baseColor',*bc[:3],type='double3'); c.setAttr(n+'.baseMetalness',metal); c.setAttr(n+'.specularRoughness',rough)
        base=None
        if 'baseColorTexture' in p:
            base=self.texture(p['baseColorTexture'],'sRGB'); self.color(base+'.outColor',n+'.baseColor',bc[:3])
        if 'metallicRoughnessTexture' in p:
            f=self.texture(p['metallicRoughnessTexture'],'Raw'); self.scalar(f+'.outColorG',n+'.specularRoughness',rough); self.scalar(f+'.outColorB',n+'.baseMetalness',metal)
        if 'normalTexture' in m:
            f=self.texture(m['normalTexture'],'Raw')
            try:
                if not c.pluginInfo('mtoa',q=True,loaded=True): c.loadPlugin('mtoa',quiet=True)
                b=c.shadingNode('aiNormalMap',asUtility=True,name='SF_normal#'); c.connectAttr(f+'.outColor',b+'.input',force=True)
                if c.attributeQuery('strength',node=b,exists=True): c.setAttr(b+'.strength',m['normalTexture'].get('scale',1))
                c.connectAttr(b+'.outValue',n+'.normalCamera',force=True)
            except Exception: self.warnings.add('Arnold normal-map connection failed; check MtoA.')
        em=m.get('emissiveFactor',[0,0,0]); strength=m.get('extensions',{}).get('KHR_materials_emissive_strength',{}).get('emissiveStrength',1)
        if any(em):
            c.setAttr(n+'.emissionColor',*em,type='double3'); c.setAttr(n+'.emissionLuminance',strength)
            if 'emissiveTexture' in m: self.color(self.texture(m['emissiveTexture'],'sRGB')+'.outColor',n+'.emissionColor',em)
        alpha=m.get('alphaMode','OPAQUE')
        if alpha!='OPAQUE':
            c.setAttr(n+'.geometryOpacity',bc[3]); src=None
            if base:
                src=base+'.outAlpha'; factor=c.createNode('multDoubleLinear',name='SF_alphaFactor#'); c.connectAttr(src,factor+'.input1'); c.setAttr(factor+'.input2',bc[3]); src=factor+'.output'
            if alpha=='MASK':
                cutoff=m.get('alphaCutoff',.5)
                if src:
                    k=c.createNode('condition',name='SF_alphaMask#'); c.setAttr(k+'.operation',3); c.connectAttr(src,k+'.firstTerm'); c.setAttr(k+'.secondTerm',cutoff); c.setAttr(k+'.colorIfTrueR',1); c.setAttr(k+'.colorIfFalseR',0); src=k+'.outColorR'
                else: c.setAttr(n+'.geometryOpacity',float(bc[3]>=cutoff))
            if src: c.connectAttr(src,n+'.geometryOpacity',force=True)
        if 'occlusionTexture' in m: self.warnings.add('AO is not multiplied into base color; use lighting or composite as needed.')
        if m.get('extensions',{}).get('KHR_materials_unlit') is not None: self.warnings.add('Unlit materials are approximated as lit OpenPBR.')
        self.materials[i]=(sg,alpha,m.get('doubleSided',False)); return self.materials[i]
    def mesh(self,p,parent,name):
        a=p['attributes']; positions=self.accessor(a['POSITION']); idx=[r[0] for r in self.accessor(p['indices'])] if 'indices' in p else list(range(len(positions)))
        if not idx or len(idx)%3: raise ValueError('Invalid triangle indices')
        sel=om.MSelectionList(); sel.add(parent); par=sel.getDependNode(0)
        fn=om.MFnMesh(); obj=fn.create([om.MPoint(x*100,y*100,z*100) for x,y,z in positions],[3]*(len(idx)//3),idx,parent=par)
        shape=om.MFnDagNode(obj).fullPathName(); shape=c.rename(shape,name+'Shape#'); shape=c.ls(shape,long=True)[0]
        if 'TEXCOORD_0' in a:
            uv=self.accessor(a['TEXCOORD_0']); fn.setUVs([x for x,y in uv],[1-y for x,y in uv]); fn.assignUVs([3]*(len(idx)//3),idx)
        if 'NORMAL' in a:
            normals=self.accessor(a['NORMAL']); fn.setVertexNormals([om.MVector(*v) for v in normals],list(range(len(normals))),om.MSpace.kObject)
        sg,alpha,double=self.material(p.get('material')); c.sets(shape,e=True,forceElement=sg)
        if c.attributeQuery('doubleSided',node=shape,exists=True): c.setAttr(shape+'.doubleSided',double)
        if alpha!='OPAQUE' and c.attributeQuery('aiOpaque',node=shape,exists=True): c.setAttr(shape+'.aiOpaque',0)
    def node(self,i,parent):
        d=self.d['nodes'][i]; n=c.createNode('transform',name='SF_'+safe(d.get('name','Node'))+'#',parent=parent); n=c.ls(n,long=True)[0]
        if 'matrix' in d:
            mat=list(d['matrix']); mat[12:15]=[x*self.unit for x in mat[12:15]]; c.xform(n,objectSpace=True,matrix=mat)
        else:
            c.setAttr(n+'.translate',*[x*self.unit for x in d.get('translation',[0,0,0])],type='double3')
            q=om.MQuaternion(*d.get('rotation',[0,0,0,1])); e=q.asEulerRotation(); import math
            c.setAttr(n+'.rotate',*[math.degrees(x) for x in (e.x,e.y,e.z)],type='double3'); c.setAttr(n+'.scale',*d.get('scale',[1,1,1]),type='double3')
        if 'mesh' in d:
            for j,p in enumerate(self.d['meshes'][d['mesh']]['primitives']):
                child=c.createNode('transform',name='SF_primitive_%d#'%j,parent=n); self.mesh(p,c.ls(child,long=True)[0],'SF_mesh')
        for ch in d.get('children',[]): self.node(ch,n)
    def run(self,name,credit):
        old=set(c.ls()); root=None
        c.undoInfo(openChunk=True,chunkName='Sketchfab Import')
        try:
            root=c.group(empty=True,name='SF_'+safe(name)+'#'); root=c.ls(root,long=True)[0]
            if c.upAxis(q=True,axis=True)=='z': c.setAttr(root+'.rotateX',90)
            scenes=self.d.get('scenes',[])
            if not scenes: raise ValueError('No glTF scenes')
            for i in scenes[self.d.get('scene',0)].get('nodes',[]): self.node(i,root)
            if not c.listRelatives(root,allDescendents=True,type='mesh'): raise ValueError('No mesh imported')
            c.addAttr(root,longName='sketchfabAttribution',dataType='string'); c.setAttr(root+'.sketchfabAttribution',credit,type='string'); c.select(root)
        except Exception:
            if root and c.objExists(root): c.delete(root)
            for n in set(c.ls())-old:
                if c.objExists(n):
                    try: c.delete(n)
                    except Exception: pass
            raise
        finally: c.undoInfo(closeChunk=True)
        return root,sorted(self.warnings)

# Qt UI: thumbnail workers never call Maya or Qt GUI APIs.
import hashlib, queue, threading
from concurrent.futures import ThreadPoolExecutor
try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import wrapInstance
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from shiboken2 import wrapInstance
import maya.OpenMayaUI as omui

THUMB_CACHE = Path(tempfile.gettempdir()) / 'MayaSketchfabThumbs_v11'
THUMB_LIMIT = 8 * 1024 * 1024

def thumb_url(model, width):
    images = [a for a in ((model.get('thumbnails') or {}).get('images') or [])
              if isinstance(a, dict) and isinstance(a.get('url'), str)
              and a['url'].startswith('https://')]
    if not images: return None
    return min(images, key=lambda a: abs((a.get('width') or width)-width))['url']

def fetch_thumb(url):
    if not url or not url.startswith('https://'): raise ValueError('No thumbnail URL')
    THUMB_CACHE.mkdir(parents=True, exist_ok=True)
    path = THUMB_CACHE / (hashlib.sha256(url.encode('utf-8')).hexdigest()+'.img')
    if path.is_file() and 0 < path.stat().st_size <= THUMB_LIMIT: return str(path)
    tmp = None
    try:
        data=download_bytes(url, {'User-Agent':USER_AGENT},timeout=8,limit=THUMB_LIMIT)
        if not data or len(data)>THUMB_LIMIT: raise ValueError('Invalid thumbnail size')
        with tempfile.NamedTemporaryFile(dir=str(THUMB_CACHE),delete=False) as f:
            tmp=f.name; f.write(data)
        os.replace(tmp,str(path)); tmp=None
        return str(path)
    finally:
        if tmp:
            try: os.unlink(tmp)
            except OSError: pass

class Browser(QtWidgets.QDialog):
    def __init__(self,parent=None):
        super(Browser,self).__init__(parent)
        self.setObjectName('SketchfabAssetBrowserV12')
        self.setWindowTitle('Sketchfab Asset Browser v1.2 | Windows / macOS | OpenPBR')
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose,True)
        self.resize(850,790); self.setMinimumSize(520,600)
        self.rows=[]; self.next=None; self.page=0; self.view_epoch=0; self.detail_epoch=0
        self.closed=False; self.loading=False; self.mode='grid'; self.grid_futures=[]; self.detail_future=None
        self.events=queue.Queue(); self.grid_pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix='SFThumb')
        self.detail_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='SFPreview')
        self.search_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='SFSearch')
        self.grid_pending=0; self.grid_done=0; self.grid_failed=0
        self.placeholder=self.make_placeholder()
        layout=QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel('Models provided by Sketchfab | Static glTF / OpenPBR'))
        form=QtWidgets.QFormLayout(); self.token=QtWidgets.QLineEdit(); self.token.setEchoMode(QtWidgets.QLineEdit.Password)
        form.addRow('API token',self.token); layout.addLayout(form)
        self.button(layout,'Get your personal token (Sketchfab settings)',lambda: self.open_url('https://sketchfab.com/settings/password'))
        sr=QtWidgets.QHBoxLayout(); self.query=QtWidgets.QLineEdit('forest'); sr.addWidget(QtWidgets.QLabel('Search')); sr.addWidget(self.query,1)
        self.search_button=self.button(sr,'Search',self.search); self.next_button=self.button(sr,'Next page',self.more); self.next_button.setEnabled(False); layout.addLayout(sr)
        self.query.returnPressed.connect(lambda: self.guard(self.search))
        mr=QtWidgets.QHBoxLayout(); self.grid_button=QtWidgets.QRadioButton('Thumbnail View'); self.list_button=QtWidgets.QRadioButton('List View (lightweight)')
        self.grid_button.setChecked(True); mr.addWidget(self.grid_button); mr.addWidget(self.list_button); mr.addStretch(1)
        self.grid_button.toggled.connect(lambda checked: self.set_mode('grid') if checked else None)
        self.list_button.toggled.connect(lambda checked: self.set_mode('list') if checked else None)
        layout.addLayout(mr)
        self.results=QtWidgets.QListWidget(); self.results.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.results.setWordWrap(True); self.results.setUniformItemSizes(True); self.results.setMinimumHeight(190)
        self.results.currentRowChanged.connect(self.selected)
        self.results.itemDoubleClicked.connect(lambda *_: self.guard(self.open_model))
        layout.addWidget(self.results,1)
        self.thumb_status=QtWidgets.QLabel(''); layout.addWidget(self.thumb_status)
        detail=QtWidgets.QHBoxLayout(); self.preview=QtWidgets.QLabel('Select an asset'); self.preview.setAlignment(QtCore.Qt.AlignCenter); self.preview.setFixedSize(260,160)
        self.preview.setStyleSheet('QLabel { background-color: #333333; color: #dddddd; }'); detail.addWidget(self.preview)
        self.info=QtWidgets.QPlainTextEdit(); self.info.setReadOnly(True); self.info.setFixedHeight(160); self.info.setPlainText('Select an asset to inspect its license and author.'); detail.addWidget(self.info,1); layout.addLayout(detail)
        self.open_button=self.button(layout,'Open selected model on Sketchfab',self.open_model)
        self.import_button=self.button(layout,'Download & Import OpenPBR',self.download); self.import_button.setMinimumHeight(38)
        self.button(layout,'Import local .gltf (static, no login)',self.import_local)
        layout.addWidget(QtWidgets.QLabel('Textures: original resolution | Cache: project/sourceimages/Sketchfab'))
        self.status=QtWidgets.QLabel('Ready'); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.set_mode('grid',force=True); self.update_buttons()
        self.timer=QtCore.QTimer(self); self.timer.setInterval(60); self.timer.timeout.connect(self.poll); self.timer.start()
    def button(self,layout,label,fn):
        b=QtWidgets.QPushButton(label); b.clicked.connect(lambda checked=False: self.guard(fn)); layout.addWidget(b); return b
    def make_placeholder(self):
        p=QtGui.QPixmap(160,100); p.fill(QtGui.QColor('#393939')); painter=QtGui.QPainter(p)
        painter.setPen(QtGui.QColor('#bcbcbc')); painter.drawText(p.rect(),QtCore.Qt.AlignCenter,'No preview'); painter.end(); return QtGui.QIcon(p)
    def guard(self,fn):
        if self.closed: return
        try: fn()
        except Exception as e:
            self.status.setText('Error: '+str(e)[:150]); c.warning(str(e)); QtWidgets.QMessageBox.warning(self,'Sketchfab Browser',str(e))
    def enqueue(self,pool,key,fn):
        # Future callback writes plain Python data only; no GUI or Maya calls.
        events=self.events
        future=pool.submit(fn)
        def done(f):
            if f.cancelled(): return
            try: events.put((key,f.result(),None))
            except Exception as exc: events.put((key,None,str(exc)))
        future.add_done_callback(done); return future
    def cancel_grid(self):
        self.view_epoch+=1
        for f in self.grid_futures: f.cancel()
        self.grid_futures=[]; self.grid_pending=self.grid_done=self.grid_failed=0
    def cancel_detail(self):
        self.detail_epoch+=1
        if self.detail_future: self.detail_future.cancel()
        self.detail_future=None
    def set_mode(self,mode,force=False):
        if self.closed or (mode==self.mode and not force): return
        self.cancel_grid(); self.mode=mode
        w=self.results; w.setUpdatesEnabled(False)
        try:
            if mode=='grid':
                w.setViewMode(QtWidgets.QListView.IconMode); w.setFlow(QtWidgets.QListView.LeftToRight); w.setWrapping(True)
                w.setResizeMode(QtWidgets.QListView.Adjust); w.setMovement(QtWidgets.QListView.Static)
                w.setIconSize(QtCore.QSize(164,104)); w.setGridSize(QtCore.QSize(188,158)); w.setSpacing(3)
            else:
                w.setViewMode(QtWidgets.QListView.ListMode); w.setFlow(QtWidgets.QListView.TopToBottom); w.setWrapping(False)
                w.setResizeMode(QtWidgets.QListView.Adjust); w.setMovement(QtWidgets.QListView.Static)
                w.setGridSize(QtCore.QSize()); w.setIconSize(QtCore.QSize(0,0)); w.setSpacing(1)
            for i,m in enumerate(self.rows): self.style_item(i,m)
        finally: w.setUpdatesEnabled(True)
        if mode=='grid': self.start_grid()
        else: self.thumb_status.setText('Lightweight: only the selected model preview is loaded.')
    def style_item(self,i,m):
        item=self.results.item(i); name=m.get('name') or 'Untitled'; author=(m.get('user') or {}).get('username') or '?'
        if self.mode=='grid':
            item.setText(name+'\n'+author); item.setIcon(self.placeholder); item.setTextAlignment(QtCore.Qt.AlignHCenter)
        else:
            item.setText('%d. %s — %s'%(i+1,name,author)); item.setIcon(QtGui.QIcon()); item.setTextAlignment(QtCore.Qt.AlignLeft|QtCore.Qt.AlignVCenter)
        item.setToolTip(name+'\nAuthor: '+author)
    def start_grid(self):
        self.grid_pending=len(self.rows); self.grid_done=self.grid_failed=0; epoch=self.view_epoch; page=self.page
        for i,m in enumerate(self.rows):
            url=thumb_url(m,256)
            if not url:
                self.grid_done+=1; self.grid_failed+=1; continue
            self.grid_futures.append(self.enqueue(self.grid_pool,('grid',page,epoch,i),lambda u=url:fetch_thumb(u)))
        self.grid_status()
    def grid_status(self):
        if not self.grid_pending: self.thumb_status.setText(''); return
        self.thumb_status.setText('Thumbnails: %d / %d%s'%(self.grid_done,self.grid_pending,(' | %d unavailable'%self.grid_failed) if self.grid_failed else ''))
    def search(self):
        if self.loading: return
        q=self.query.text().strip(); self.load(API+'search?'+urllib.parse.urlencode({'type':'models','q':q,'downloadable':'true','count':24}))
    def more(self):
        if self.next and not self.loading: self.load(self.next)
    def load(self,url):
        if not url.startswith(API): raise ValueError('Unexpected search URL')
        self.loading=True; self.update_buttons(); self.status.setText('Searching Sketchfab…')
        self.enqueue(self.search_pool,('search',),lambda:request(url,timeout=20))
    def apply_search(self,result):
        self.cancel_grid(); self.cancel_detail(); self.page+=1
        self.rows=result.get('results') or []; self.next=result.get('next'); self.results.blockSignals(True)
        try:
            self.results.clear()
            for i,m in enumerate(self.rows): self.results.addItem(QtWidgets.QListWidgetItem()); self.style_item(i,m)
        finally: self.results.blockSignals(False)
        self.info.setPlainText('Select an asset.'); self.preview.setPixmap(QtGui.QPixmap()); self.preview.setText('Select an asset'); self.update_buttons()
        self.status.setText('%d results'%len(self.rows))
        if self.mode=='grid': self.start_grid()
        else: self.thumb_status.setText('Lightweight: only the selected model preview is loaded.')
    def update_buttons(self):
        self.search_button.setEnabled(not self.loading); self.next_button.setEnabled(bool(self.next) and not self.loading)
        selected=0<=self.results.currentRow()<len(self.rows) and not self.loading
        self.open_button.setEnabled(selected); self.import_button.setEnabled(selected)
    def model(self):
        i=self.results.currentRow()
        if not 0<=i<len(self.rows): raise ValueError('Select an asset first.')
        return self.rows[i]
    def selected(self,i):
        if self.closed: return
        self.cancel_detail(); self.update_buttons()
        self.preview.setPixmap(QtGui.QPixmap()); self.preview.setText('Select an asset')
        if not 0<=i<len(self.rows): self.info.setPlainText('Select an asset.'); return
        m=self.rows[i]; self.info.setPlainText(self.credit(m)); self.preview.setText('Loading preview…')
        url=thumb_url(m,640)
        if not url: self.preview.setText('No preview available'); return
        self.detail_future=self.enqueue(self.detail_pool,('detail',self.page,self.detail_epoch,i),lambda:fetch_thumb(url))
    def pixmap(self,path):
        # QImageReader detects content rather than relying on the cache extension.
        reader=QtGui.QImageReader(path); reader.setDecideFormatFromContent(True); reader.setAutoTransform(True)
        size=reader.size()
        if size.isValid() and (size.width()>2048 or size.height()>2048):
            reader.setScaledSize(size.scaled(QtCore.QSize(2048,2048),QtCore.Qt.KeepAspectRatio))
        im=reader.read()
        if im.isNull():
            try: Path(path).unlink()
            except OSError: pass
            return QtGui.QPixmap()
        return QtGui.QPixmap.fromImage(im)
    def poll(self):
        if self.closed: return
        for _ in range(16):
            try: key,value,error=self.events.get_nowait()
            except queue.Empty: break
            kind=key[0]
            if kind=='search':
                self.loading=False; self.update_buttons()
                if error: self.status.setText('Search failed: '+error[:160]); continue
                try: self.apply_search(value)
                except Exception as e: self.status.setText('Search failed: '+str(e)[:160])
            elif kind=='grid':
                _,page,epoch,i=key
                if page!=self.page or epoch!=self.view_epoch or self.mode!='grid': continue
                self.grid_done+=1; pix=self.pixmap(value) if not error else QtGui.QPixmap()
                if pix.isNull(): self.grid_failed+=1
                elif self.results.item(i):
                    self.results.item(i).setIcon(QtGui.QIcon(pix.scaled(164,104,QtCore.Qt.KeepAspectRatio,QtCore.Qt.SmoothTransformation)))
                self.grid_status()
            elif kind=='detail':
                _,page,epoch,i=key
                if page!=self.page or epoch!=self.detail_epoch or i!=self.results.currentRow(): continue
                pix=self.pixmap(value) if not error else QtGui.QPixmap()
                if pix.isNull(): self.preview.setText('Preview unavailable'); continue
                self.preview.setPixmap(pix.scaled(self.preview.size(),QtCore.Qt.KeepAspectRatio,QtCore.Qt.SmoothTransformation))
    def credit(self,m):
        l=m.get('license') or {}; u=m.get('user') or {}; url=m.get('viewerUrl') or m.get('url') or 'https://sketchfab.com/3d-models/'+m['uid']; return '%s\nAuthor: %s\nSource: %s\nLicense: %s %s'%(m.get('name','Untitled'),u.get('username','Unknown'),url,l.get('label','Check model page'),l.get('url',''))
    def open_url(self,url):
        https_url(url)
        if not QtGui.QDesktopServices.openUrl(QtCore.QUrl(url)):
            raise RuntimeError('Could not open the system web browser.')
    def open_model(self):
        m=self.model(); self.open_url(m.get('viewerUrl') or 'https://sketchfab.com/3d-models/'+m['uid'])
    def download(self):
        m=self.model(); detail=request(API+'models/'+m['uid']); credit=self.credit(detail)
        if c.confirmDialog(title='License / Attribution',message=credit+'\n\nImport this asset under its license?',button=['Import','Cancel'],defaultButton='Import',cancelButton='Cancel',dismissString='Cancel')!='Import': return
        token=self.token.text().strip(); path=acquire(m['uid'],token); (cache_dir()/m['uid']/'ATTRIBUTION.txt').write_text(credit,encoding='utf-8'); self.finish(path,m.get('name','Asset'),credit)
    def import_local(self):
        paths=c.fileDialog2(fileMode=1,fileFilter='glTF (*.gltf)',caption='Import local glTF') or []
        if paths: self.finish(Path(paths[0]),Path(paths[0]).stem,'Local asset: verify original license and author.')
    def finish(self,path,name,credit):
        root,warnings=GLTF(path).run(name,credit); self.status.setText('Imported: '+root.split('|')[-1])
        for w in warnings: c.warning(w)
        if warnings: c.confirmDialog(title='Imported with limitations',message='\n'.join(warnings),button=['OK'])
    def closeEvent(self,event):
        self.closed=True; self.timer.stop(); self.cancel_grid(); self.cancel_detail()
        for pool in (self.grid_pool,self.detail_pool,self.search_pool): pool.shutdown(wait=False,cancel_futures=True)
        super(Browser,self).closeEvent(event)

def show():
    global _browser
    if c.window(WIN,exists=True): c.deleteUI(WIN)
    ptr=omui.MQtUtil.mainWindow(); parent=wrapInstance(int(ptr),QtWidgets.QWidget) if ptr else None
    if parent:
        for version in ('SketchfabAssetBrowserV11','SketchfabAssetBrowserV12'):
            for old in parent.findChildren(QtWidgets.QDialog,version):
                old.close()
    _browser=Browser(parent); _browser.show(); _browser.raise_(); _browser.activateWindow(); return _browser

if __name__=='__main__': show()
