# -*- coding: utf-8 -*-
"""Maya City Builder 2.4.1 — nTools integration; also runnable in Maya Python Script Editor.
Data: OpenStreetMap contributors, ODbL. https://www.openstreetmap.org/copyright
No Google data. No additional pip packages. Browser map requires internet.
"""
import json
import math
import os
import re
import ssl
import threading
import secrets
import hashlib
import time
import traceback
import urllib.request
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import maya.cmds as cmds
import maya.api.OpenMaya as om
try:
    from PySide6 import QtCore
except ImportError:
    from PySide2 import QtCore

VERSION = '2.4.1'
CREDIT = '© OpenStreetMap contributors | ODbL | https://www.openstreetmap.org/copyright'
DEFAULT_BBOX = (35.6788, 139.7645, 35.6834, 139.7701)
R = 6378137.0
MAX_SPAN = 1500.0  # metres per side, to limit load on public services
MAX_BUILDINGS = 2000

HTML = r'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Maya City Builder</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<style>body{margin:0;background:#20252b;color:#f2f3f4;font:15px system-ui,sans-serif}header{padding:12px 18px}h2{margin:0 0 8px;font-size:19px}p{margin:6px 0}button,input{font:inherit;padding:6px 9px;border-radius:5px;border:1px solid #8b969e}button{cursor:pointer;margin:3px;background:#e2e8eb;color:#17232c}button.primary{background:#bde9cc}input{width:112px}#map{height:calc(100vh - 238px);min-height:300px}#status{color:#bde9cc;min-height:20px}footer{padding:7px 18px}a{color:#a5d5ff}</style></head><body><header>
<h2>Maya City Builder / 地図で範囲選択</h2><p>地図を移動・拡大し、範囲選択を押して対角の2点をクリックしてください。</p>
<div><button id="draw">範囲選択（2点）</button><button id="view">表示範囲を選択</button><button id="send" class="primary">選択範囲をMayaへ送信</button></div>
<div><label>南 <input id="s" type="number" step="any"></label> <label>西 <input id="w" type="number" step="any"></label> <label>北 <input id="n" type="number" step="any"></label> <label>東 <input id="e" type="number" step="any"></label> <button id="apply">座標を適用</button></div>
<div id="status" role="status">地図の読み込み中…</div></header><div id="map"></div><footer>最大約1.5 km四方。<a href="https://www.openstreetmap.org/fixthemap" target="_blank" rel="noopener">地図の問題を報告</a> · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors</a></footer>
<script>
const $=id=>document.getElementById(id), status=s=>{$('status').textContent=s};
let map, rect, first=null, drawing=false;
const initial=__BBOX__;
function numbers(){return ['s','w','n','e'].map(k=>Number($(k).value));}
function fill(b){['s','w','n','e'].forEach((k,i)=>$(k).value=b[i].toFixed(7));}
function valid(b){return b.every(Number.isFinite)&&b[0]>=-80&&b[2]<=80&&b[1]>=-180&&b[3]<=180&&b[0]<b[2]&&b[1]<b[3];}
function show(b,fit=false){if(!valid(b)){status('座標が無効です。');return false;} fill(b);if(map){let bounds=[[b[0],b[1]],[b[2],b[3]]]; if(rect)rect.setBounds(bounds);else rect=L.rectangle(bounds,{color:'#f08c26',weight:3,fillOpacity:.12,interactive:false}).addTo(map);if(fit)map.fitBounds(bounds);}status('範囲を設定しました。Mayaへ送信してください。');return true;}
function stopDraw(){drawing=false;first=null;if(map)map.getContainer().style.cursor='';}
$('draw').onclick=()=>{if(!map){status('地図を読み込めません。座標を直接入力してください。');return;} drawing=true;first=null;map.getContainer().style.cursor='crosshair';status('1点目をクリックしてください。');};
$('view').onclick=()=>{if(!map)return;stopDraw();let b=map.getBounds();show([b.getSouth(),b.getWest(),b.getNorth(),b.getEast()]);};
$('apply').onclick=()=>{stopDraw();show(numbers(),true);};
$('send').onclick=async()=>{let b=numbers();if(!valid(b)){status('座標が無効です。');return;}try{let res=await fetch('./selection',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});let result=await res.json();if(!res.ok)throw Error(result.error);stopDraw();show(b);status('Mayaへ送信しました。Mayaに戻り「選択範囲を取得」→「BUILD CITY」を押してください。');}catch(e){status('送信失敗: '+e.message);}};
fill(initial);
if(typeof L!=='undefined'){map=L.map('map',{worldCopyJump:false}).setView([(initial[0]+initial[2])/2,(initial[1]+initial[3])/2],16);L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'}).addTo(map);show(initial,true);map.on('click',e=>{if(!drawing)return;let p=e.latlng;if(!first){first=p;status('2点目をクリックしてください。');return;}let b=[Math.min(first.lat,p.lat),Math.min(first.lng,p.lng),Math.max(first.lat,p.lat),Math.max(first.lng,p.lng)];stopDraw();show(b);});map.on('mousemove',e=>{if(drawing&&first){let p=e.latlng;let bounds=[[Math.min(first.lat,p.lat),Math.min(first.lng,p.lng)],[Math.max(first.lat,p.lat),Math.max(first.lng,p.lng)]];if(rect)rect.setBounds(bounds);else rect=L.rectangle(bounds,{color:'#f08c26',interactive:false}).addTo(map);}});}else{status('地図ライブラリが読み込めません。座標を直接入力して送信できます。');}
</script></body></html>'''

# Numeric and geographic utilities (metres, X east, Z south).
def span(b):
    s,w,n,e = b
    return R * math.radians(e-w) * math.cos(math.radians((s+n)/2)), R * math.radians(n-s)

def validate_bbox(b):
    if not isinstance(b, (tuple,list)) or len(b)!=4:
        raise ValueError('Enter four coordinates: South, West, North, East.')
    b = tuple(float(v) for v in b)
    s,w,n,e=b
    if not all(math.isfinite(v) for v in b) or not (-80<=s<n<=80 and -180<=w<e<=180):
        raise ValueError('Invalid bounds (no dateline crossing; latitude ±80°).')
    x,z=span(b)
    if max(x,z)>MAX_SPAN or min(x,z)<5:
        raise ValueError('Select an area between 5 m and 1.5 km on each side.')
    return b

def project(lat,lon,b):
    s,w,n,e=b; lat0=(s+n)/2; lon0=(w+e)/2
    return R*math.radians(lon-lon0)*math.cos(math.radians(lat0)), -R*math.radians(lat-lat0)

def signed_area(p):
    return .5*sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(p,p[1:]+p[:1]))

def clean_points(p, closed=False):
    out=[]
    for pt in p:
        if not out or math.hypot(pt[0]-out[-1][0],pt[1]-out[-1][1])>.001:
            out.append(pt)
    if closed and len(out)>1 and math.hypot(out[0][0]-out[-1][0],out[0][1]-out[-1][1])<.002:
        out.pop()
    return out

def number(s):
    if s is None:return None
    s=str(s).strip().lower().replace(',','.')
    m=re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)\s*(m|metres?|meters?|ft|feet|\')?',s)
    if not m:return None
    v=float(m.group(1));return v*.3048 if m.group(2) in ('ft','feet',"'") else v

def building_height(t, default, floor):
    h=number(t.get('height')); levels=number(t.get('building:levels'))
    if h and .3<=h<=1000:return h,'height'
    if levels and .3<=levels*floor<=1000:return levels*floor,'building:levels'
    if t.get('building') in ('garage','garages','shed','hut','carport'):return min(default,3.0),'estimated'
    return default,'estimated'

def road_width(t):
    v=number(t.get('width'))
    if v and .3<=v<=60:return v
    k=t.get('highway',''); lanes=number(t.get('lanes'))
    if lanes and lanes<=15 and k not in ('footway','path','cycleway','steps'):
        return max(3,lanes*3.2)
    return {'motorway':12,'trunk':10,'primary':9,'secondary':8,'tertiary':7,'residential':5,'unclassified':5,'service':3.2,'living_street':4,'pedestrian':4,'footway':1.6,'path':1.3,'cycleway':2,'steps':1.5,'track':3}.get(k,3)

def solid_geometry(p,h):
    if len(p)<3 or abs(signed_area(p))<.03:raise ValueError('Degenerate footprint')
    if signed_area(p)<0:p=list(reversed(p))
    n=len(p); pts=[(x,0,z) for x,z in p]+[(x,h,z) for x,z in p]
    faces=[list(range(n)),list(reversed(range(n,2*n)))]
    faces.extend([i,i+n,(i+1)%n+n,(i+1)%n] for i in range(n))
    return pts,faces

def surface_geometry(p,y):
    if len(p)<3 or abs(signed_area(p))<.03:raise ValueError('Degenerate area')
    if signed_area(p)>0:p=list(reversed(p))
    return [(x,y,z) for x,z in p],[list(range(len(p)))]

def road_geometry(p,width,y):
    if len(p)<2:raise ValueError('Degenerate road')
    dirs=[]
    for a,b in zip(p,p[1:]):
        dx,dz=b[0]-a[0],b[1]-a[1]; length=math.hypot(dx,dz)
        if length<.0001:raise ValueError('Degenerate segment')
        dirs.append((-dz/length,dx/length))
    pts=[];half=width/2
    for i,(x,z) in enumerate(p):
        a=dirs[max(0,i-1)];b=dirs[min(i,len(dirs)-1)];mx,mz=a[0]+b[0],a[1]+b[1];mag=math.hypot(mx,mz)
        if mag<.01:mx,mz=b;scale=half
        else:
            mx,mz=mx/mag,mz/mag;scale=min(half*2.5,half/max(.4,mx*b[0]+mz*b[1]))
        pts.extend([(x+mx*scale,y,z+mz*scale),(x-mx*scale,y,z-mz*scale)])
    faces=[[2*i,2*i+2,2*i+3,2*i+1] for i in range(len(p)-1)]
    # The left-to-right ordering above produces upward normals in X/Z.
    return pts,faces

def mesh(name,parent,pts,faces,sg):
    tr=cmds.createNode('transform',name=name,parent=parent)
    tr=parent+'|'+tr.split('|')[-1] if parent.startswith('|') else cmds.ls(tr,long=True)[0]
    try:
        sel=om.MSelectionList();sel.add(tr);par=sel.getDependNode(0)
        points=om.MPointArray(); counts=om.MIntArray(); connects=om.MIntArray()
        for x,y,z in pts:points.append(om.MPoint(x*100,y*100,z*100)) # Maya API uses cm
        for face in faces:
            counts.append(len(face))
            for i in face:connects.append(i)
        obj=om.MFnMesh().create(points,counts,connects,parent=par)
        fn=om.MFnMesh(obj)
        # Face-local planar UVs in metres for editable architectural geometry.
        us=[];vs=[];uv_ids=[]
        for face in faces:
            nx=ny=nz=0.
            for ia,ib in zip(face,face[1:]+face[:1]):
                a,b=pts[ia],pts[ib];nx+=(a[1]-b[1])*(a[2]+b[2]);ny+=(a[2]-b[2])*(a[0]+b[0]);nz+=(a[0]-b[0])*(a[1]+b[1])
            axis=max(range(3),key=lambda i:abs((nx,ny,nz)[i]));uaxis,vaxis=((2,1),(0,2),(0,1))[axis]
            uv_ids.extend(range(len(us),len(us)+len(face)))
            for i in face:us.append(pts[i][uaxis]);vs.append(pts[i][vaxis])
        if us:fn.setUVs(us,vs);fn.assignUVs([len(f) for f in faces],uv_ids)
        path=om.MDagPath.getAPathTo(obj).fullPathName()
        cmds.sets(path,edit=True,forceElement=sg)
        return tr
    except Exception:
        if cmds.objExists(tr):cmds.delete(tr)
        raise

def attr(node,name,value):
    cmds.addAttr(node,longName=name,dataType='string')
    cmds.setAttr(node+'.'+name,str(value),type='string')

def material(name,color):
    # Use uniquely named materials per import; no existing scene materials modified.
    mat=cmds.shadingNode('lambert',asShader=True,name=name)
    sg=cmds.sets(renderable=True,noSurfaceShader=True,empty=True,name=mat+'SG')
    cmds.setAttr(mat+'.color',*color,type='double3')
    cmds.connectAttr(mat+'.outColor',sg+'.surfaceShader',force=True)
    return mat,sg

def tls_context():
    # macOS Maya may have its own CA bundle. Use certifi if already available.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except (ImportError,OSError):
        return ssl.create_default_context()

def download_osm(b,endpoint,cache_dir):
    s,w,n,e=b; bb=','.join('%.7f'%v for v in b)
    query='[out:json][timeout:45];(way["building"](%s);way["highway"](%s);way["natural"="water"](%s);way["waterway"="riverbank"](%s);way["leisure"="park"](%s);way["landuse"~"^(grass|forest|recreation_ground|meadow)$"](%s);way["natural"="wood"](%s););out geom;' % ((bb,)*7)
    key=hashlib.sha256((endpoint+query).encode()).hexdigest()[:24]; path=os.path.join(cache_dir,key+'.json')
    if os.path.isfile(path) and time.time()-os.path.getmtime(path)<86400:
        try:
            with open(path,encoding='utf-8') as f:data=json.load(f)
            if isinstance(data.get('elements'),list) and not data.get('remark'):return data,True
        except (OSError,ValueError):pass
    req=urllib.request.Request(endpoint,data=urllib.parse.urlencode({'data':query}).encode(),headers={'User-Agent':'Maya-OSM-City-Importer/1.0 (interactive desktop client)','Accept':'application/json'})
    raw=verified_request(req,40*1024*1024,65)
    if len(raw)>40*1024*1024:raise ValueError('Response too large; select a smaller area.')
    data=json.loads(raw.decode('utf-8'))
    if data.get('remark'):raise RuntimeError(str(data['remark']))
    if not isinstance(data.get('elements'),list):raise ValueError('Unexpected Overpass response.')
    try:
        os.makedirs(cache_dir,exist_ok=True)
        with open(path+'.tmp','w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False)
        os.replace(path+'.tmp',path)
    except OSError:pass
    return data,False

class CityImporter:
    def __init__(self):
        self.win='OSMCityImporterWindow';self.bbox=DEFAULT_BBOX;self.selection=None;self.server=None
        self.token=secrets.token_urlsafe(24);self.lock=threading.Lock();self.result=None;self.busy=False;self.timer=None
        self.cache_dir=os.path.join(cmds.internalVar(userAppDir=True),'osm_city_cache')
    def close_server(self):
        if self.server:
            srv=self.server;self.server=None
            threading.Thread(target=lambda:(srv.shutdown(),srv.server_close()),daemon=True).start()
    def dispose(self):
        if self.timer:self.timer.stop()
        self.close_server()
    def open_map(self,*_):
        if not self.server:
            app=self; prefix='/'+self.token+'/'
            class Handler(BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def respond(self,code,data,kind):
                    self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
                def do_GET(self):
                    if self.path==prefix:
                        with app.lock:b=app.bbox
                        self.respond(200,HTML.replace('__BBOX__',json.dumps(b)).encode('utf-8'),'text/html; charset=utf-8')
                    else:self.respond(404,b'Not found','text/plain')
                def do_POST(self):
                    if self.path!=prefix+'selection':self.respond(404,b'{}','application/json');return
                    try:
                        if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('Invalid content type')
                        length=int(self.headers.get('Content-Length','0'))
                        if not 0<length<1024:raise ValueError('Invalid request length')
                        b=validate_bbox(json.loads(self.rfile.read(length)))
                        with app.lock:app.selection=b
                        self.respond(200,b'{"ok":true}','application/json')
                    except Exception as exc:self.respond(400,json.dumps({'error':str(exc)}).encode(),'application/json')
            self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            threading.Thread(target=self.server.serve_forever,daemon=True).start()
        try:
            with self.lock:self.bbox=self.read_bbox()
        except ValueError:pass
        url='http://127.0.0.1:%d/%s/'%(self.server.server_address[1],self.token)
        webbrowser.open(url);self.status('Map opened in browser. If needed: '+url)
    def read_bbox(self):return validate_bbox([cmds.floatField(f,q=True,value=True) for f in self.fields])
    def get_selection(self,*_):
        with self.lock:b=self.selection
        if b is None:self.status('No map selection received. Send it from the browser first.');return
        for f,v in zip(self.fields,b):cmds.floatField(f,e=True,value=v)
        self.bbox=b;self.status('Map selection received. Press Import City.')
    def status(self,s):
        if cmds.window(self.win,exists=True):cmds.text(self.status_text,e=True,label=s)
    def show(self):
        if cmds.window(self.win,exists=True):cmds.deleteUI(self.win)
        cmds.window(self.win,title='OSM City Importer v'+VERSION,widthHeight=(485,510),sizeable=True)
        cmds.columnLayout(adjustableColumn=True,rowSpacing=7)
        cmds.text(label='OpenStreetMap → editable Maya geometry',height=28,align='center',font='boldLabelFont')
        cmds.button(label='1. 地図を開く / Open Map',height=35,command=self.open_map)
        cmds.button(label='2. 選択範囲を取得 / Receive Selection',height=32,command=self.get_selection)
        cmds.text(label='Bounds (latitude / longitude) — editable',align='left')
        self.fields=[]
        for label,v in zip(('South / 南','West / 西','North / 北','East / 東'),self.bbox):
            cmds.rowLayout(numberOfColumns=2,adjustableColumn=2,columnWidth2=(125,300))
            cmds.text(label=label,align='left');self.fields.append(cmds.floatField(value=v,precision=7));cmds.setParent('..')
        cmds.separator(height=8,style='in')
        self.options={}
        for key,label in [('building','Buildings / 建物'),('road','Roads / 道路・歩道'),('water','Water / 水面'),('green','Green areas / 公園・緑地'),('ground','Flat ground / 平面地面')]:self.options[key]=cmds.checkBox(label=label,value=True)
        cmds.rowLayout(numberOfColumns=2,adjustableColumn=2,columnWidth2=(220,230));cmds.text(label='Default building height (m)');self.default=cmds.floatField(value=9,minValue=1,maxValue=100);cmds.setParent('..')
        cmds.rowLayout(numberOfColumns=2,adjustableColumn=2,columnWidth2=(220,230));cmds.text(label='Height per floor (m)');self.floor=cmds.floatField(value=3,minValue=1,maxValue=10);cmds.setParent('..')
        cmds.text(label='Overpass endpoint (HTTPS):',align='left');self.endpoint=cmds.textField(text='https://overpass-api.de/api/interpreter')
        self.import_button=cmds.button(label='3. Import City / 街並みを生成',height=42,command=self.start_import)
        self.status_text=cmds.text(label='Ready. Choose a small area first.',align='left',wordWrap=True,height=52)
        cmds.text(label='© OpenStreetMap contributors | ODbL',align='center')
        cmds.text(label='Flat terrain, estimated heights where unavailable.',align='center')
        cmds.showWindow(self.win)
    def start_import(self,*_):
        if self.busy:return
        try:
            if cmds.upAxis(q=True,axis=True)!='y':raise ValueError('Y-up Maya scenes only. Change up axis before import.')
            b=self.read_bbox(); endpoint=cmds.textField(self.endpoint,q=True,text=True).strip()
            if not endpoint.startswith('https://'):raise ValueError('Use an HTTPS Overpass endpoint.')
            opts={k:cmds.checkBox(v,q=True,value=True) for k,v in self.options.items()}
            if not any(opts.values()):raise ValueError('Enable at least one layer.')
            default=cmds.floatField(self.default,q=True,value=True);floor=cmds.floatField(self.floor,q=True,value=True)
        except Exception as exc:cmds.confirmDialog(title='OSM Importer',message=str(exc),button=['OK']);return
        self.busy=True;self.result=None;self.bbox=b;cmds.button(self.import_button,e=True,enable=False);self.status('Downloading OpenStreetMap data… (up to 65 seconds)')
        def worker():
            try:self.result=(True,download_osm(b,endpoint,self.cache_dir),b,opts,default,floor)
            except Exception as exc:self.result=(False,str(exc),b,opts,default,floor)
        threading.Thread(target=worker,daemon=True).start()
        self.timer=QtCore.QTimer();self.timer.timeout.connect(self.poll);self.timer.start(250)
    def poll(self):
        if self.result is None:return
        self.timer.stop();ok,payload,b,opts,default,floor=self.result;self.result=None
        try:
            if not ok:raise RuntimeError(payload)
            data,cached=payload;self.status('Generating geometry on Maya main thread…')
            cmds.refresh(force=True)
            summary=self.build(data,b,opts,default,floor)
            self.status(('Cached data. ' if cached else '')+summary);print('[OSM City] '+summary)
        except Exception as exc:
            self.status('Import failed: '+str(exc));cmds.warning('OSM City: '+str(exc));traceback.print_exc()
            if cmds.window(self.win,exists=True):cmds.confirmDialog(title='OSM Importer',message=str(exc),button=['OK'])
        finally:
            self.busy=False
            if cmds.window(self.win,exists=True):cmds.button(self.import_button,e=True,enable=True)
    def build(self,data,b,opts,default,floor):
        elements=data['elements']; nbuild=sum(1 for e in elements if e.get('tags',{}).get('building') not in (None,'no'))
        if opts['building'] and nbuild>MAX_BUILDINGS:raise ValueError('More than 2,000 buildings. Select a smaller area.')
        root=cmds.group(empty=True,name='OSM_City#');created_materials=[];counts={k:0 for k in opts};skipped=0;estimated=0
        colors={'building':(.58,.61,.65),'road':(.13,.15,.17),'water':(.12,.34,.48),'green':(.22,.42,.22),'ground':(.43,.43,.38)}
        groups={};sgs={};combined={k:([],[]) for k in ('road','water','green')}
        try:
            attr(root,'osmAttribution',CREDIT);attr(root,'osmBounds',json.dumps(b));attr(root,'osmOriginLatLon',json.dumps([(b[0]+b[2])/2,(b[1]+b[3])/2]));attr(root,'osmAxes','X east, Y up, -Z north; 1 metre = 100 cm; local equirectangular projection')
            for k,on in opts.items():
                if on:
                    groups[k]=cmds.group(empty=True,name=root.split('|')[-1]+'_'+k.title(),parent=root);mat,sg=material('OSM_'+k+'_MAT#',colors[k]);created_materials.extend([mat,sg]);sgs[k]=sg
            if opts['ground']:
                x,z=span(b);pts,faces=surface_geometry([(-x/2,-z/2),(x/2,-z/2),(x/2,z/2),(-x/2,z/2)],-.03);mesh(root.split('|')[-1]+'_Ground',groups['ground'],pts,faces,sgs['ground']);counts['ground']=1
            for e in elements:
                t=e.get('tags',{});geo=e.get('geometry') or [];k=None
                if t.get('building') not in (None,'no'):k='building'
                elif t.get('highway') not in (None,'construction','proposed','abandoned','platform','raceway'):
                    if t.get('tunnel') not in (None,'no') or t.get('bridge') not in (None,'no'):continue
                    k='road'
                elif t.get('natural')=='water' or t.get('waterway')=='riverbank':k='water'
                elif t.get('leisure')=='park' or t.get('natural')=='wood' or t.get('landuse') in ('grass','forest','recreation_ground','meadow'):k='green'
                if not k or not opts.get(k):continue
                try:
                    if not geo or any('lat' not in p or 'lon' not in p for p in geo):raise ValueError('Missing geometry')
                    is_closed=geo[0]==geo[-1]
                    if k!='road' and not is_closed:raise ValueError('Open outline')
                    p=clean_points([project(g['lat'],g['lon'],b) for g in geo],closed=k!='road')
                    if k=='building':
                        h,source=building_height(t,default,floor);pts,faces=solid_geometry(p,h)
                        tr=mesh(root.split('|')[-1]+'_Building_'+str(e['id']),groups[k],pts,faces,sgs[k]);attr(tr,'osmID',e['id']);attr(tr,'osmHeightSource',source);attr(tr,'osmHeightMetres',h)
                        if source=='estimated':estimated+=1
                    else:
                        if k=='road':pts,faces=road_geometry(p,road_width(t),.07)
                        else:pts,faces=surface_geometry(p,.01 if k=='green' else .035)
                        cp,cf=combined[k];offset=len(cp);cp.extend(pts);cf.extend([[i+offset for i in face] for face in faces])
                    counts[k]+=1
                except Exception as exc:
                    skipped+=1
                    if skipped<=5:print('[OSM City] skipped way',e.get('id'),str(exc))
            for k,(pts,faces) in combined.items():
                if pts:mesh(root.split('|')[-1]+'_'+k.title()+'_Mesh',groups[k],pts,faces,sgs[k])
            cmds.select(root,replace=True)
            return 'Buildings %d (%d estimated), roads %d, water %d, green %d, skipped %d. Delete %s to remove geometry.'%(counts['building'],estimated,counts['road'],counts['water'],counts['green'],skipped,root)
        except Exception:
            if cmds.objExists(root):cmds.delete(root)
            for node in reversed(created_materials):
                if cmds.objExists(node):cmds.delete(node)
            raise


# City Builder v2 extensions. All geographic values in metres / degrees.
import xml.etree.ElementTree as ET
import zipfile
import posixpath
import random
import urllib.error
import shutil
import subprocess
import tempfile
import http.client
import sys

PLATEAU_API='https://api.plateauview.mlit.go.jp'
PLATEAU_CREDIT='Source: Project PLATEAU, MLIT (https://www.mlit.go.jp/plateau/); processed by Maya City Builder'
GSI_CREDIT='Source: Geospatial Information Authority of Japan, elevation tiles (https://maps.gsi.go.jp/development/demtile.html); processed'
MAX_DETAILS=40000
MAX_PLATEAU_FACES=250000
# Large downloads are written to disk, not accumulated in RAM.
MIB=1024*1024
GIB=1024*MIB
MAX_PACK_BYTES=8*GIB
MAX_GML_BYTES=4*GIB
MAX_GML_TOTAL=16*GIB
DISK_RESERVE=512*MIB
DOWNLOAD_CHUNK=1024*1024


def verified_request(req,limit,timeout):
    try:
        with urllib.request.urlopen(req,timeout=timeout,context=tls_context()) as res:
            raw=res.read(limit+1)
    except (urllib.error.URLError,ssl.SSLError) as exc:
        # macOS Maya may ship an incompatible SSL runtime. System curl retains TLS verification.
        if sys.platform!='darwin' or not any(k in str(exc).lower() for k in ('ssl','tls','certificate')):raise
        fd,out=tempfile.mkstemp(prefix='maya_city_');os.close(fd)
        try:
            args=['/usr/bin/curl','--silent','--show-error','--location','--max-redirs','5','--proto','=https','--proto-redir','=https','--max-time',str(timeout),'--max-filesize',str(limit),'--output',out,'--write-out','%{http_code}']
            for k,v in req.header_items():args.extend(['--header',k+': '+v])
            if req.data is not None:args.extend(['--request','POST','--data-binary','@-'])
            args.append(req.full_url)
            done=subprocess.run(args,input=req.data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout+5,check=False)
            code=int(done.stdout.decode().strip() or '0')
            if code>=400:raise urllib.error.HTTPError(req.full_url,code,'HTTP error from system curl',None,None)
            if done.returncode:raise RuntimeError('macOS verified curl failed: '+done.stderr.decode(errors='replace'))
            with open(out,'rb') as f:raw=f.read(limit+1)
        finally:
            try:os.remove(out)
            except OSError:pass
    if len(raw)>limit:raise ValueError('Response exceeds download size limit.')
    return raw

def get_bytes(url,limit=100*1024*1024,body=None):
    req=urllib.request.Request(url,data=body,headers={'User-Agent':'Maya-City-Builder/2.3','Accept':'*/*',**({'Content-Type':'application/json'} if body is not None else {})})
    raw=verified_request(req,limit,90)
    if len(raw)>limit:raise ValueError('Download exceeds size limit. Choose a smaller area or use local CityGML.')
    return raw

def api_json(path,body=None):
    return json.loads(get_bytes(PLATEAU_API+path,8*1024*1024,None if body is None else json.dumps(body).encode()))

def cached_bytes(url,folder,limit=100*1024*1024,ext='.bin'):
    os.makedirs(folder,exist_ok=True); path=os.path.join(folder,hashlib.sha256(url.encode()).hexdigest()[:32]+ext)
    if os.path.isfile(path) and os.path.getsize(path)<=limit:
        with open(path,'rb') as f:return f.read()
    raw=get_bytes(url,limit); tmp=path+'.'+secrets.token_hex(5)+'.tmp'
    with open(tmp,'wb') as f:f.write(raw)
    os.replace(tmp,path);return raw

# Network resilience: keep service and request stage in the error, retry only transient failures.
TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504}

def transient_error(exc):
    if isinstance(exc, urllib.error.HTTPError):return exc.code in TRANSIENT_HTTP
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead)) and not any(x in str(exc).lower() for x in ('certificate','ssl','tls'))

def network_call(label, action, progress, attempts=3):
    for i in range(attempts):
        try:return action()
        except Exception as exc:
            if i+1>=attempts or not transient_error(exc):raise
            delay=2**(i+1)
            if isinstance(exc,urllib.error.HTTPError) and exc.headers:
                try:delay=max(delay,min(30,int(exc.headers.get('Retry-After','0'))))
                except (ValueError,TypeError):pass
            progress('%s: %s; retry %d/%d in %ds'%(label,str(exc),i+2,attempts,delay));time.sleep(delay)

def mesh_codes(b):
    # JIS X 0410 third-level cells: latitude 30 arcsec, longitude 45 arcsec.
    s,w,n,e=b; codes=[]
    for iy in range(math.floor(s*120), math.floor(n*120)+1):
        for ix in range(math.floor(w*80),math.floor(e*80)+1):
            lat0,latrem=divmod(iy,80);lon0,lonrem=divmod(ix,80)
            a,c=divmod(latrem,10);d,f=divmod(lonrem,10)
            codes.append('%02d%02d%d%d%d%d'%(lat0,lon0-100,a,d,c,f))
    return codes

def plateau_city_records(obj):
    # Actual REST response is {"cities": [...], "featureTypes": {...}}.
    # Also accept a single city or the legacy flat array of cities.
    if isinstance(obj, dict):
        if 'cities' in obj:
            cities=obj['cities']
            if not isinstance(cities,list):
                raise ValueError('Unexpected PLATEAU catalog: cities is not an array.')
            return cities
        if isinstance(obj.get('files'),dict):return [obj]
        if obj.get('error'):raise ValueError('PLATEAU API: '+str(obj['error'])[:300])
        raise ValueError('Unexpected PLATEAU catalog keys: '+', '.join(sorted(obj.keys())[:20]))
    if isinstance(obj,list):return obj
    raise ValueError('Unexpected PLATEAU catalog JSON type: '+type(obj).__name__)

def extract_plateau_urls(obj):
    urls=[]
    for r in plateau_city_records(obj):
        if not isinstance(r,dict):continue
        files=r.get('files') or {}
        if not isinstance(files,dict):continue
        buildings=files.get('bldg') or []
        if not isinstance(buildings,list):continue
        for f in buildings:
            if not isinstance(f,dict):continue
            u=f.get('url','')
            if not isinstance(u,str):continue
            parsed=urllib.parse.urlsplit(u)
            if (parsed.scheme=='https' and parsed.hostname=='assets.cms.plateau.reearth.io'
                    and parsed.username is None and parsed.password is None
                    and parsed.path.lower().endswith('.gml') and u not in urls):
                urls.append(u)
    return urls

def plateau_catalog_summary(obj):
    records=plateau_city_records(obj)
    names=[];count=0;hosts=set()
    for r in records:
        if not isinstance(r,dict):continue
        names.append(str(r.get('cityName') or r.get('cityCode') or '?'))
        files=r.get('files') or {}
        items=(files.get('bldg') or []) if isinstance(files,dict) else []
        if not isinstance(items,list):continue
        count+=len(items)
        for f in items:
            if isinstance(f,dict) and isinstance(f.get('url'),str):
                hosts.add(urllib.parse.urlsplit(f['url']).hostname or '(none)')
    return 'cities=%d (%s), bldg entries=%d, URL hosts=%s'%(len(records),', '.join(names[:8]),count,', '.join(sorted(hosts)) or '(none)')

def write_catalog_json(path,obj):
    tmp=path+'.'+secrets.token_hex(4)+'.tmp'
    try:
        with open(tmp,'w',encoding='utf8') as f:json.dump(obj,f,ensure_ascii=False,indent=2)
        os.replace(tmp,path)
    except OSError as exc:
        print('[City Builder] Cannot save catalog:',exc)
    finally:
        if os.path.exists(tmp):os.remove(tmp)

def plateau_urls(b,folder,progress):
    s,w,n,e=b
    if not (20<s<n<46 and 122<w<e<154):raise ValueError('PLATEAU online mode covers Japan only.')
    os.makedirs(folder,exist_ok=True)
    key=hashlib.sha256(json.dumps(b).encode()).hexdigest()[:24]
    manifest=os.path.join(folder,'plateau_catalog_'+key+'.json')
    if os.path.isfile(manifest) and time.time()-os.path.getmtime(manifest)<7*86400:
        try:
            with open(manifest,encoding='utf8') as f:urls=extract_plateau_urls(json.load(f))
            if 0<len(urls)<=16:
                print('[City Builder] PLATEAU cached catalog: %d GML files'%len(urls));return urls
        except (OSError,ValueError,TypeError,AttributeError):pass
    rect='r:%.7f,%.7f,%.7f,%.7f'%(w,s,e,n)
    mesh='m:'+','.join(mesh_codes(b));errors=[]
    for label,condition in [('rectangle',rect),('JIS mesh',mesh)]:
        path='/datacatalog/citygml/'+condition+'?types=bldg'
        progress('PLATEAU catalog: '+label)
        print('[City Builder] PLATEAU request:',PLATEAU_API+path)
        try:
            obj=network_call('PLATEAU catalog '+label,lambda:api_json(path),progress,2)
            diagnostic=os.path.join(folder,'plateau_catalog_debug_'+key+'_'+('rect' if label=='rectangle' else 'mesh')+'.json')
            write_catalog_json(diagnostic,obj)
            print('[City Builder] PLATEAU response saved:',diagnostic)
            summary=plateau_catalog_summary(obj)
            print('[City Builder] PLATEAU '+label+': '+summary)
            urls=extract_plateau_urls(obj)
            if not urls:raise ValueError('No usable building GML URLs. '+summary)
            if len(urls)>16:raise ValueError('More than 16 PLATEAU tiles. Select a smaller area.')
            write_catalog_json(manifest,obj)
            progress('PLATEAU catalog: %d GML files found'%len(urls))
            return urls
        except Exception as exc:
            errors.append('%s: %s'%(label,exc));print('[City Builder] PLATEAU catalog '+errors[-1])
    raise RuntimeError('PLATEAU catalog failed (api.plateauview.mlit.go.jp). '+' | '.join(errors)+' | Check Script Editor for request and response details. Use Local CityGML / ZIP if needed.')

def download_file(url,path,limit,progress,label,validate):
    """Atomic, bounded disk download. Never return a partial cache file."""
    os.makedirs(os.path.dirname(path),exist_ok=True)
    if os.path.isfile(path) and 0<os.path.getsize(path)<=limit:
        try:
            validate(path);progress(label+': cached %.1f MiB'%(os.path.getsize(path)/MIB));return path
        except (OSError,ValueError):pass
    tmp=path+'.'+secrets.token_hex(5)+'.part'
    req=urllib.request.Request(url,headers={'User-Agent':'Maya-City-Builder/2.3','Accept':'*/*','Accept-Encoding':'identity'})
    def check_space(n):
        free=shutil.disk_usage(os.path.dirname(path)).free
        if n+DISK_RESERVE>free:raise OSError('Not enough disk space for '+label+' (cache: '+os.path.dirname(path)+'). Free space and retry.')
    def transfer():
        check_space(0)
        try:
            with urllib.request.urlopen(req,timeout=120,context=tls_context()) as res:
                length=res.headers.get('Content-Length');expected=int(length) if length and length.isdigit() else None
                if expected is not None:
                    if expected>limit:raise ValueError('%s: %.2f GiB exceeds %.1f GiB safety limit.'%(label,expected/GIB,limit/GIB))
                    check_space(expected)
                size=0;last=0
                with open(tmp,'wb') as out:
                    while True:
                        chunk=res.read(DOWNLOAD_CHUNK)
                        if not chunk:break
                        size+=len(chunk)
                        if size>limit:raise ValueError('%s exceeds %.1f GiB safety limit.'%(label,limit/GIB))
                        if size-last>=8*MIB or last==0:
                            check_space(len(chunk));last=size
                            progress('%s: %.1f MiB%s'%(label,size/MIB,(' / %.1f MiB (%.0f%%)'%(expected/MIB,100*size/expected)) if expected else ''))
                        out.write(chunk)
                if expected is not None and size!=expected:raise http.client.IncompleteRead(b'',max(0,expected-size))
        except (urllib.error.URLError,ssl.SSLError) as exc:
            if sys.platform!='darwin' or not any(k in str(exc).lower() for k in ('ssl','tls','certificate')):raise
            # Use system curl with verified HTTPS. Bound both disk and file size.
            if os.path.exists(tmp):os.remove(tmp)
            cap=min(limit,shutil.disk_usage(os.path.dirname(path)).free-DISK_RESERVE)
            if cap<=0:raise OSError('Not enough cache disk space.')
            progress(label+': downloading with macOS verified curl...')
            args=['/usr/bin/curl','--silent','--show-error','--fail','--location','--max-redirs','5','--proto','=https','--proto-redir','=https','--connect-timeout','30','--max-time','3600','--max-filesize',str(cap),'--output',tmp,'--user-agent','Maya-City-Builder/2.3',url]
            done=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=3610,check=False)
            if done.returncode:raise RuntimeError('macOS curl: '+done.stderr.decode(errors='replace'))
        size=os.path.getsize(tmp)
        if size<=0 or size>limit:raise ValueError(label+': invalid download size.')
        validate(tmp);os.replace(tmp,path)
        progress(label+': saved %.1f MiB'%(size/MIB));print('[City Builder]',label,'saved',size,'bytes:',path)
        return path
    try:return network_call(label,transfer,progress,2)
    finally:
        if os.path.exists(tmp):os.remove(tmp)

def validate_zip_file(path):
    if not zipfile.is_zipfile(path):raise ValueError('PLATEAU returned an invalid ZIP.')
    with zipfile.ZipFile(path) as z:
        if not any(i.filename.lower().endswith('.gml') for i in z.infolist()):raise ValueError('PLATEAU ZIP has no CityGML.')

def validate_gml_file(path):
    with open(path,'rb') as f:head=f.read(65536)
    if not head.lstrip(b'\xef\xbb\xbf \t\r\n').startswith(b'<') or b'CityModel' not in head:raise ValueError('CMS did not return CityGML.')

def plateau_pack_only(urls,folder,progress):
    path=os.path.join(folder,'plateau_'+hashlib.sha256(json.dumps(urls).encode()).hexdigest()[:24]+'.zip')
    if os.path.isfile(path) and zipfile.is_zipfile(path) and time.time()-os.path.getmtime(path)<7*86400:return path
    progress('PLATEAU Pack: preparing %d building tiles...'%len(urls))
    # POST is not guaranteed idempotent: do not retry pack creation blindly.
    pid=api_json('/citygml/pack',{'urls':urls}).get('id','')
    if not isinstance(pid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',pid):raise ValueError('Invalid PLATEAU pack ID.')
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        result=network_call('PLATEAU pack status',lambda:api_json('/citygml/pack/'+pid+'/status'),progress,2);state=result.get('status')
        if state=='succeeded':break
        if state=='failed':raise RuntimeError('PLATEAU pack failed: '+str(result)[:300])
        progress('PLATEAU pack: '+str(state));time.sleep(3)
    else:raise RuntimeError('PLATEAU pack timed out.')
    progress('Downloading PLATEAU pack ZIP...')
    url=PLATEAU_API+'/citygml/pack/'+pid+'.zip'
    return download_file(url,path,MAX_PACK_BYTES,progress,'PLATEAU pack ZIP',validate_zip_file)

def plateau_direct_zip(urls,folder,progress):
    # Despite the legacy function name, store individual GML files directly on disk.
    # Each file is committed atomically; a subsequent run can reuse completed tiles.
    path=os.path.join(folder,'plateau_direct_'+hashlib.sha256(json.dumps(urls).encode()).hexdigest()[:24])
    os.makedirs(path,exist_ok=True);total=0
    for i,url in enumerate(urls):
        label='PLATEAU CMS GML %d/%d'%(i+1,len(urls));progress(label)
        name=posixpath.basename(urllib.parse.urlsplit(url).path)
        if not name.lower().endswith('.gml'):name='building.gml'
        dest=os.path.join(path,'tile_%02d'%i,'bldg',name)
        try:
            remaining=MAX_GML_TOTAL-total
            if remaining<=0:raise ValueError('Direct GML batch exceeds 16 GiB safety limit.')
            download_file(url,dest,min(MAX_GML_BYTES,remaining),progress,label,validate_gml_file)
            total+=os.path.getsize(dest)
        except Exception as exc:raise RuntimeError('%s (%s): %s'%(label,url,exc)) from exc
    return path

def plateau_pack(b,folder,progress,prefer_textures=True,direct_only=False,notices=None):
    notices=notices if notices is not None else []
    urls=plateau_urls(b,folder,progress)
    pack_error=None
    if prefer_textures and not direct_only:
        try:return plateau_pack_only(urls,folder,progress)
        except Exception as exc:
            pack_error=str(exc);print('[City Builder] PLATEAU Pack failed:',pack_error)
            notices.append('PLATEAU Pack failed; switched to direct CityGML (no photo textures).')
            progress('PLATEAU Pack failed; downloading individual GML files...')
    elif prefer_textures:
        notices.append('Direct CityGML: photo textures are not downloaded.')
    try:return plateau_direct_zip(urls,folder,progress)
    except Exception as exc:
        raise RuntimeError('PLATEAU download failed. '+(('Pack: '+pack_error+' | ') if pack_error else '')+'Direct: '+str(exc)+' | Use Local CityGML / ZIP.') from exc

def resilient_osm(b,endpoint,cache_dir,progress):
    try:return network_call('OpenStreetMap / Overpass',lambda:download_osm(b,endpoint,cache_dir),progress,2)
    except Exception as exc:raise RuntimeError('OpenStreetMap / Overpass (%s): %s'%(endpoint,exc)) from exc

def localname(t):return t.rsplit('}',1)[-1]
def xa(el,key,default=''):
    return next((v for k,v in el.attrib.items() if localname(k)==key),default)
def children(el,name):return [c for c in el if localname(c.tag)==name]
def descendants(el,name):return (c for c in el.iter() if localname(c.tag)==name)
def first(el,name):return next(descendants(el,name),None)
def txt(el):return (el.text or '').strip() if el is not None else ''
def floats(s):return [float(v) for v in s.split()]

def ring_coords(ring):
    pl=first(ring,'posList')
    if pl is not None:
        dim=int(xa(pl,'srsDimension',xa(ring,'srsDimension','3'))); vals=floats(txt(pl))
        if dim!=3 or len(vals)%3:raise ValueError('Only 3D geographic CityGML rings supported.')
        p=[tuple(vals[i:i+3]) for i in range(0,len(vals),3)]
    else:p=[tuple(floats(txt(x))) for x in descendants(ring,'pos')]
    if any(len(v)!=3 or not all(math.isfinite(x) for x in v) or not (-90<=v[0]<=90 and -180<=v[1]<=180) for v in p):raise ValueError('Unsupported coordinates; expected latitude, longitude, altitude.')
    if len(p)>1 and p[0]==p[-1]:p.pop()
    if len(p)<3:raise ValueError('Degenerate ring')
    return p

def overlaps(p,b):
    s,w,n,e=b;return max(v[0] for v in p)>=s and min(v[0] for v in p)<=n and max(v[1] for v in p)>=w and min(v[1] for v in p)<=e

def parse_citygml(raw,b,lod,resolve_texture,defer_textures=False):
    # PLATEAU uses EPSG:6697, latitude longitude orthometric height.
    if isinstance(raw,ET.Element):root=raw
    else:
        if re.search(br'<!\s*(DOCTYPE|ENTITY)',raw,re.I):raise ValueError('DTD/entity declarations are not supported.')
        root=ET.fromstring(raw)
    env=first(root,'Envelope')
    if env is not None:
        srs=xa(env,'srsName');
        if srs and not re.search(r'[:/]6697$',srs):raise ValueError('Unsupported CRS: '+srs+' (expected EPSG:6697).')
        lo=txt(first(env,'lowerCorner'));hi=txt(first(env,'upperCorner'))
        if lo and hi and not overlaps([floats(lo),floats(hi)],b):return [],0
    # Polygon/ring id map resolves same-document xlinks; do not resolve arbitrary remote XML.
    ids={xa(x,'id'):x for x in root.iter() if xa(x,'id')}
    textures={};skipped=0
    for t in (() if defer_textures else descendants(root,'ParameterizedTexture')):
        uri=txt(first(t,'imageURI'))
        if not uri:continue
        for target in descendants(t,'target'):
            pid=xa(target,'uri').lstrip('#')
            for uv in descendants(target,'textureCoordinates'):
                rid=xa(uv,'ring').lstrip('#');vals=floats(txt(uv)) if txt(uv) else []
                if pid and rid and len(vals)%2==0 and all(math.isfinite(v) for v in vals):
                    textures[(pid,rid)]=(uri,list(zip(vals[::2],vals[1::2])))
    def polygons(el,seen):
        if el is None:return
        if localname(el.tag)=='Polygon':
            pid=xa(el,'id') or str(id(el))
            if pid not in seen:seen.add(pid);yield el
            return
        href=xa(el,'href')
        if href.startswith('#') and href[1:] in ids and href not in seen:
            seen.add(href);yield from polygons(ids[href[1:]],seen)
        for c in el:yield from polygons(c,seen)
    def scopes(el):
        # Stop at nested building parts; they are imported separately if needed.
        for c in el:
            k=localname(c.tag)
            if k in ('Building','BuildingPart'):continue
            if re.match(r'lod[12](Solid|MultiSurface|Geometry)$',k):yield (int(k[3]),c)
            else:yield from scopes(c)
    def collect(el,want):
        nonlocal skipped
        seen=set();faces=[]
        for level,scope in scopes(el):
            if level!=want:continue
            for poly in polygons(scope,seen):
                if children(poly,'interior'):skipped+=1;continue # no filling courtyards / holes
                exterior=first(poly,'exterior');ring=first(exterior,'LinearRing') if exterior is not None else None
                if ring is None:skipped+=1;continue
                try:p=ring_coords(ring)
                except ValueError:skipped+=1;continue
                if defer_textures:
                    faces.append((p,(xa(poly,'id'),xa(ring,'id')),None));continue
                tex=None;uv=None;entry=textures.get((xa(poly,'id'),xa(ring,'id')))
                if entry:
                    uri,coords=entry
                    if len(coords)==len(p)+1:coords=coords[:-1]
                    if len(coords)==len(p):tex=uri;uv=coords
                faces.append((p,tex,uv))
        return faces
    records=[]
    def building(el):
        nonlocal skipped
        want=2 if lod!=1 else 1;faces=collect(el,want)
        if not faces and want==2:want=1;faces=collect(el,1)
        if not faces:
            for part in descendants(el,'BuildingPart'):
                # Only direct nested parts, recursion handles deeper nesting.
                if part is not el and any(part is q for wrapper in children(el,'consistsOfBuildingPart') for q in wrapper):building(part)
            return
        if not overlaps([v for p,_,_ in faces for v in p],b):return
        resolved=[]
        for p,uri,uv in faces:
            tex=uri if defer_textures else (resolve_texture(uri) if uri else None)
            resolved.append((p,tex,uv if tex else None))
        records.append((xa(el,'id') or 'building',want,resolved))
    for el in descendants(root,'Building'):building(el)
    return records,skipped

class SafeXMLStream:
    """Guard streamed XML against DTD/entity declarations, including split tokens."""
    def __init__(self,source):self.source=source;self.tail=b''
    def read(self,size=-1):
        data=self.source.read(size)
        scan=self.tail+data
        # PLATEAU is UTF-8; reject NUL (UTF-16/32) to prevent bypass of byte guard.
        if b'\x00' in data or re.search(br'<!\s*(DOCTYPE|ENTITY)',scan,re.I):raise ValueError('Unsupported XML encoding or DTD/entity declaration.')
        self.tail=scan[-128:]
        return data

def stream_citygml(opener,b,lod,resolve_texture,progress,use_textures=True):
    """Parse one cityObjectMember at a time; second pass links only selected UVs.
    Same-member xlinks are preserved; cross-member references are not expanded.
    """
    records=[];skipped=0;faces=0;members=0
    with opener() as raw:
        stack=[];root=None
        for ev,el in ET.iterparse(SafeXMLStream(raw),events=('start','end')):
            if ev=='start':
                stack.append(el)
                if len(stack)==1:
                    root=el
                    if localname(el.tag)!='CityModel':raise ValueError('Expected a CityGML CityModel root.')
                continue
            depth=len(stack);kind=localname(el.tag)
            if depth==2:
                if kind=='boundedBy':
                    env=first(el,'Envelope')
                    if env is not None:
                        srs=xa(env,'srsName')
                        if srs and not re.search(r'[:/]6697$',srs):raise ValueError('Unsupported CRS: '+srs+' (expected EPSG:6697).')
                        lo=txt(first(env,'lowerCorner'));hi=txt(first(env,'upperCorner'))
                        if lo and hi and not overlaps([floats(lo),floats(hi)],b):return [],0
                elif kind in ('cityObjectMember','Building','cityObjectMembers'):
                    # cityObjectMembers (plural) is handled per Building below.
                    if kind!='cityObjectMembers':
                        rows,n=parse_citygml(el,b,lod,lambda _:None,defer_textures=True)
                        records.extend(rows);skipped+=n;faces+=sum(len(x[2]) for x in rows);members+=1
                if faces>MAX_PLATEAU_FACES or len(records)>MAX_BUILDINGS:raise ValueError('PLATEAU selection exceeds geometry limit; reduce area.')
                if members and members%200==0:progress('Reading CityGML: %d objects scanned, %d selected'%(members,len(records)))
                root.remove(el);el.clear()
            elif depth==3 and localname(stack[1].tag)=='cityObjectMembers':
                rows,n=parse_citygml(el,b,lod,lambda _:None,defer_textures=True)
                records.extend(rows);skipped+=n;faces+=sum(len(x[2]) for x in rows);members+=1
                if faces>MAX_PLATEAU_FACES or len(records)>MAX_BUILDINGS:raise ValueError('PLATEAU selection exceeds geometry limit; reduce area.')
                stack[-2].remove(el);el.clear()
            elif depth>2 and localname(stack[1].tag) not in ('cityObjectMember','cityObjectMembers','Building','boundedBy'):
                # Do not retain large global appearance sections in geometry pass.
                stack[-2].remove(el);el.clear()
            stack.pop()
    wanted={key for _,_,polys in records for _,key,_ in polys if key and all(key)} if use_textures else set()
    entries={}
    if wanted:
        progress('Reading photo UVs for %d selected polygons...'%len(wanted))
        with opener() as raw:
            stack=[];texture_depth=0
            for ev,el in ET.iterparse(SafeXMLStream(raw),events=('start','end')):
                if ev=='start':
                    stack.append(el)
                    if not texture_depth and localname(el.tag)=='ParameterizedTexture':texture_depth=len(stack)
                    continue
                depth=len(stack)
                if texture_depth==depth:
                    uri=txt(first(el,'imageURI'))
                    if uri:
                        for target in descendants(el,'target'):
                            pid=xa(target,'uri').lstrip('#')
                            for uv in descendants(target,'textureCoordinates'):
                                key=(pid,xa(uv,'ring').lstrip('#'))
                                if key not in wanted:continue
                                try:vals=floats(txt(uv))
                                except ValueError:continue
                                if vals and len(vals)%2==0 and all(math.isfinite(v) for v in vals):entries[key]=(uri,list(zip(vals[::2],vals[1::2])))
                    texture_depth=0
                if not texture_depth and depth>1:stack[-2].remove(el);el.clear()
                stack.pop()
    out=[];resolved={}
    for ident,level,polys in records:
        pp=[]
        for p,key,_ in polys:
            tex=uv=None
            if key in entries:
                uri,coords=entries[key]
                if len(coords)==len(p)+1:coords=coords[:-1]
                if len(coords)==len(p):
                    if uri not in resolved:resolved[uri]=resolve_texture(uri)
                    tex=resolved[uri];uv=coords if tex else None
            pp.append((p,tex,uv))
        out.append((ident,level,pp))
    return out,skipped

def read_plateau(path,b,lod,cache,progress,use_textures=True):
    records=[];skipped=0;face_count=0;gml_count=0;total=0
    def add(opener,size,resolver):
        nonlocal skipped,face_count,gml_count,total
        total+=size
        if size>MAX_GML_BYTES or total>MAX_GML_TOTAL:raise ValueError('CityGML exceeds safety limit (4 GiB per tile / 16 GiB total). Select fewer local tiles.')
        rows,n=stream_citygml(opener,b,lod,resolver,progress,use_textures);skipped+=n;gml_count+=1
        face_count+=sum(len(x[2]) for x in rows);records.extend(rows)
        if len(records)>MAX_BUILDINGS or face_count>MAX_PLATEAU_FACES:raise ValueError('PLATEAU selection exceeds geometry limit; reduce area.')
    if os.path.isfile(path) and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            index={i.filename.replace('\\','/'):i for i in z.infolist() if not i.is_dir()}
            gm=[k for k in index if k.lower().endswith('.gml') and ('_bldg_' in k.lower() or '/bldg/' in k.lower())]
            if not gm:gm=[k for k in index if k.lower().endswith('.gml')]
            if len(gm)>400:raise ValueError('Archive contains over 400 GML tiles. Extract the relevant bldg folder or individual GML files.')
            texcache={}
            for k in gm:
                info=index[k];progress('Reading PLATEAU tile %d / %d (%.1f MiB)'%(gml_count+1,len(gm),info.file_size/MIB))
                def resolver(uri):
                    u=urllib.parse.unquote(uri).replace('\\','/');name=posixpath.normpath(posixpath.join(posixpath.dirname(k),u))
                    if name not in index or name.startswith('../') or name.startswith('/') or not name.lower().endswith(('.jpg','.jpeg','.png','.tif','.tiff')):return None
                    if name in texcache:return texcache[name]
                    inf=index[name]
                    if inf.file_size>50*MIB:return None
                    folder=os.path.join(cache,'textures');os.makedirs(folder,exist_ok=True)
                    dest=os.path.join(folder,hashlib.sha256((os.path.abspath(path)+str(os.path.getmtime(path))+name).encode()).hexdigest()[:28]+posixpath.splitext(name)[1])
                    if not os.path.isfile(dest):
                        tmp=dest+'.'+secrets.token_hex(4)+'.part'
                        try:
                            with z.open(inf) as src,open(tmp,'wb') as dst:shutil.copyfileobj(src,dst,DOWNLOAD_CHUNK)
                            os.replace(tmp,dest)
                        finally:
                            if os.path.exists(tmp):os.remove(tmp)
                    texcache[name]=dest;return dest
                add(lambda:z.open(info),info.file_size,resolver)
    else:
        if os.path.isdir(path):
            gm=[os.path.join(d,f) for d,_,fs in os.walk(path) for f in fs if f.lower().endswith('.gml') and ('_bldg_' in f.lower() or os.path.basename(d).lower()=='bldg')]
            if not gm:gm=[os.path.join(d,f) for d,_,fs in os.walk(path) for f in fs if f.lower().endswith('.gml')]
        elif os.path.isfile(path):gm=[path]
        else:raise ValueError('Choose a valid CityGML file, bldg folder, or ZIP.')
        if len(gm)>400:raise ValueError('Choose a smaller bldg folder (max 400 GML files).')
        for k in sorted(gm):
            size=os.path.getsize(k);progress('Reading PLATEAU tile %d / %d (%.1f MiB)'%(gml_count+1,len(gm),size/MIB))
            def resolver(uri):
                u=urllib.parse.unquote(uri).replace('\\','/')
                if urllib.parse.urlsplit(u).scheme or os.path.isabs(u):return None
                dest=os.path.realpath(os.path.join(os.path.dirname(k),u))
                return dest if os.path.isfile(dest) and dest.lower().endswith(('.jpg','.jpeg','.png','.tif','.tiff')) else None
            add(lambda:open(k,'rb'),size,resolver)
    if not records:raise ValueError('No LOD1/LOD2 buildings found in selection. Check bounds, CRS and source.')
    return records,skipped

# GSI 10 m DEM grid (text tiles); optional, Japan only.
def tile_pixel(lat,lon,z=14):
    scale=256*(2**z);return (lon+180)/360*scale,(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*scale

def terrain_grid(b,step,folder):
    s,w,n,e=b
    if not (20<s<n<46 and 122<w<e<154):raise ValueError('GSI terrain available in Japan only. Disable terrain for other regions.')
    sx,sz=span(b);nx=max(1,min(160,math.ceil(sx/step)));nz=max(1,min(160,math.ceil(sz/step)));tiles={}
    def sample(lat,lon):
        x,y=tile_pixel(lat,lon); ix,iy=int(x),int(y);key=(ix//256,iy//256)
        if key not in tiles:
            url='https://cyberjapandata.gsi.go.jp/xyz/dem/14/%d/%d.txt'%key
            try:
                rows=cached_bytes(url,folder,2*1024*1024,'.txt').decode().strip().splitlines();tiles[key]=[r.split(',') for r in rows]
            except urllib.error.HTTPError as exc:
                if exc.code!=404:raise
                tiles[key]=None
        t=tiles[key]
        if t is None:return None
        v=t[iy%256][ix%256];return None if v=='e' else float(v)
    values=[sample(n-(n-s)*j/nz,w+(e-w)*i/nx) for j in range(nz+1) for i in range(nx+1)]
    valid=[v for v in values if v is not None]
    if not valid:raise ValueError('No GSI elevation data for this area.')
    base=min(valid);missing=sum(v is None for v in values)
    # Nodata (typically water) approximated at sea level.
    return (nx,nz,sx,sz,[0.0 if v is None else v for v in values],base,missing)

def height_at(grid,x,z):
    if grid is None:return 0.
    nx,nz,sx,sz,v,base,_=grid;u=max(0,min(nx,(x/sx+.5)*nx));w=max(0,min(nz,(z/sz+.5)*nz));i=min(nx-1,int(u));j=min(nz-1,int(w));a=u-i;c=w-j;k=j*(nx+1)+i
    return (1-c)*((1-a)*v[k]+a*v[k+1])+c*((1-a)*v[k+nx+1]+a*v[k+nx+2])-base

def terrain_geo(grid):
    nx,nz,sx,sz,v,base,_=grid;p=[((i/nx-.5)*sx,v[j*(nx+1)+i]-base,(j/nz-.5)*sz) for j in range(nz+1) for i in range(nx+1)];f=[]
    for j in range(nz):
        for i in range(nx):
            k=j*(nx+1)+i;f.append([k,k+nx+1,k+nx+2,k+1])
    return p,f

def append_geo(dest,geo):
    p,f=dest;pp,ff=geo;off=len(p);p.extend(pp);f.extend([[i+off for i in face] for face in ff])

def detail_geo(p,h,base,floor,style,seed,max_count):
    # Boxes in edge-local coordinates, outward-facing thin extrusions; batched by material.
    p=list(p) if signed_area(p)>0 else list(reversed(p));rng=random.Random(seed);result={k:([],[]) for k in ('glass','trim','roof')};count=0
    levels=max(1,min(80,int(round(h/floor))));fh=h/levels;spacing={'Residential':2.6,'Office':2.0,'Industrial':4.0}[style]
    def box(k,a,b,nx,nz,u0,u1,y0,y1,d0,d1):
        nonlocal count
        if count>=max_count:return
        dx,dz=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dz);dx/=length;dz/=length
        poly=[(a[0]+dx*u+nx*d,a[1]+dz*u+nz*d) for u,d in [(u0,d0),(u1,d0),(u1,d1),(u0,d1)]]
        pts,faces=solid_geometry(poly,y1-y0);append_geo(result[k],([(x,y+base+y0,z) for x,y,z in pts],faces));count+=1
    for edge,(a,b) in enumerate(zip(p,p[1:]+p[:1])):
        dx,dz=b[0]-a[0],b[1]-a[1];L=math.hypot(dx,dz)
        if L<1:continue
        nx,nz=dz/L,-dx/L;cols=max(1,min(100,int(L/spacing)));bay=L/cols
        for j in range(levels):
            for i in range(cols):
                if count>=max_count:break
                if j==0 and edge==0 and i==cols//2 and L>2.5:
                    ww=min(1.3,bay*.65);y0=.04;y1=min(fh*.86,2.2);k='trim'
                elif fh>1.5:
                    ww=min(2.2,bay*(.72 if style=='Office' else .53));y0=j*fh+fh*.30;y1=j*fh+fh*.78;k='glass'
                else:continue
                center=(i+.5)*bay
                if ww>.25 and y1-y0>.2:box(k,a,b,nx,nz,center-ww/2,center+ww/2,y0,y1,.015,.09)
            if count>=max_count:break
        if h>2.5:box('roof',a,b,nx,nz,0,L,h,h+.35,-.10,.10)
    # Small rooftop equipment in the footprint's interior, only for convex-ish safe centroid.
    return result,count


def make_material(name,color,shader,texture=None,rough=.65,metal=0.):
    mat=None;sg=None;nodes=[]
    try:
        if shader=='OpenPBR':
            try:mat=cmds.shadingNode('openPBRSurface',asShader=True,name=name)
            except Exception:
                try:
                    if not cmds.pluginInfo('mtoa',q=True,loaded=True):cmds.loadPlugin('mtoa',quiet=True)
                    mat=cmds.shadingNode('openPBRSurface',asShader=True,name=name)
                except Exception:pass
        if mat is None:
            if shader=='OpenPBR':print('[City Builder] OpenPBR unavailable; using fallback material.')
            try:mat=cmds.shadingNode('standardSurface',asShader=True,name=name)
            except Exception:mat=cmds.shadingNode('lambert',asShader=True,name=name)
        nodes.append(mat);sg=cmds.sets(renderable=True,noSurfaceShader=True,empty=True,name=mat+'SG');nodes.append(sg)
        def set_existing(keys,v):
            for k in keys:
                if cmds.attributeQuery(k,node=mat,exists=True):
                    if isinstance(v,tuple):cmds.setAttr(mat+'.'+k,*v,type='double3')
                    else:cmds.setAttr(mat+'.'+k,v)
                    return k
        color_attr=set_existing(('baseColor','color'),color);set_existing(('baseWeight','base'),1.);set_existing(('specularRoughness','roughness'),rough);set_existing(('baseMetalness','metalness'),metal)
        cmds.connectAttr(mat+'.outColor',sg+'.surfaceShader',force=True)
        if texture:
            f=cmds.shadingNode('file',asTexture=True,name='City_Texture#');nodes.append(f);p=cmds.shadingNode('place2dTexture',asUtility=True,name='City_UV#');nodes.append(p)
            for a in ('coverage','translateFrame','rotateFrame','mirrorU','mirrorV','stagger','wrapU','wrapV','repeatUV','offset','rotateUV','noiseUV','vertexUvOne','vertexUvTwo','vertexUvThree','vertexCameraOne'):
                cmds.connectAttr(p+'.'+a,f+'.'+a,force=True)
            cmds.connectAttr(p+'.outUV',f+'.uvCoord',force=True);cmds.connectAttr(p+'.outUvFilterSize',f+'.uvFilterSize',force=True)
            cmds.setAttr(f+'.fileTextureName',texture.replace('\\','/'),type='string');cmds.connectAttr(f+'.outColor',mat+'.'+color_attr,force=True)
        return sg,nodes
    except Exception:
        for n in reversed(nodes):
            if cmds.objExists(n):cmds.delete(n)
        raise

def textured_mesh(name,parent,pts,faces,sg,face_uv,face_sgs):
    tr=mesh(name,parent,pts,faces,sg)
    try:
        shape=cmds.listRelatives(tr,shapes=True,fullPath=True)[0];sel=om.MSelectionList();sel.add(shape);fn=om.MFnMesh(sel.getDagPath(0));us=[];vs=[];counts=[];uv_ids=[]
        for i,uv in enumerate(face_uv):
            if not uv:
                uv=[fn.getUV(fn.getPolygonUVid(i,j)) for j in range(len(faces[i]))]
            counts.append(len(uv) if uv else 0)
            if uv:
                uv_ids.extend(range(len(us),len(us)+len(uv)));us.extend(x[0] for x in uv);vs.extend(x[1] for x in uv)
        if us and any(face_uv):fn.clearUVs();fn.setUVs(us,vs);fn.assignUVs(counts,uv_ids)
        for g,inds in face_sgs.items():
            # Assign by contiguous ranges where possible.
            runs=[]
            for i in inds:
                if runs and runs[-1][1]+1==i:runs[-1][1]=i
                else:runs.append([i,i])
            comps=[shape+'.f[%d%s]'%(a,(':%d'%b) if b!=a else '') for a,b in runs]
            if comps:cmds.sets(comps,edit=True,forceElement=g)
        return tr
    except Exception:
        cmds.delete(tr);raise

# Procedural Japan: all geometry in metres; deterministic, editable, batched by material.
JP_COLORS={'jp_wall_warm':(.72,.65,.54),'jp_wall_white':(.78,.79,.76),'jp_wall_gray':(.47,.50,.52),'jp_tile':(.18,.21,.24),'jp_tile_brown':(.31,.24,.20),'jp_frame':(.29,.30,.30),'jp_glass':(.17,.29,.36),'jp_balcony':(.60,.60,.57),'jp_ac':(.78,.79,.75),'jp_pole':(.48,.49,.47),'jp_wire':(.035,.039,.044),'jp_metal':(.61,.64,.65),'jp_white':(.88,.88,.82),'jp_yellow':(.91,.63,.12),'jp_red':(.72,.065,.045),'jp_green':(.055,.53,.23),'jp_sign':(.12,.24,.46),'jp_dark':(.08,.10,.12),'jp_blue':(.11,.31,.66)}
JP_MAX_STREET_PARTS=12000

def jp_box(a,dx,dz,u0,u1,d0,d1,y0,y1):
    nx,nz=-dz,dx
    poly=[(a[0]+dx*u+nx*d,a[1]+dz*u+nz*d) for u,d in ((u0,d0),(u1,d0),(u1,d1),(u0,d1))]
    # Thin trim pieces are intentionally much smaller than a building footprint.
    if u1<=u0 or d1<=d0 or y1<=y0:return [],[]
    pts=[(x,y,z) for y in (y0,y1) for x,z in poly]
    faces=[[0,1,2,3],[7,6,5,4]]+[[i,i+4,(i+1)%4+4,(i+1)%4] for i in range(4)]
    return pts,faces

def jp_tube(a,b,r,sides=6):
    # Oriented polygon cylinder with closed end caps.
    vx,vy,vz=(b[i]-a[i] for i in range(3));L=math.sqrt(vx*vx+vy*vy+vz*vz)
    if L<.001:return [],[]
    vx,vy,vz=vx/L,vy/L,vz/L
    ref=(0,1,0) if abs(vy)<.9 else (1,0,0)
    ux,uy,uz=(vy*ref[2]-vz*ref[1],vz*ref[0]-vx*ref[2],vx*ref[1]-vy*ref[0]);m=math.sqrt(ux*ux+uy*uy+uz*uz);ux,uy,uz=ux/m,uy/m,uz/m
    wx,wy,wz=vy*uz-vz*uy,vz*ux-vx*uz,vx*uy-vy*ux
    pts=[(c[0]+r*(ux*math.cos(2*math.pi*i/sides)+wx*math.sin(2*math.pi*i/sides)),c[1]+r*(uy*math.cos(2*math.pi*i/sides)+wy*math.sin(2*math.pi*i/sides)),c[2]+r*(uz*math.cos(2*math.pi*i/sides)+wz*math.sin(2*math.pi*i/sides))) for c in (a,b) for i in range(sides)]
    faces=[list(reversed(range(sides))),list(range(sides,2*sides))]+[[i,(i+1)%sides,(i+1)%sides+sides,i+sides] for i in range(sides)]
    return pts,faces

def jp_add(out,k,geo):
    if geo[0]:append_geo(out.setdefault(k,([],[])),geo)

def jp_rect(p):
    # Reject concave or irregular plans; preserve original footprint for other roofs.
    if len(p)!=4:return None
    p=list(p) if signed_area(p)>0 else list(reversed(p));edges=[(b[0]-a[0],b[1]-a[1]) for a,b in zip(p,p[1:]+p[:1])];ls=[math.hypot(*e) for e in edges]
    if min(ls)<2.5 or max(ls)>45:return None
    for i in range(4):
        a,c=edges[i],edges[(i+1)%4]
        if abs(a[0]*c[0]+a[1]*c[1])/(ls[i]*ls[(i+1)%4])>.15:return None
    if abs(ls[0]-ls[2])>max(ls[0],ls[2])*.12 or abs(ls[1]-ls[3])>max(ls[1],ls[3])*.12:return None
    i=0 if ls[0]>=ls[1] else 1
    return p[i:]+p[:i]

def jp_kind(t,p,h,style):
    typ=t.get('building','yes');area=abs(signed_area(p));shop=t.get('shop') or typ in ('retail','commercial','supermarket')
    if typ in ('garage','garages','shed','hut','carport','roof','industrial','warehouse','factory','barn'):return 'service'
    if style=='Residential district':return 'apartment' if h>12 or typ=='apartments' else 'house'
    if style=='Urban / station district':return 'office' if h>=15 or shop or typ=='office' else ('apartment' if h>=8 or area>130 else 'house')
    if typ in ('office','hotel','commercial','retail','supermarket') or shop:return 'office'
    if typ in ('apartments','dormitory') or h>13 or area>220:return 'apartment'
    return 'house'

def jp_roof(p,top):
    q=jp_rect(p)
    if not q:return None
    cx=sum(x for x,z in q)/4;cz=sum(z for x,z in q)/4
    # Eaves extend about 30 cm on both axes; ridge along long edge.
    dx,dz=q[1][0]-q[0][0],q[1][1]-q[0][1];L=math.hypot(dx,dz);dx,dz=dx/L,dz/L;nx,nz=-dz,dx
    eaves=[]
    for x,z in q:
        u=(x-cx)*dx+(z-cz)*dz;v=(x-cx)*nx+(z-cz)*nz
        eaves.append((x+(.30 if u>0 else -.30)*dx+(.30 if v>0 else -.30)*nx,z+(.30 if u>0 else -.30)*dz+(.30 if v>0 else -.30)*nz))
    rise=min(2.4,max(.65,math.hypot(q[3][0]-q[0][0],q[3][1]-q[0][1])*.24))
    a,b,c,d=eaves;r0=((a[0]+d[0])/2,top+rise,(a[1]+d[1])/2);r1=((b[0]+c[0])/2,top+rise,(b[1]+c[1])/2)
    pts=[(x,top,z) for x,z in eaves]+[r0,r1]
    # Roof slopes + closed gable ends, outward normals in Y-up.
    return pts,[[0,4,5,1],[3,2,5,4],[0,3,4],[1,5,2],[0,1,2,3]]

def japan_building(p,h,base,floor,kind,seed,flags,budget):
    p=list(p) if signed_area(p)>0 else list(reversed(p));out={};used=0;rng=random.Random(seed)
    def add(k,geo):
        nonlocal used
        if used>=budget or not geo[0]:return False
        jp_add(out,k,geo);used+=1;return True
    if kind=='service':return out,used
    levels=max(1,min(40,int(round(h/floor))));fh=h/levels
    if flags['roofs']:
        roof=jp_roof(p,base+h) if kind=='house' and h<=13 else None
        if roof:
            add(rng.choice(('jp_tile','jp_tile_brown')),roof)
            # Ridge cap, visually distinct, low-poly.
            pts=roof[0];add('jp_tile',jp_tube(pts[4],pts[5],.12,6))
        else:
            for a,b in zip(p,p[1:]+p[:1]):
                dx,dz=b[0]-a[0],b[1]-a[1];L=math.hypot(dx,dz)
                if L>.3:add('jp_balcony',jp_box(a,dx/L,dz/L,0,L,-.09,.09,base+h,base+h+.32))
    # One longer facade gets entrance, balconies and AC. Windows on all sides.
    edges=list(zip(p,p[1:]+p[:1]));front=max(range(len(edges)),key=lambda i:math.dist(*edges[i]))
    for edge,(a,b) in enumerate(edges):
        L=math.dist(a,b)
        if L<1.1 or used>=budget:continue
        dx,dz=(b[0]-a[0])/L,(b[1]-a[1])/L;cols=max(1,min(30,int(L/(2.2 if kind=='office' else 2.8))));bay=L/cols
        def box(k,u0,u1,d0,d1,y0,y1):
            if u1-u0>.08 and y1-y0>.04 and d1-d0>.009:return add(k,jp_box(a,dx,dz,u0,u1,d0,d1,base+y0,base+y1))
        for j in range(levels):
            if used>=budget:break
            for i in range(cols):
                if used>=budget:break
                c=(i+.5)*bay;ww=min(2.1,bay*.67);y=j*fh
                if edge==front and j==0 and i==cols//2:
                    if flags['facades']:box('jp_frame',c-ww*.42,c+ww*.42,-.10,-.015,.04,min(2.25,fh*.85))
                    if kind=='office' and flags['facades'] and fh>2.5:box('jp_sign',max(.05,c-ww*.65),min(L-.05,c+ww*.65),-.16,-.02,min(2.25,fh*.78),min(2.65,fh*.95))
                    continue
                if flags['facades'] and fh>1.3:
                    lo=y+fh*.30;hi=y+fh*.78
                    box('jp_frame',c-ww/2,c+ww/2,-.10,-.015,lo,hi)
                    box('jp_glass',c-ww/2+.07,c+ww/2-.07,-.115,-.095,lo+.07,hi-.07)
                    if kind=='house' and ww>.8:box('jp_frame',c-.035,c+.035,-.13,-.11,lo,hi)
                if kind=='apartment' and edge==front and j>0 and flags['balconies'] and bay>1.5:
                    left,right=c-bay*.43,c+bay*.43
                    box('jp_balcony',left,right,-.95,-.01,y+.02,y+.17)
                    box('jp_metal',left,right,-.96,-.88,y+.17,min(y+1.04,y+fh*.7))
                    for side in (left,right-.08):box('jp_metal',side,side+.08,-.88,-.02,y+.17,min(y+1.04,y+fh*.7))
                if flags['ac'] and edge==front and kind in ('house','apartment') and (i+j)%2==0 and bay>2.1:
                    box('jp_ac',c+.28,c+.88,-.43,-.02,y+.15,y+.65)
                    box('jp_dark',c+.37,c+.77,-.45,-.43,y+.25,y+.55)
    return out,used

def jp_inside(p,x,z):
    inside=False
    for a,b in zip(p,p[1:]+p[:1]):
        if (a[1]>z)!=(b[1]>z) and x<(b[0]-a[0])*(z-a[1])/(b[1]-a[1])+a[0]:inside=not inside
    return inside

def jp_dist_seg(x,z,a,b):
    dx,dz=b[0]-a[0],b[1]-a[1];d=dx*dx+dz*dz;t=max(0,min(1,((x-a[0])*dx+(z-a[1])*dz)/d)) if d else 0
    return math.hypot(x-a[0]-t*dx,z-a[1]-t*dz)

def jp_samples(p,spacing):
    distance=0.;target=spacing*.5
    for a,b in zip(p,p[1:]):
        L=math.dist(a,b)
        if L<.001:continue
        dx,dz=(b[0]-a[0])/L,(b[1]-a[1])/L
        while target<=distance+L:
            u=target-distance;yield (a[0]+dx*u,a[1]+dz*u,dx,dz);target+=spacing
        distance+=L

def japan_street(elements,b,grid,flags,spacing,seed):
    out={};parts=0;stats={'poles':0,'spans':0,'vending':0,'signals':0,'rails':0,'markings':0};rng=random.Random(seed);footprints=[];roads=[];junctions={};sx,sz=span(b)
    def add(k,geo):
        nonlocal parts
        if parts>=JP_MAX_STREET_PARTS or not geo[0]:return False
        jp_add(out,k,geo);parts+=1;return True
    for e in elements:
        t=e.get('tags',{});g=e.get('geometry') or []
        if len(g)<2 or any('lat' not in v or 'lon' not in v for v in g):continue
        p=clean_points([project(v['lat'],v['lon'],b) for v in g],closed=False)
        if t.get('building') not in (None,'no') and len(p)>=4 and math.dist(p[0],p[-1])<.01:
            p=p[:-1];footprints.append((min(x for x,z in p),max(x for x,z in p),min(z for x,z in p),max(z for x,z in p),p))
        k=t.get('highway')
        if k not in ('residential','living_street','unclassified','service','tertiary','secondary','primary','trunk'):continue
        if t.get('bridge') not in (None,'no') or t.get('tunnel') not in (None,'no'):continue
        if len(p)<2:continue
        width=road_width(t);roads.append((e.get('id',0),p,width,k))
        if k in ('tertiary','secondary','primary','trunk'):
            for v in p:
                key=(round(v[0],1),round(v[1],1));junctions.setdefault(key,set()).add(e.get('id',0))
    # Spatial bins for collision checks: footprints, road corridors, and placed props.
    cell=20.;build_bins={};road_bins={};occupied={}
    def cells(x0,x1,z0,z1):
        for i in range(math.floor(x0/cell),math.floor(x1/cell)+1):
            for j in range(math.floor(z0/cell),math.floor(z1/cell)+1):yield i,j
    for x0,x1,z0,z1,p in footprints:
        for key in cells(x0-2,x1+2,z0-2,z1+2):build_bins.setdefault(key,[]).append((x0,x1,z0,z1,p))
    for _,p,w,k in roads:
        for a,c in zip(p,p[1:]):
            pad=w/2+2
            for key in cells(min(a[0],c[0])-pad,max(a[0],c[0])+pad,min(a[1],c[1])-pad,max(a[1],c[1])+pad):road_bins.setdefault(key,[]).append((a,c,w))
    def free(x,z,r=.55):
        if abs(x)+r>sx/2 or abs(z)+r>sz/2:return False
        key=(math.floor(x/cell),math.floor(z/cell))
        for x0,x1,z0,z1,p in build_bins.get(key,[]):
            if x0-r<=x<=x1+r and z0-r<=z<=z1+r and (jp_inside(p,x,z) or any(jp_dist_seg(x,z,a,c)<r for a,c in zip(p,p[1:]+p[:1]))):return False
        if any(jp_dist_seg(x,z,a,c)<w/2+r for a,c,w in road_bins.get(key,[])):return False
        for k in cells(x-r-3,x+r+3,z-r-3,z+r+3):
            if any(math.hypot(x-a,z-c)<r+rr+.3 for a,c,rr in occupied.get(k,[])):return False
        return True
    def reserve(x,z,r):occupied.setdefault((math.floor(x/cell),math.floor(z/cell)),[]).append((x,z,r))
    def position(v,w,r):
        x,z,dx,dz=v
        for side in (1,-1):
            xx=x-dz*(w/2+r+.2)*side;zz=z+dx*(w/2+r+.2)*side
            if free(xx,zz,r):return xx,zz,side
        return None
    for ident,p,w,k in sorted(roads,key=lambda q:str(q[0])):
        if parts>=JP_MAX_STREET_PARTS:break
        prev=None
        if flags['poles'] and k!='trunk':
            for v in jp_samples(p,spacing):
                if parts+50>JP_MAX_STREET_PARTS:break
                pos=position(v,w,.40)
                if not pos:prev=None;continue
                x,z,side=pos;dx,dz=v[2:];y=height_at(grid,x,z);top=y+8.2
                reserve(x,z,.4);add('jp_pole',jp_tube((x,y,z),(x,top,z),.16,10));add('jp_metal',jp_box((x,z),-dz,dx,-.85,.85,-.07,.07,top-.42,top-.28));stats['poles']+=1
                anchors=[(x-dz*d,top-.18,z+dx*d) for d in (-.65,0,.65)]
                for a in anchors:add('jp_dark',jp_tube((a[0],a[1]-.22,a[2]),a,.065,6))
                if stats['poles']%4==1:add('jp_metal',jp_tube((x+.28,y+5.6,z),(x+.28,y+6.35,z),.23,8))
                if flags['wires'] and prev and prev[1]==side and math.dist((x,z),prev[2])<spacing*1.5:
                    for a,c in zip(prev[0],anchors):
                        points=[tuple((1-t)*a[i]+t*c[i]-(.65*4*t*(1-t) if i==1 else 0) for i in range(3)) for t in [j/8 for j in range(9)]]
                        for aa,cc in zip(points,points[1:]):add('jp_wire',jp_tube(aa,cc,.023,5))
                    stats['spans']+=1
                prev=(anchors,side,(x,z))
        if flags['markings'] and k in ('tertiary','secondary','primary','trunk') and w>=6:
            for x,z,dx,dz in jp_samples(p,8):
                if parts+1>=JP_MAX_STREET_PARTS or abs(x)>sx/2-2 or abs(z)>sz/2-2:continue
                # Ground-following quad; no solid volume, sits above road.
                pp=[(x+dx*u-dz*d,z+dz*u+dx*d) for u,d in ((-1.5,-.065),(1.5,-.065),(1.5,.065),(-1.5,.065))]
                pts,faces=surface_geometry(pp,.095);add('jp_white',([(a,y+height_at(grid,a,c),c) for a,y,c in pts],faces));stats['markings']+=1
        if flags['rails'] and k in ('secondary','primary','trunk'):
            for v in jp_samples(p,18):
                if parts+3>=JP_MAX_STREET_PARTS:break
                x,z,dx,dz=v;pos=position(v,w,.65)
                if not pos:continue
                x,z,side=pos
                if not all(free(x+dx*u,z+dz*u,.25) for u in (-2,2)):continue
                reserve(x,z,.65);y=height_at(grid,x,z)
                add('jp_metal',jp_box((x,z),dx,dz,-2,2,-.075,.075,y+.55,y+.78))
                for u in (-1.8,1.8):
                    xx,zz=x+dx*u,z+dz*u;yy=height_at(grid,xx,zz);add('jp_metal',jp_tube((xx,yy,zz),(xx,yy+.72,zz),.065,6))
                stats['rails']+=1
        if flags['vending'] and k in ('residential','tertiary','unclassified','living_street','service'):
            for v in jp_samples(p,95):
                if parts+5>=JP_MAX_STREET_PARTS or stats['vending']>=100:break
                pos=position(v,w,.8)
                if not pos:continue
                x,z,side=pos;dx,dz=v[2:];y=height_at(grid,x,z);reserve(x,z,.8)
                add(rng.choice(('jp_white','jp_red','jp_blue')),jp_box((x,z),dx,dz,-.52,.52,-.35,.35,y,y+1.83))
                d0,d1=(-.38,-.35) if side==1 else (.35,.38)
                add('jp_glass',jp_box((x,z),dx,dz,-.40,.27,d0,d1,y+.65,y+1.62));add('jp_dark',jp_box((x,z),dx,dz,-.31,.23,d0,d1,y+.20,y+.46));add('jp_metal',jp_box((x,z),dx,dz,.32,.46,d0,d1,y+.80,y+1.20));stats['vending']+=1
    if flags['signals']:
        for (x,z),ids in sorted(junctions.items()):
            if len(ids)<2 or parts+8>=JP_MAX_STREET_PARTS or stats['signals']>=100:continue
            # Approximate junction furniture, not real signal inventory.
            nearby=[(a,c,w) for a,c,w in road_bins.get((math.floor(x/cell),math.floor(z/cell)),[]) if jp_dist_seg(x,z,a,c)<.2]
            if not nearby:continue
            a,c,w=nearby[0];L=math.dist(a,c)
            if L<.01:continue
            dx,dz=(c[0]-a[0])/L,(c[1]-a[1])/L
            pos=None
            for u in (5,-5,8,-8):
                pos=position((x+dx*u,z+dz*u,dx,dz),w,.65)
                if pos:break
            if not pos:continue
            xx,zz,side=pos;y=height_at(grid,xx,zz);reserve(xx,zz,.65)
            add('jp_metal',jp_tube((xx,y,zz),(xx,y+5.1,zz),.11,8));add('jp_dark',jp_box((xx,zz),dx,dz,-.75,.75,-.18,.18,y+4.72,y+5.12))
            for u,k in zip((-.46,0,.46),('jp_green','jp_yellow','jp_red')):
                for sign in (-1,1):
                    nx,nz=-dz,dx;center=(xx+dx*u+nx*sign*.18,y+4.92,zz+dz*u+nz*sign*.18);end=(center[0]+nx*sign*.035,center[1],center[2]+nz*sign*.035);add(k,jp_tube(center,end,.13,10))
            stats['signals']+=1
    return out,stats,parts


def safe_name(s):return re.sub('[^A-Za-z0-9_]','_',str(s))[:80] or 'object'

class CityBuilder(CityImporter):
    def __init__(self):
        super().__init__();self.win='MayaCityBuilderWindow';self.cache_dir=os.path.join(cmds.internalVar(userAppDir=True),'maya_city_builder_cache');self.progress_message='';self.worker_thread=None
    def show(self):
        if cmds.window(self.win,exists=True):cmds.deleteUI(self.win)
        cmds.window(self.win,title='Maya City Builder v'+VERSION,widthHeight=(550,780),sizeable=True)
        cmds.scrollLayout(childResizable=True);cmds.columnLayout(adjustableColumn=True,rowSpacing=7)
        cmds.rowLayout(numberOfColumns=2, adjustableColumn=1, columnWidth2=(430, 90))
        cmds.text(label='MAYA CITY BUILDER  /  Real world to editable 3D',height=34,font='boldLabelFont',align='left')
        cmds.button(label='Help',height=28,command=lambda *_:open_help())
        cmds.setParent('..')
        self.mode=cmds.optionMenu(label='Mode',changeCommand=self.mode_changed)
        for k in ('OSM','PLATEAU','Procedural','Procedural Japan'):cmds.menuItem(label=k)
        cmds.button(label='1. 地図を開く / Open Map',height=34,command=self.open_map)
        cmds.button(label='2. 選択範囲を取得 / Receive Selection',height=32,command=self.get_selection)
        self.fields=[]
        for label,v in zip(('South / 南','West / 西','North / 北','East / 東'),self.bbox):
            cmds.rowLayout(numberOfColumns=2,adjustableColumn=2,columnWidth2=(120,340));cmds.text(label=label,align='left');self.fields.append(cmds.floatField(value=v,precision=7));cmds.setParent('..')
        cmds.separator(height=8,style='in')
        cmds.text(label='Layers / 生成する要素',font='boldLabelFont',align='left');self.options={}
        for k,label in [('building','Buildings / 建物'),('road','Roads / 道路・歩道 (OSM)'),('water','Water / 水面 (OSM)'),('green','Green areas / 緑地 (OSM)'),('ground','Ground / 地面')]:self.options[k]=cmds.checkBox(label=label,value=True)
        self.terrain=cmds.checkBox(label='Japan DEM terrain / 日本の実標高地形 (GSI)',value=False)
        self.step=self.num('DEM grid interval (m)',15,5,100)
        self.shader=cmds.optionMenu(label='Material');cmds.menuItem(label='OpenPBR');cmds.menuItem(label='Standard Surface')
        self.osm_panel=cmds.frameLayout(label='OSM / Procedural settings',collapsable=True);cmds.columnLayout(adjustableColumn=True,rowSpacing=5)
        self.default=self.num('Default building height (m)',9,1,100);self.floor=self.num('Height per floor (m)',3,1,10)
        self.endpoint=cmds.textFieldGrp(label='Overpass URL',text='https://overpass-api.de/api/interpreter',columnWidth2=(100,390),adjustableColumn=2)
        cmds.setParent('..');cmds.setParent('..')
        self.proc_panel=cmds.frameLayout(label='Procedural facade settings',collapsable=True);cmds.columnLayout(adjustableColumn=True,rowSpacing=5)
        self.style=cmds.optionMenu(label='Facade style');[cmds.menuItem(label=x) for x in ('Residential','Office','Industrial')]
        self.density=self.num('Detail building limit',150,1,500,integer=True)
        cmds.text(label='Detail limit: remaining buildings use simple massing.',wordWrap=True,align='left');cmds.setParent('..');cmds.setParent('..')
        self.jp_panel=cmds.frameLayout(label='Procedural Japan / 日本の街並み',collapsable=True);cmds.columnLayout(adjustableColumn=True,rowSpacing=5)
        self.jp_style=cmds.optionMenu(label='District style');[cmds.menuItem(label=x) for x in ('Auto (OSM tags)','Residential district','Urban / station district')]
        self.jp_seed=self.num('Random seed',42,0,999999,integer=True)
        self.jp_spacing=self.num('Utility pole spacing (m)',32,15,80)
        self.jp_flags={}
        for k,label,on in [('roofs','Japanese roofs / 瓦屋根風・軒',True),('facades','Windows, doors, signs / 窓・玄関・看板',True),('balconies','Apartment balconies / バルコニー',True),('ac','Outdoor AC units / 室外機',True),('poles','Utility poles / 電柱',True),('wires','Overhead wires / 電線',True),('markings','Road center markings / 道路標示',True),('rails','Guardrails / ガードレール',False),('vending','Vending machines / 自動販売機',True),('signals','Traffic signals / 信号機',True)]:self.jp_flags[k]=cmds.checkBox(label=label,value=on)
        cmds.text(label='Street props are estimated, not surveyed. Roads layer required. Gable roofs only on near-rectangular houses. Detail limit applies to buildings.',align='left',wordWrap=True)
        cmds.setParent('..');cmds.setParent('..')
        self.plat_panel=cmds.frameLayout(label='PLATEAU / 国土交通省 3D都市モデル',collapsable=True);cmds.columnLayout(adjustableColumn=True,rowSpacing=5)
        self.source=cmds.optionMenu(label='Source');cmds.menuItem(label='Online API');cmds.menuItem(label='Local CityGML / ZIP / folder');cmds.menuItem(label='Online Direct GML (geometry only)')
        self.local=cmds.textFieldButtonGrp(label='Local path',buttonLabel='File',buttonCommand=self.pick_file,columnWidth3=(85,315,65),adjustableColumn=2)
        cmds.button(label='Choose bldg folder / フォルダ選択',command=self.pick_folder)
        self.lod=cmds.optionMenu(label='LOD');cmds.menuItem(label='LOD2 preferred (fallback LOD1)');cmds.menuItem(label='LOD1 only')
        self.tex=cmds.checkBox(label='Import photo textures when available',value=True)
        self.allow_partial=cmds.checkBox(label='Keep PLATEAU buildings if OSM layers fail',value=True)
        cmds.text(label='Large files stream to disk. Online API: photo ZIP / direct GML fallback (no photos).',align='left',wordWrap=True)
        cmds.button(label='PLATEAU official download portal',command=lambda *_:webbrowser.open('https://www.mlit.go.jp/plateau/open-data/'))
        cmds.text(label='Japan only. Large data cached on disk; keep several GB free. Local files use map bounds.',wordWrap=True,align='left');cmds.setParent('..');cmds.setParent('..')
        self.import_button=cmds.button(label='3. BUILD CITY / 街並みを生成',height=44,command=self.start_import)
        self.status_text=cmds.text(label='Ready. Start with a small area (200–500 m).',align='left',wordWrap=True,height=62)
        cmds.button(label='Select last city root',command=self.select_last);self.last_root=None
        cmds.text(label='OSM © contributors / ODbL | Project PLATEAU / MLIT | GSI',align='center',wordWrap=True)
        self.mode_changed('OSM');cmds.showWindow(self.win)
    def num(self,label,v,mn,mx,integer=False):
        cmds.rowLayout(numberOfColumns=2,adjustableColumn=2,columnWidth2=(240,230));cmds.text(label=label,align='left');f=(cmds.intField if integer else cmds.floatField)(value=v,minValue=mn,maxValue=mx);cmds.setParent('..');return f
    def mode_changed(self,mode,*_):
        if hasattr(self,'proc_panel'):
            cmds.frameLayout(self.proc_panel,e=True,manage=mode in ('Procedural','Procedural Japan'));cmds.frameLayout(self.jp_panel,e=True,manage=mode=='Procedural Japan');cmds.frameLayout(self.plat_panel,e=True,manage=mode=='PLATEAU')
            cmds.frameLayout(self.osm_panel,e=True,manage=True);cmds.optionMenu(self.style,e=True,manage=mode=='Procedural')
    def pick_file(self,*_):
        p=cmds.fileDialog2(fileMode=1,caption='Choose CityGML or ZIP',fileFilter='CityGML / ZIP (*.gml *.zip);;All files (*.*)')
        if p:cmds.textFieldButtonGrp(self.local,e=True,text=p[0]);cmds.optionMenu(self.source,e=True,select=2)
    def pick_folder(self,*_):
        p=cmds.fileDialog2(fileMode=3,caption='Choose extracted bldg folder')
        if p:cmds.textFieldButtonGrp(self.local,e=True,text=p[0]);cmds.optionMenu(self.source,e=True,select=2)
    def select_last(self,*_):
        if self.last_root and cmds.objExists(self.last_root):cmds.select(self.last_root,r=True)
    def start_import(self,*_):
        if self.busy:return
        try:
            if cmds.upAxis(q=True,axis=True)!='y':raise ValueError('Y-up Maya scenes only.')
            b=self.read_bbox();mode=cmds.optionMenu(self.mode,q=True,value=True);opts={k:cmds.checkBox(v,q=True,value=True) for k,v in self.options.items()}
            if not any(opts.values()):raise ValueError('Enable at least one layer.')
            settings=dict(mode=mode,opts=opts,default=cmds.floatField(self.default,q=True,value=True),floor=cmds.floatField(self.floor,q=True,value=True),endpoint=cmds.textFieldGrp(self.endpoint,q=True,text=True).strip(),terrain=cmds.checkBox(self.terrain,q=True,value=True),step=cmds.floatField(self.step,q=True,value=True),shader=cmds.optionMenu(self.shader,q=True,value=True),style=cmds.optionMenu(self.style,q=True,value=True),density=cmds.intField(self.density,q=True,value=True),source=cmds.optionMenu(self.source,q=True,select=True),local=cmds.textFieldButtonGrp(self.local,q=True,text=True).strip(),lod=cmds.optionMenu(self.lod,q=True,select=True),textures=cmds.checkBox(self.tex,q=True,value=True),allow_partial=cmds.checkBox(self.allow_partial,q=True,value=True),notices=[])
            if mode=='Procedural Japan':
                settings.update(jp_style=cmds.optionMenu(self.jp_style,q=True,value=True),jp_seed=cmds.intField(self.jp_seed,q=True,value=True),jp_spacing=cmds.floatField(self.jp_spacing,q=True,value=True),jp_flags={k:cmds.checkBox(v,q=True,value=True) for k,v in self.jp_flags.items()})
            if not settings['endpoint'].startswith('https://'):raise ValueError('Overpass endpoint must use HTTPS.')
            if settings['terrain'] and not opts['ground']:raise ValueError('Enable Ground to use DEM terrain.')
            if mode=='PLATEAU' and opts['building'] and settings['source']==2 and not os.path.exists(settings['local']):raise ValueError('Select a local GML, ZIP or folder.')
        except Exception as e:cmds.confirmDialog(title='City Builder',message=str(e),button=['OK']);return
        self.busy=True;self.result=None;self.bbox=b;self.progress_message='Preparing…';cmds.button(self.import_button,e=True,enable=False)
        def progress(s):self.progress_message=s
        def worker():
            try:
                grid=None;osm=None;plat=None;stage='Preparing'
                # Prioritize the requested PLATEAU buildings over supplementary OSM layers.
                if mode=='PLATEAU' and opts['building']:
                    stage='PLATEAU / CityGML'
                    path=plateau_pack(b,self.cache_dir,progress,settings['textures'],settings['source']==3,settings['notices']) if settings['source']!=2 else settings['local']
                    direct=os.path.basename(path).startswith('plateau_direct_') and settings['source']!=2
                    plat=read_plateau(path,b,1 if settings['lod']==2 else 2,self.cache_dir,progress,settings['textures'] and not direct)
                if settings['terrain']:
                    stage='GSI elevation tiles';progress('Downloading GSI elevation tiles...');grid=terrain_grid(b,settings['step'],os.path.join(self.cache_dir,'dem'))
                if any(opts[k] for k in ('road','green','water')) or (opts['building'] and mode!='PLATEAU'):
                    stage='OpenStreetMap / Overpass';progress('Downloading OpenStreetMap data...')
                    try:osm,_=resilient_osm(b,settings['endpoint'],os.path.join(self.cache_dir,'osm'),progress)
                    except Exception as exc:
                        if not (plat and settings['allow_partial']):raise
                        settings['notices'].append('OSM layers skipped: '+str(exc));print('[City Builder] '+settings['notices'][-1])
                        for k in ('road','green','water'):opts[k]=False
                self.result=(True,(osm,plat,grid),b,settings)
            except Exception as exc:
                traceback.print_exc();self.result=(False,stage+': '+str(exc),b,settings)
        self.worker_thread=threading.Thread(target=worker,daemon=True);self.worker_thread.start();self.timer=QtCore.QTimer();self.timer.timeout.connect(self.poll);self.timer.start(300)
    def poll(self):
        if self.result is None:self.status(self.progress_message);return
        self.timer.stop();ok,payload,b,s=self.result;self.result=None
        try:
            if not ok:raise RuntimeError(payload)
            self.status('Generating editable geometry…');cmds.refresh(force=True);summary=self.build_city(payload,b,s);self.status(summary);print('[City Builder] '+summary)
            if s['notices']:
                notice='\n'.join(s['notices']);cmds.warning('City Builder: '+notice);self.status(summary+' | '+notice)
                if cmds.window(self.win,exists=True):cmds.confirmDialog(title='City Builder - Completed with notices',message=notice,button=['OK'])
        except Exception as e:
            self.status('Failed: '+str(e));cmds.warning('City Builder: '+str(e));traceback.print_exc()
            if cmds.window(self.win,exists=True):cmds.confirmDialog(title='City Builder - Import failed',message=str(e)+'\n\nFull details: Maya Script Editor.',button=['OK'])
        finally:
            self.busy=False
            if cmds.window(self.win,exists=True):cmds.button(self.import_button,e=True,enable=True)
    def build_city(self,payload,b,s):
        osm,plat,grid=payload;opts=s['opts'];mode=s['mode'];root=cmds.group(empty=True,name='City_'+safe_name(mode)+'#');root=cmds.ls(root,long=True)[0];nodes=[];groups={};sgs={};counts={k:0 for k in opts};skip=0;estimated=0;detail_count=0;detail_buildings=0;tex_mats={};textured_faces=0;lod2_count=0
        colors={'building':(.58,.61,.65),'road':(.13,.15,.17),'water':(.12,.34,.48),'green':(.22,.42,.22),'ground':(.43,.43,.38),'glass':(.12,.24,.34),'trim':(.24,.22,.19),'roof':(.36,.37,.39)}
        colors.update(JP_COLORS);jp_stats={};jp_parts=0
        def mat(k,texture=None):
            sg,nn=make_material('City_'+k+'_MAT#',(1.,1.,1.) if texture else colors[k],s['shader'],texture,rough=.25 if k in ('glass','jp_glass') else .65,metal=.15 if k in ('glass','jp_glass','jp_metal') else 0.);nodes.extend(nn);return sg
        def jp_mat(k):
            if k not in sgs:sgs[k]=mat(k)
            return sgs[k]
        # A shared origin is saved on each root. Flat modes use zero; DEM uses min sampled elevation.
        altitude=grid[5] if grid else 0.
        try:
            if plat and not grid:altitude=min(v[2] for _,_,faces in plat[0] for p,_,_ in faces for v in p)
            attr(root,'cityBounds',json.dumps(b));attr(root,'cityOriginLatLon',json.dumps([(b[0]+b[2])/2,(b[1]+b[3])/2]));attr(root,'cityAltitudeOriginMetres',altitude);attr(root,'cityCredits',' | '.join(x for x,yes in [(CREDIT,bool(osm)),(PLATEAU_CREDIT,bool(plat)),(GSI_CREDIT,bool(grid))] if yes));attr(root,'cityAxes','X east, Y up, -Z north; metres converted to Maya internal cm');attr(root,'cityImportNotices',' | '.join(s.get('notices',[])))
            for k,on in opts.items():
                if on:
                    g=cmds.group(empty=True,name='City_'+k.title(),parent=root);groups[k]=root+'|'+g.split('|')[-1];sgs[k]=mat(k)
            if mode=='Procedural' and opts['building']:
                for k in ('glass','trim','roof'):sgs[k]=mat(k)
            if opts['ground']:
                x,z=span(b);geo=terrain_geo(grid) if grid else surface_geometry([(-x/2,-z/2),(x/2,-z/2),(x/2,z/2),(-x/2,z/2)],-.03);mesh('Ground',groups['ground'],*geo,sgs['ground']);counts['ground']=1
            combined={k:([],[]) for k in ('road','water','green')}
            elements=(osm or {}).get('elements',[])
            if opts['building'] and mode!='PLATEAU' and sum(e.get('tags',{}).get('building') not in (None,'no') for e in elements)>MAX_BUILDINGS:raise ValueError('More than 2000 buildings. Reduce selection.')
            for e in elements:
                t=e.get('tags',{});geo=e.get('geometry') or [];k=None
                if t.get('building') not in (None,'no'):k='building'
                elif t.get('highway') not in (None,'construction','proposed','abandoned','platform','raceway'):
                    if t.get('tunnel') not in (None,'no') or t.get('bridge') not in (None,'no'):continue
                    k='road'
                elif t.get('natural')=='water' or t.get('waterway')=='riverbank':k='water'
                elif t.get('leisure')=='park' or t.get('natural')=='wood' or t.get('landuse') in ('grass','forest','recreation_ground','meadow'):k='green'
                if not k or not opts.get(k) or (mode=='PLATEAU' and k=='building'):continue
                try:
                    if not geo or any('lat' not in q or 'lon' not in q for q in geo):raise ValueError('Missing geometry')
                    if k!='road' and geo[0]!=geo[-1]:raise ValueError('Open outline')
                    p=clean_points([project(q['lat'],q['lon'],b) for q in geo],closed=k!='road')
                    if k=='building':
                        h,source=building_height(t,s['default'],s['floor']);pts,faces=solid_geometry(p,h);base=min(height_at(grid,x,z) for x,z in p);pts=[(x,y+base,z) for x,y,z in pts];name='Building_'+str(e['id'])
                        kind=jp_kind(t,p,h,s['jp_style']) if mode=='Procedural Japan' else None
                        wall=jp_mat(random.Random(e['id']+s['jp_seed']).choice(('jp_wall_warm','jp_wall_white','jp_wall_gray'))) if kind else sgs[k]
                        tr=mesh(name,groups[k],pts,faces,wall);attr(tr,'osmID',e['id']);attr(tr,'osmHeightSource',source);attr(tr,'osmHeightMetres',h);estimated+=source=='estimated'
                        if mode=='Procedural' and detail_buildings<s['density'] and detail_count<MAX_DETAILS:
                            det,n=detail_geo(p,h,base,s['floor'],s['style'],e['id'],MAX_DETAILS-detail_count);detail_count+=n;detail_buildings+=1
                            for dk,(dp,df) in det.items():
                                if dp:mesh(name+'_'+dk,tr,dp,df,sgs[dk])
                        if kind:
                            attr(tr,'japanBuildingStyle',kind)
                            if detail_buildings<s['density'] and detail_count<MAX_DETAILS:
                                det,n=japan_building(p,h,base,s['floor'],kind,e['id']+s['jp_seed'],s['jp_flags'],MAX_DETAILS-detail_count);detail_count+=n;detail_buildings+=bool(n)
                                for dk,(dp,df) in det.items():
                                    if dp:mesh(name+'_'+dk,tr,dp,df,jp_mat(dk))
                    else:
                        if k=='road':
                            # Insert points along long segments so DEM-following roads do not bridge hills.
                            if grid:
                                sub=[]
                                for a,c in zip(p,p[1:]):
                                    nn=max(1,math.ceil(math.hypot(c[0]-a[0],c[1]-a[1])/s['step']));sub.extend((a[0]+(c[0]-a[0])*i/nn,a[1]+(c[1]-a[1])*i/nn) for i in range(nn))
                                if p:sub.append(p[-1]);p=sub
                            pts,faces=road_geometry(p,.0+road_width(t),.08)
                        else:pts,faces=surface_geometry(p,.02 if k=='green' else .05)
                        pts=[(x,y+height_at(grid,x,z),z) for x,y,z in pts];append_geo(combined[k],(pts,faces))
                    counts[k]+=1
                except Exception as exc:
                    skip+=1
                    if skip<=5:print('[City Builder] skipped OSM way',e.get('id'),str(exc))
            for k,(pts,faces) in combined.items():
                if pts:mesh(k.title()+'_Mesh',groups[k],pts,faces,sgs[k])
            if mode=='Procedural Japan' and opts['road']:
                street,jp_stats,jp_parts=japan_street(elements,b,grid,s['jp_flags'],s['jp_spacing'],s['jp_seed'])
                if street:
                    g=cmds.group(empty=True,name='Japan_Street_Details',parent=root);g=root+'|'+g.split('|')[-1]
                    for k,(pts,faces) in street.items():
                        if pts:mesh('Street_'+k,g,pts,faces,jp_mat(k))
                attr(root,'japanStreetStats',json.dumps(jp_stats));attr(root,'japanSeed',s['jp_seed'])
                if jp_parts>=JP_MAX_STREET_PARTS-50:s['notices'].append('Japan street detail budget reached; some props omitted.')
            if plat:
                records,nskip=plat;skip+=nskip;seen=set()
                for ident,lod,polys in records:
                    if ident in seen and ident!='building':continue
                    seen.add(ident);pts=[];faces=[];face_uv=[];face_sgs={};verts={}
                    for p,tex,uv in polys:
                        f=[]
                        for lat,lon,h in p:
                            x,z=project(lat,lon,b);key=(round(x,5),round(h-altitude,5),round(z,5))
                            if key not in verts:verts[key]=len(pts);pts.append(key)
                            f.append(verts[key])
                        if len(set(f))!=len(f) or len(f)<3:skip+=1;continue
                        # Retain GML polygon winding in the local east/up/south coordinate system.
                        idx=len(faces);faces.append(f);face_uv.append(uv if tex and s['textures'] else None)
                        if tex and uv and s['textures']:
                            if tex not in tex_mats:tex_mats[tex]=mat('building',tex)
                            face_sgs.setdefault(tex_mats[tex],[]).append(idx);textured_faces+=1
                    if faces:
                        tr=textured_mesh('PLATEAU_'+safe_name(ident),groups['building'],pts,faces,sgs['building'],face_uv,face_sgs);attr(tr,'plateauID',ident);attr(tr,'plateauLOD',lod);counts['building']+=1;lod2_count+=lod==2
            cmds.select(root,r=True);self.last_root=root
            return 'Buildings %d (LOD2 %d, estimated %d), roads %d, green %d, water %d; detail buildings %d / parts %d; photo faces %d; skipped %d%s.'%(counts['building'],lod2_count,estimated,counts['road'],counts['green'],counts['water'],detail_buildings,detail_count,textured_faces,skip,('; DEM nodata %d'%grid[6]) if grid else '')+(' Japan: '+', '.join('%s %d'%(k,v) for k,v in jp_stats.items()) if jp_stats else '')
        except Exception:
            if cmds.objExists(root):cmds.delete(root)
            for n in reversed(nodes):
                if cmds.objExists(n):cmds.delete(n)
            raise

# nTools launch entry point; standalone Script Editor execution remains supported.
HELP_URL = 'https://github.com/nmasaaki-web/nTools/blob/main/docs/tools/city_builder.md'


def open_help():
    try:
        if not webbrowser.open(HELP_URL):
            raise RuntimeError('Could not open the browser.')
    except Exception as exc:
        cmds.confirmDialog(title='Maya City Builder - Help',
                           message=str(exc)+'\n'+HELP_URL, button=['OK'])


def show():
    """Open one City Builder window; do not restart an active download."""
    global _maya_city_builder
    old = globals().get('_maya_city_builder')
    if old is not None:
        if cmds.window(old.win, exists=True):
            cmds.showWindow(old.win)
            return old
        if old.busy:
            cmds.warning('City Builder: wait for the current import to finish before reopening.')
            return old
        old.dispose()
    # Clean up a prior standalone OSM importer when this file is pasted again.
    legacy = globals().get('_maya_osm_city_importer')
    if legacy is not None:
        legacy.dispose()
        if cmds.window(legacy.win, exists=True):
            cmds.deleteUI(legacy.win)
    _maya_city_builder = CityBuilder()
    _maya_city_builder.show()
    return _maya_city_builder


if __name__ == '__main__':
    show()
