# -*- coding: utf-8 -*-
"""nTools installer and shelf manager. Run inside Maya, or drag onto Maya.
The repository copy and installed installer.py are identical.
"""
import hashlib
import importlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
import urllib.request
import uuid
import zipfile

REPO = 'https://github.com/nmasaaki-web/nTools'
ARCHIVE = 'https://codeload.github.com/nmasaaki-web/nTools/zip/refs/heads/main'
SHELF = 'nTools'
PACKAGE = 'ntools'
MAX_BYTES = 32 * 1024 * 1024
_RESTART_REQUIRED = False


def _maya():
    import maya.cmds as cmds
    import maya.mel as mel
    return cmds, mel


def _target():
    cmds, _ = _maya()
    return Path(cmds.internalVar(userScriptDir=True)).resolve() / PACKAGE


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d+\.\d+', value):
        raise ValueError('Invalid release version: ' + str(value))
    return tuple(map(int, value.split('.')))


def _manifest(data):
    m = json.loads(data.decode('utf-8'))
    if m.get('schema') != 1 or m.get('package') != 'nTools':
        raise ValueError('Unknown nTools package format.')
    _version(m['version'])
    files = m['files']
    if not isinstance(files, dict) or len(files) > 200:
        raise ValueError('Invalid file list.')
    destinations = set()
    for src, digest in files.items():
        if not isinstance(src, str) or not re.fullmatch(r'[A-Za-z0-9_./-]+', src):
            raise ValueError('Invalid path: ' + str(src))
        p = PurePosixPath(src)
        if p.is_absolute() or '..' in p.parts or p.as_posix() != src:
            raise ValueError('Unsafe path: ' + src)
        dest = _relative(src)
        if dest.casefold() in destinations:
            raise ValueError('Duplicate destination: ' + dest)
        destinations.add(dest.casefold())
        if not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest):
            raise ValueError('Invalid checksum: ' + src)
    if not {'install.py','scripts/ntools/__init__.py','scripts/ntools/tools/__init__.py','scripts/ntools/icons/update.png'} <= set(files):
        raise ValueError('Required files missing.')
    tools = m['tools']
    if not isinstance(tools, list) or not tools or len(tools) > 50:
        raise ValueError('Invalid tool list.')
    ids = set()
    for tool in tools:
        ident = tool['id']
        if not re.fullmatch(r'[a-z][a-z0-9_]*', ident) or ident in ids:
            raise ValueError('Invalid tool ID.')
        ids.add(ident)
        if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', tool['entry']):
            raise ValueError('Invalid entry point.')
        if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', tool['module']):
            raise ValueError('Invalid module.')
        if not re.fullmatch(r'[A-Za-z0-9_-]+\.png', tool['icon']):
            raise ValueError('Invalid icon.')
        if 'scripts/ntools/tools/'+tool['module']+'.py' not in files or 'scripts/ntools/icons/'+tool['icon'] not in files:
            raise ValueError('Tool file missing: '+ident)
        for k in ('label','version','short','description'):
            if not isinstance(tool[k], str): raise ValueError('Invalid tool metadata.')
    return m


def _relative(src):
    if src == 'install.py':
        return 'installer.py'
    prefix = 'scripts/ntools/'
    if not src.startswith(prefix):
        raise ValueError('Unexpected package file: ' + src)
    rest = src[len(prefix):]
    if rest not in ('__init__.py',) and not re.fullmatch(r'(?:tools/[A-Za-z0-9_]+\.py|icons/[A-Za-z0-9_-]+\.png)', rest):
        raise ValueError('Unexpected package file: ' + src)
    return rest


def _download():
    # macOS Maya has previously had embedded OpenSSL problems. Use system
    # curl with normal TLS verification, never -k or an unverified context.
    if sys.platform == 'darwin' and Path('/usr/bin/curl').is_file():
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)/'ntools.zip'
            env = os.environ.copy()
            for key in ('DYLD_LIBRARY_PATH','DYLD_FALLBACK_LIBRARY_PATH','DYLD_INSERT_LIBRARIES','SSL_CERT_FILE','SSL_CERT_DIR'):
                env.pop(key,None)
            subprocess.run(['/usr/bin/curl','-q','--fail','--silent','--show-error','--location','--proto','=https','--proto-redir','=https','--connect-timeout','10','--max-time','60','--max-filesize',str(MAX_BYTES),'--output',str(dest),ARCHIVE],env=env,check=True,timeout=70)
            if dest.stat().st_size > MAX_BYTES: raise ValueError('Download too large.')
            return dest.read_bytes()
    req = urllib.request.Request(ARCHIVE, headers={'User-Agent':'nTools-Maya-Installer/1'})
    with urllib.request.urlopen(req,timeout=30) as response:
        if not response.geturl().startswith('https://'): raise ValueError('HTTPS required.')
        data = response.read(MAX_BYTES+1)
    if len(data)>MAX_BYTES: raise ValueError('Download too large.')
    return data


