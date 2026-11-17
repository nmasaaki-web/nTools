# -*- coding: utf-8 -*-
"""nTools Data Collector / データ集合ツール v1.0.

Collect external dependencies into the active Maya project without deleting originals.
Deliberately conservative: backed-up, saved scene; editable nodes only; no
implicit edits inside .ass, referenced scenes, binary caches or unknown plug-ins.
Tested with Python mocks; requires an actual Maya 2027 test before classroom use.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import traceback
import webbrowser

VERSION = '1.0'
WINDOW = 'nToolsDataCollectorWindow'
HELP = 'https://github.com/nmasaaki-web/nTools/blob/main/docs/tools/data_collector.md'
MAX_ITEMS_PER_ENTRY = 10000
MAX_TOTAL_FILES = 20000
MAX_TOTAL_BYTES = 50 * (1024 ** 3)
SPACE_RESERVE = 512 * (1024 ** 2)

# A conservative, explicit list of writable file attributes. Unsupported
# custom plug-in file attributes are never mutated based on a name guess.
KINDS = (
    ('file', 'fileTextureName', 'texture', 'sourceimages'),
    ('aiImage', 'filename', 'texture', 'sourceimages'),
    ('imagePlane', 'imageName', 'image', 'sourceimages'),
    ('aiStandIn', 'dso', 'standin', 'scenes/standins'),
    ('gpuCache', 'cacheFileName', 'gpu', 'cache/gpuCache'),
    ('AlembicNode', 'abc_File', 'alembic', 'cache/alembic'),
    ('mayaUsdProxyShape', 'filePath', 'usd', 'scenes/usd'),
    ('pxrUsdProxyShape', 'filePath', 'usd', 'scenes/usd'),
    ('aiVolume', 'filename', 'volume', 'cache/volumes'),
    ('audio', 'filename', 'audio', 'sound'),
    ('movie', 'fileTextureName', 'movie', 'movies'),
    ('aiPhotometricLight', 'aiFilename', 'ies', 'sourceimages'),
)

# Tokenized texture/sequence names are copied as a group. Never glob arbitrary
# parent directories: only filenames matching explicit tokens are considered.
TOKENS = (
    (re.compile(r'<UDIM>', re.I), r'\d{4}'),
    (re.compile(r'<UVTILE>', re.I), r'u\d+_v\d+'),
    (re.compile(r'<u>_<v>', re.I), r'u\d+_v\d+'),
    (re.compile(r'<frame>', re.I), r'\d+'),
    (re.compile(r'<f>', re.I), r'\d+'),
    (re.compile(r'%0\d+d'), r'\d+'),
    (re.compile(r'\$F\d*'), r'\d+'),
    (re.compile(r'(?<!#)#{2,}(?!#)'), r'\d+'),
)


def _maya():
    import maya.cmds as cmds
    return cmds


def inside(path, root):
    """Realpath-aware containment; prevents lexical ../ and symlink escapes."""
    path, root = Path(path).resolve(), Path(root).resolve()
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def project_root(cmds=None):
    cmds = cmds or _maya()
    raw = cmds.workspace(q=True, rootDirectory=True)
    if not raw:
        raise RuntimeError('File > Set Project でプロジェクトを指定してください。')
    path = Path(raw).expanduser().resolve()
    if not path.is_dir() or not (path / 'workspace.mel').is_file():
        raise RuntimeError('有効なMayaプロジェクトが見つかりません。File > Set Projectで設定してください。')
    return path


def saved_scene(cmds, root):
    name = cmds.file(q=True, sceneName=True) or ''
    if not name or not Path(name).is_file():
        raise RuntimeError('まずFile > Save Sceneでシーンを保存してください。')
    if cmds.file(q=True, modified=True):
        raise RuntimeError('シーンに未保存の変更があります。Save Sceneしてから再実行してください。')
    return Path(name).resolve()


def _source_path(text, root):
    text = os.path.expandvars(os.path.expanduser(str(text).strip())).replace('\\', '/')
    if not text or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*://', text):
        return None
    path = Path(text)
    return (path if path.is_absolute() else root / path).resolve(strict=False)


def _token_pattern(name):
    """Return regex for explicit UDIM/sequence tokens, or None."""
    pieces = []
    cursor = 0
    found = False
    for match in re.finditer(r'<UDIM>|<UVTILE>|<u>_<v>|<frame>|<f>|%0\d+d|\$F\d*|(?<!#)#{2,}(?!#)', name, flags=re.I):
        found = True
        pieces.append(re.escape(name[cursor:match.start()]))
        pieces.append(next(repl for regex, repl in TOKENS if regex.fullmatch(match.group())))
        cursor = match.end()
    if not found:
        return None
    pieces.append(re.escape(name[cursor:]))
    return re.compile('^' + ''.join(pieces) + '$', re.I)


def _expand_files(path, auto_udim=False, auto_sequence=False):
    path = Path(path)
    name = path.name
    rx = _token_pattern(name)
    tokenized = rx is not None
    if not tokenized and (auto_udim or auto_sequence):
        suffix_match = re.search(r'(\d{4,})(?=\.[^.]+$)', name)
        if suffix_match:
            tokenized = True
            rx = re.compile('^' + re.escape(name[:suffix_match.start()]) +
                            r'\d{' + str(len(suffix_match.group(1))) + '}' +
                            re.escape(name[suffix_match.end():]) + '$', re.I)
    if not tokenized:
        return ([path] if path.is_file() else []), name, False
    folder = path.parent
    if not folder.is_dir():
        return [], name, True
    matched = []
    for child in folder.iterdir():
        if child.is_file() and rx.fullmatch(child.name):
            matched.append(child.resolve())
            if len(matched) > MAX_ITEMS_PER_ENTRY:
                raise ValueError('連番ファイルが多すぎます（上限 %d 個）。' % MAX_ITEMS_PER_ENTRY)
    return sorted(matched), name, True


def _is_referenced(cmds, node):
    try:
        return bool(cmds.referenceQuery(node, isNodeReferenced=True))
    except Exception:
        return False


def _attr_entry(cmds, root, node, attribute, category, folder):
    plug = node + '.' + attribute
    try:
        if not cmds.attributeQuery(attribute, node=node, exists=True):
            return None
        raw = cmds.getAttr(plug)
        if not isinstance(raw, str) or not raw.strip():
            return None
        src = _source_path(raw, root)
        if src is None or inside(src, root):
            return None
        auto_udim = False
        auto_sequence = False
        if cmds.nodeType(node) == 'file':
            try: auto_udim = bool(cmds.getAttr(node + '.uvTilingMode') == 3)
            except Exception: pass
            try: auto_sequence = bool(cmds.getAttr(node + '.useFrameExtension'))
            except Exception: pass
        paths, _, pattern = _expand_files(src, auto_udim, auto_sequence)
        readonly = _is_referenced(cmds, node)
        return dict(key='attr:'+plug, label=node, plug=plug, kind=category,
                    folder=folder, old=raw, source=str(src), members=[str(f) for f in paths],
                    pattern=pattern, method='attribute',
                    readonly=readonly, status=('参照シーン内のため変更不可' if readonly else
                           ('コピー可能' if paths else '元ファイルが見つかりません')))
    except Exception as exc:
        print('[Data Collector] skipped', plug, exc)
        return None


def _cache_entry(cmds, root, node):
    try:
        if not cmds.attributeQuery('cachePath', node=node, exists=True): return None
        src_raw = cmds.getAttr(node+'.cachePath') or ''
        cache_name = cmds.getAttr(node+'.cacheName') or ''
        if not src_raw or not cache_name: return None
        path = _source_path(src_raw, root)
        if path is None or inside(path, root): return None
        # nCache typically stores cacheName.xml and cacheNameFrame*.mcx/.mc.
        allowed = {'.xml','.mc','.mcx','.mcc','.mcf'}
        members = []
        if path.is_dir():
            members = sorted(str(f.resolve()) for f in path.iterdir()
                             if f.is_file() and f.suffix.lower() in allowed
                             and (f.name == cache_name + f.suffix or f.name.startswith(cache_name+'Frame')))
        if len(members)>MAX_ITEMS_PER_ENTRY:
            raise ValueError('nCacheのファイル数が上限を超えています。')
        readonly=_is_referenced(cmds,node)
        return dict(key='cache:'+node,label=node,plug=node+'.cachePath',kind='ncache',
                    folder='data/nCache',old=src_raw,source=str(path),members=members,
                    pattern=True,method='cache',readonly=readonly,
                    status=('参照シーン内のため変更不可' if readonly else
                            ('コピー可能' if members else 'キャッシュが見つかりません')))
    except Exception as exc:
        print('[Data Collector] skipped nCache',node,exc)
        return None


def _reference_entry(cmds, root, node):
    if node in ('sharedReferenceNode','_UNKNOWN_REF_NODE_'):
        return None
    try:
        raw = cmds.referenceQuery(node, filename=True, withoutCopyNumber=True)
        src = _source_path(raw,root)
        if src is None or inside(src, root): return None
        files = [str(src)] if src.is_file() else []
        # Editing nested/unloaded references is more invasive than modifying
        # a loaded top-level reference; present but disable these cases.
        try:
            is_nested = bool(cmds.referenceQuery(node, parent=True, referenceNode=True))
        except Exception:
            is_nested = False
        try:
            is_loaded = bool(cmds.referenceQuery(node, isLoaded=True))
        except Exception:
            is_loaded = False
        return dict(key='reference:'+node,label=node,plug=node,kind='reference',
                    folder='scenes/references',old=raw,source=str(src),members=files,
                    pattern=False,method='reference',readonly=is_nested or not is_loaded,
                    status=('入れ子の参照シーン: 手動対応' if is_nested else
                            ('未ロードの参照: 手動対応' if not is_loaded else
                            ('コピー可能（参照を再読込）' if files else '参照ファイルが見つかりません'))))
    except Exception:
        return None


def scan(cmds=None):
    cmds=cmds or _maya()
    root=project_root(cmds)
    items=[]
    for node_type,attr,kind,folder in KINDS:
        try: nodes=cmds.ls(type=node_type) or []
        except Exception: nodes=[]
        for node in nodes:
            entry=_attr_entry(cmds,root,node,attr,kind,folder)
            if entry: items.append(entry)
    for node in cmds.ls(type='cacheFile') or []:
        entry=_cache_entry(cmds,root,node)
        if entry:items.append(entry)
    for node in cmds.ls(type='reference') or []:
        entry=_reference_entry(cmds,root,node)
        if entry:items.append(entry)
    return root, sorted(items,key=lambda x:(x['kind'],x['label'],x['key']))


def _dest_group(root, entry, reserved=None):
    """Stable per-source directory; never overwrite different contents."""
    base=Path(entry['source'])
    # For a file use its parent; for nCache the source *is* the directory.
    parent=base if entry['method']=='cache' else base.parent
    code=hashlib.sha256(str(parent).encode('utf-8')).hexdigest()[:12]
    folder=(root / entry['folder'] / 'nToolsCollected').resolve()
    if not inside(folder,root): raise RuntimeError('コピー先がプロジェクト外です。')
    reserved=reserved or set()
    for i in range(1000):
        target=folder/(code if i==0 else code+'_'+str(i))
        if target in reserved:continue
        if not target.exists():return target
        if not inside(target,root):continue
        conflict=False
        for file in entry['members']:
            dest=target/Path(file).name
            if dest.exists() and (not dest.is_file() or not _same_bytes(Path(file),dest)):
                conflict=True;break
        if not conflict:return target
    raise RuntimeError('コピー先の重複を解決できません。')


def _same_bytes(a,b):
    if a.stat().st_size!=b.stat().st_size:return False
    def sha(p):
        dig=hashlib.sha256()
        with p.open('rb') as fh:
            for buf in iter(lambda:fh.read(2*1024*1024),b''):dig.update(buf)
        return dig.digest()
    return sha(a)==sha(b)


def make_plan(root, selections):
    """Pure planning/preflight. No scene edits or file copies."""
    plan=[];total_bytes=0;total_files=0;reserved=set();groups={};unique=set()
    for entry in selections:
        if entry['readonly'] or not entry['members']:
            raise RuntimeError('対象をコピーできません: '+entry['label'])
        base=Path(entry['source'])
        directory=base if entry['method']=='cache' else base.parent
        group_key=(entry['folder'],str(directory))
        if group_key in groups:
            group=groups[group_key]
        else:
            group=_dest_group(root,entry,reserved)
            reserved.add(group)
            groups[group_key]=group
        members=[]
        for src_text in entry['members']:
            src=Path(src_text)
            if not src.is_file() or inside(src,root):
                raise RuntimeError('外部ファイルが見つからないか既にプロジェクト内です: '+str(src))
            dst=group/src.name
            if not inside(dst,root):raise RuntimeError('コピー先パスが不正です。')
            size=src.stat().st_size
            if dst not in unique:
                unique.add(dst)
                total_bytes+=size;total_files+=1
                if total_files>MAX_TOTAL_FILES or total_bytes>MAX_TOTAL_BYTES:
                    raise RuntimeError('コピー量が安全上限を超えています。分割して実行してください。')
            members.append((src,dst))
        name=Path(entry['source']).name
        new_path=(str(group) if entry['method']=='cache' else str(group/name))
        plan.append(dict(entry=entry, group=group,files=members,new_path=new_path))
    # Check available capacity with a 512MiB safety margin.
    sizes={dst: src.stat().st_size for row in plan for src,dst in row['files']}
    extra=sum(size for dst,size in sizes.items() if not dst.exists())
    if plan and shutil.disk_usage(str(root)).free < extra+SPACE_RESERVE:
        raise RuntimeError('ディスクの空き容量が不足しています。必要容量＋512MiBを確保してください。')
    return plan,total_files,total_bytes


def _set_link(cmds, entry, target):
    if entry['method']=='reference':
        # Top-level LOADED references only. A real loadReference operation
        # updates the filename; 'loadReferenceDepth=none' merely validates it.
        cmds.file(str(target),loadReference=entry['plug'])
        updated=cmds.referenceQuery(entry['plug'],filename=True,withoutCopyNumber=True)
        if Path(updated).resolve()!=Path(target).resolve():
            raise RuntimeError('参照ファイルのリンク更新を確認できません: '+entry['plug'])
    else:
        # Maya project files support project-relative paths for common images,
        # audio and file textures. Preserve absolute paths for plug-in caches,
        # which may use their own resolution rules (documented limitation).
        root=project_root(cmds)
        relative_ok=(entry['kind'] in ('texture','image','audio','movie'))
        link=Path(target).relative_to(root).as_posix() if relative_ok and inside(target,root) else str(target).replace('\\','/')
        cmds.setAttr(entry['plug'],link,type='string')
        actual=cmds.getAttr(entry['plug'])
        if not isinstance(actual,str) or _source_path(actual,root)!=Path(target).resolve():
            raise RuntimeError('ファイルのリンク更新を確認できません: '+entry['plug'])


def run_plan(cmds, root, plan,scene):
    """Copy first, relink second. On failure restore plugs and remove new copies.

    Scene backup is a byte-for-byte copy of the *saved* original. A JSON report
    records every operation, and originals are never deleted or overwritten.
    """
    if cmds.file(q=True, modified=True):
        raise RuntimeError('シーンに未保存の変更があります。保存後に再実行してください。')
    saved_scene(cmds,root)
    timestamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    reports=root/'data'/'nToolsCollected'/'reports'
    if not inside(reports,root):raise RuntimeError('レポートの保存先が不正です。')
    reports.mkdir(parents=True,exist_ok=True)
    backup=reports/(scene.stem+'_'+timestamp+scene.suffix)
    shutil.copy2(scene,backup)
    copied=[];relinked=[]
    progress_open=False
    progress_done=set()
    progress_total=len({dst for row in plan for _,dst in row['files']})
    report={'date':timestamp,'project':str(root),'scene':str(scene),'scene_backup':str(backup),
            'result':'in_progress','items':[],'warnings':[
            '元のファイルは削除しません。元シーンのバックアップは保存時点の内容です。',
            'ASCII .ass内の外部パス・参照シーン内部の依存ファイルは自動修正されません。']}
    report_path=reports/('collect_'+timestamp+'.json')
    def write_report():
        tmp=report_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        tmp.replace(report_path)
    try:
        # Maya's native progress dialog allows students to cancel a large
        # copy; cancellation flows through the same file/plug rollback path.
        if progress_total and hasattr(cmds,'progressWindow'):
            try:
                cmds.progressWindow(title='nTools データ集合',progress=0,
                                    maxValue=progress_total,status='外部データを検証中...',
                                    isInterruptable=True)
                progress_open=True
            except Exception:
                progress_open=False
        # Preflight all sources again before touching the scene.
        for row in plan:
            for src,dst in row['files']:
                if not src.is_file():raise RuntimeError('コピー元が消えました: '+str(src))
                if dst.exists() and not _same_bytes(src,dst):
                    raise RuntimeError('コピー先に別のデータがあります: '+str(dst))
        for row in plan:
            for src,dst in row['files']:
                if progress_open and cmds.progressWindow(q=True,isCancelled=True):
                    raise RuntimeError('利用者がコピーをキャンセルしました。')
                if dst in progress_done:continue
                progress_done.add(dst)
                if dst.is_file():
                    if progress_open:cmds.progressWindow(e=True,progress=len(progress_done))
                    continue
                dst.parent.mkdir(parents=True,exist_ok=True)
                if not inside(dst,root):raise RuntimeError('コピー先がプロジェクト外です。')
                tmp=dst.with_name(dst.name+'.ntools-part')
                if tmp.exists():raise RuntimeError('コピー作業中のファイルが残っています: '+str(tmp))
                try:
                    shutil.copy2(src,tmp)
                    if not _same_bytes(src,tmp):raise RuntimeError('コピー検証に失敗: '+str(src))
                    if dst.exists():raise RuntimeError('コピー中にコピー先が使用されました: '+str(dst))
                    tmp.rename(dst)
                    copied.append(dst)
                    if progress_open:
                        cmds.progressWindow(e=True,progress=len(progress_done),
                                            status=src.name+' をコピーしました')
                finally:
                    if tmp.exists():tmp.unlink()
        for row in plan:
            entry=row['entry']
            # Do not silently relink if the user edited paths while copying.
            if entry['method']!='reference' and cmds.getAttr(entry['plug'])!=entry['old']:
                raise RuntimeError('シーン内のリンクが変更されました: '+entry['plug'])
            relinked.append((entry,entry['old']))
            _set_link(cmds,entry,row['new_path'])
            report['items'].append({'kind':entry['kind'],'plug':entry['plug'],
                                    'source':entry['source'],'copied_files':[str(d) for _,d in row['files']],
                                    'new_path':row['new_path']})
        report['result']='success'
        write_report()
        # Never auto-save: the student can inspect the result and save manually.
        return report_path,backup,len(copied)
    except Exception as exc:
        rollback_errors=[]
        for entry,previous in reversed(relinked):
            try:_set_link(cmds,entry,previous)
            except Exception as err:rollback_errors.append(str(err))
        for path in reversed(copied):
            try:path.unlink()
            except OSError as err:rollback_errors.append(str(err))
        report['result']='failed'
        report['error']=str(exc)
        report['rollback_errors']=rollback_errors
        write_report()
        raise RuntimeError(str(exc)+(('\n復元できなかった項目: '+'; '.join(rollback_errors)) if rollback_errors else '')) from exc
    finally:
        if progress_open:
            try:cmds.progressWindow(endProgress=True)
            except Exception:pass


_UI=None


def _notify(message):
    _maya().confirmDialog(title='nTools データ集合', message=message,button=['OK'])


class CollectorWindow:
    def __init__(self):
        self.cmds=_maya()
        self.root=None
        self.entries=[]
        self.widgets=[]
        self.refresh()

    def refresh(self):
        self.root,self.entries=scan(self.cmds)
        if self.cmds.window(WINDOW,exists=True):self.build()

    def choose(self,value):
        for entry,box in self.widgets:
            if entry['readonly'] or not entry['members']:continue
            self.cmds.checkBox(box,e=True,value=value)

    def help(self,*_):
        webbrowser.open(HELP)

    def collect(self,*_):
        try:
            checked=[item for item,box in self.widgets if
                     self.cmds.checkBox(box,q=True,value=True)]
            if not checked:
                _notify('コピー対象がありません。')
                return
            scene=saved_scene(self.cmds,self.root)
            plan,nfiles,nbytes=make_plan(self.root,checked)
            info=(('選択 %d 項目 / %d ファイル / %.2f GiB\n\n'
                   '元データは削除しません。コピー後、シーン内のリンクを書き換えます。\n'
                   '現在保存されているシーンのバックアップを作ります。\n'
                   'シーンの保存は自動では行いません。\n\n実行しますか？')
                  % (len(plan),nfiles,nbytes/(1024**3)))
            if self.cmds.confirmDialog(title='データ集合: 最終確認',message=info,
                    button=['コピーしてリンク更新','キャンセル'],defaultButton='キャンセル',
                    cancelButton='キャンセル',dismissString='キャンセル')!='コピーしてリンク更新':return
            report,backup,ncopied=run_plan(self.cmds,self.root,plan,scene)
            _notify('完了しました。%dファイルをコピーしました。\n\n'
                    '保存済みシーンのバックアップ:\n%s\n\n実行レポート:\n%s\n\n'
                    '結果を確認してからシーンを保存してください。' % (ncopied,backup,report))
            self.refresh()
        except Exception as exc:
            traceback.print_exc()
            _notify('処理を中止しました:\n'+str(exc)+'\n\n詳細はScript Editorを確認してください。')

    def build(self):
        cmds=self.cmds
        if cmds.window(WINDOW,exists=True):cmds.deleteUI(WINDOW)
        cmds.window(WINDOW,title='データ集合ツール v'+VERSION+' | nTools',widthHeight=(970,660),sizeable=True)
        cmds.columnLayout(adjustableColumn=True,rowSpacing=8)
        cmds.rowLayout(numberOfColumns=2,adjustableColumn=1,columnWidth2=(790,140))
        cmds.text(label='データ集合ツール  |  外部データをプロジェクトへ集合！',font='boldLabelFont',align='left')
        cmds.button(label='Help / 使い方',command=self.help)
        cmds.setParent('..')
        cmds.text(label='Project: '+str(self.root),align='left')
        cmds.text(label='チェックの付いたファイルをコピーして、現在のシーンのリンクを更新します。元データは変更しません。',align='left')
        cmds.rowLayout(numberOfColumns=3,columnWidth3=(180,180,180))
        cmds.button(label='一覧を再スキャン',command=lambda *_:self.refresh())
        cmds.button(label='全てチェック',command=lambda *_:self.choose(True))
        cmds.button(label='全て解除',command=lambda *_:self.choose(False))
        cmds.setParent('..')
        cmds.separator(style='in',height=8)
        cmds.rowLayout(numberOfColumns=4,columnWidth4=(32,135,320,430))
        for v in ('選択','種類','ノード','状態 / 元ファイル'):
            cmds.text(label=v,align='left',font='boldLabelFont')
        cmds.setParent('..')
        cmds.scrollLayout(height=420,childResizable=True)
        cmds.columnLayout(adjustableColumn=True,rowSpacing=4)
        self.widgets=[]
        for entry in self.entries:
            enabled=bool(entry['members'] and not entry['readonly'])
            cmds.rowLayout(numberOfColumns=4,columnWidth4=(32,135,320,430))
            box=cmds.checkBox(label='',value=enabled,enable=enabled)
            cmds.text(label=entry['kind'],align='left')
            cmds.text(label=entry['label'],align='left',annotation=entry['plug'])
            text=entry['status']+' | '+entry['source']
            cmds.text(label=text if len(text)<100 else text[:97]+'...',align='left',annotation=text)
            cmds.setParent('..')
            self.widgets.append((entry,box))
        if not self.entries:
            cmds.text(label='プロジェクト外の依存ファイルは見つかりませんでした（対応ノードのみ）。',align='center',height=75)
        cmds.setParent('..')
        cmds.setParent('..')
        cmds.separator(style='in',height=8)
        cmds.text(label='対応: テクスチャ / UDIM / 連番 / リファレンス / .ass / Alembic / GPU Cache / nCache / USD / 音声など',align='left')
        cmds.text(label='注意: 参照内部のリンク・.ass内部の外部パス・不明なプラグイン形式は自動修正しません。',align='left')
        cmds.button(label='選択したデータを集合！  コピー ＋ リンク更新',height=45,command=self.collect)
        cmds.showWindow(WINDOW)


def show():
    global _UI
    cmds=_maya()
    try:
        if cmds.window(WINDOW,exists=True):
            cmds.showWindow(WINDOW)
            return
        _UI=CollectorWindow()
        _UI.build()
    except Exception as exc:
        traceback.print_exc()
        _notify(str(exc))


if __name__=='__main__':
    show()