def _verified(read):
    raw = read('version.json')
    m = _manifest(raw)
    payload = {}
    total = 0
    for src, digest in m['files'].items():
        data = read(src)
        total += len(data)
        if total > MAX_BYTES: raise ValueError('Package too large.')
        if hashlib.sha256(data).hexdigest()!=digest:
            raise ValueError('SHA-256 mismatch: '+src)
        dest = _relative(src)
        if dest.endswith('.py'):
            compile(data,src,'exec')
        payload[dest] = data
    payload['version.json'] = raw
    return m,payload


def _local(root):
    return _verified(lambda name: (root/name).read_bytes())


def _online():
    with zipfile.ZipFile(io.BytesIO(_download())) as z:
        names = z.namelist()
        roots = [n for n in names if n.count('/')==1 and n.endswith('/version.json')]
        if len(roots)!=1: raise ValueError('Repository version.json not found.')
        prefix = roots[0].split('/')[0]+'/'
        def read(name):
            full = prefix+name
            if names.count(full)!=1: raise ValueError('Missing or duplicate archive file: '+name)
            info=z.getinfo(full)
            if info.file_size>MAX_BYTES: raise ValueError('Archive entry too large.')
            return z.read(info)
        return _verified(read)


def _installed():
    path = _target()/'version.json'
    if not path.is_file(): return None
    return _manifest(path.read_bytes())


def _shelf_parent():
    _, mel = _maya()
    return mel.eval('global string $gShelfTopLevel; $ntoolsTop = $gShelfTopLevel;')


def _shelf_path():
    cmds,_ = _maya()
    return Path(cmds.internalVar(userShelfDir=True)) / ('shelf_'+SHELF+'.mel')


def _command(action):
    # Resolve per-user paths when clicked, not the teacher's machine path.
    return ('import sys, maya.cmds as cmds\n'
            'p = cmds.internalVar(userScriptDir=True)\n'
            'if p not in sys.path: sys.path.insert(0,p)\n'
            'from ntools import installer as nt\n'+action)


def register_shelf(manifest=None):
    cmds,mel = _maya()
    m = manifest or _installed()
    if m is None: raise RuntimeError('nTools is not installed.')
    top = _shelf_parent()
    shelf = top+'|'+SHELF
    if not cmds.shelfLayout(shelf,exists=True):
        mel.eval('addNewShelfTab "nTools";')
    if not cmds.shelfLayout(shelf,exists=True):
        raise RuntimeError('Cannot create nTools shelf.')
    for child in cmds.shelfLayout(shelf,q=True,childArray=True) or []:
        full = child if '|' in child else shelf+'|'+child
        cmds.deleteUI(full)
    for t in m['tools']:
        cmds.shelfButton(parent=shelf,label=t['label'],annotation=t['label']+' v'+t['version']+' | '+t['description'],image1=(_target()/'icons'/t['icon']).as_posix(),imageOverlayLabel=t['short'],sourceType='python',command=_command('nt.launch('+repr(t['id'])+')'))
    cmds.shelfButton(parent=shelf,label='Update nTools',annotation='nTools '+m['version']+' | Check GitHub for updates',image1=(_target()/'icons'/'update.png').as_posix(),imageOverlayLabel='Update',sourceType='python',command=_command('nt.update()'))
    path=_shelf_path(); path.parent.mkdir(parents=True,exist_ok=True)
    if not cmds.saveShelf(shelf,path.as_posix()): raise RuntimeError('Could not save nTools shelf.')
    cmds.shelfTabLayout(top,e=True,selectTab=SHELF)
    return shelf


def launch(ident):
    cmds,_ = _maya()
    if _RESTART_REQUIRED or getattr(sys,'_ntools_restart_required',False):
        cmds.confirmDialog(title='nTools',message='更新を反映するため、Mayaを再起動してください。',button=['OK']);return
    try:
        m=_installed()
        t=next(x for x in m['tools'] if x['id']==ident)
        name='ntools.tools.'+t['module']
        was_loaded=name in sys.modules
        module=importlib.import_module(name)
        # QQR v2.4 opens its UI when imported. Do not open twice on first click.
        if not t.get('opens_on_import',False) or was_loaded:
            getattr(module,t['entry'])()
    except Exception as exc:
        traceback.print_exc()
        cmds.confirmDialog(title='nTools - Error',message=str(exc),button=['OK'])


def _apply(m,payload):
    dest=_target(); dest.parent.mkdir(parents=True,exist_ok=True)
    old=_installed()
    if dest.exists() and old is None:
        raise RuntimeError('Existing unrecognized ntools folder. No files changed: '+str(dest))
    # Stage complete package before any existing installation is changed.
    stage=Path(tempfile.mkdtemp(prefix='.ntools-stage-',dir=str(dest.parent)))
    backup=dest.parent/('.ntools-backup-'+uuid.uuid4().hex)
    shelf_file=_shelf_path()
    saved_shelf=shelf_file.read_bytes() if shelf_file.is_file() else None
    moved=False; installed=False
    try:
        for relative,data in payload.items():
            p=stage/relative; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(data)
        if dest.exists(): dest.rename(backup); moved=True
        stage.rename(dest);installed=True
        importlib.invalidate_caches()
        register_shelf(m)
    except Exception:
        if installed: shutil.rmtree(dest)
        if moved: backup.rename(dest)
        # Restore saved shelf on disk, and recreate previous managed UI when possible.
        try:
            if old: register_shelf(old)
            else:
                cmds,_=_maya(); shelf=_shelf_parent()+'|'+SHELF
                if cmds.shelfLayout(shelf,exists=True): cmds.deleteUI(shelf)
        except Exception: traceback.print_exc()
        # Restore the disk shelf even if rebuilding the live UI failed.
        try:
            if saved_shelf is not None: shelf_file.write_bytes(saved_shelf)
            elif shelf_file.exists(): shelf_file.unlink()
        except Exception: traceback.print_exc()
        raise
    finally:
        if stage.exists(): shutil.rmtree(stage,ignore_errors=True)
    # Keep one successful previous installation, outside the importable package.
    if moved:
        for p in dest.parent.glob('.ntools-backup-*'):
            if p!=backup and p.is_dir(): shutil.rmtree(p,ignore_errors=True)
    if old is not None:
        sys._ntools_restart_required=True
    return old is not None


def _confirm(message, yes='Install'):
    cmds,_=_maya()
    return cmds.confirmDialog(title='nTools',message=message,button=[yes,'Cancel'],defaultButton=yes,cancelButton='Cancel',dismissString='Cancel')==yes


def _notify(message):
    cmds,_=_maya(); cmds.confirmDialog(title='nTools',message=message,button=['OK'])


def install(source=None):
    """Install from extracted repository; otherwise download from GitHub."""
    try:
        # Explicit source path provided by drag/drop or Python Script Editor.
        # Pasting the whole file into Script Editor also works (online fallback).
        path=Path(source).resolve() if source else None
        if path and path.is_file(): path=path.parent
        if path is None:
            file=globals().get('__file__')
            path=Path(file).resolve().parent if file else None
        local=path is not None and (path/'version.json').is_file() and (path/'scripts'/'ntools').is_dir()
        m,payload=_local(path) if local else _online()
        old=_installed()
        cmds,_=_maya(); shelf=_shelf_parent()+'|'+SHELF
        if old is None and cmds.shelfLayout(shelf,exists=True):
            raise RuntimeError('Existing nTools shelf without an installation. Rename that shelf first; no changes made.')
        if old and _version(m['version'])<_version(old['version']):
            raise RuntimeError('Older package. Use the latest version instead.')
        msg='nTools '+m['version']+' をインストールします。\nツールと更新ボタンを登録します。\n既存の nTools シェルフは置き換わります。\n他のシェルフ・制作データは変更しません。'
        if not _confirm(msg):return
        restart=_apply(m,payload)
        _notify('インストール完了！ nTools '+m['version']+'\n'+('Mayaを再起動してください。' if restart else 'nTools シェルフを選んでください。'))
    except Exception as exc:
        traceback.print_exc();_notify('インストール失敗：\n'+str(exc)+'\n詳細は Script Editor を確認してください。')


def update():
    """Check public GitHub main, confirm, then replace only nTools."""
    try:
        old=_installed()
        if old is None: raise RuntimeError('nTools is not installed. Run install.py again.')
        m,payload=_online()
        if _version(m['version'])<=_version(old['version']):
            _notify('現在の nTools '+old['version']+' は最新版です。\nGitHub: '+m['version']);return
        if not _confirm('nTools '+old['version']+' → '+m['version']+'\n更新しますか？\nシーンを保存し、ツールの作業を終えてから更新してください。\n更新後は Maya の再起動が必要です。','Update'):return
        _apply(m,payload)
        _notify('更新完了：nTools '+m['version']+'\nMayaを再起動してください。')
    except Exception as exc:
        traceback.print_exc();_notify('更新失敗：\n'+str(exc)+'\n詳細は Script Editor を確認してください。')


def onMayaDroppedPythonFile(*args):
    install(globals().get('__file__'))


if __name__=='__main__':
    install(globals().get('__file__'))
