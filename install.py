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
import webbrowser
import zipfile

REPO = 'https://github.com/nmasaaki-web/nTools'
ARCHIVE = 'https://codeload.github.com/nmasaaki-web/nTools/zip/refs/heads/main'
SHELF = 'nTools'
PACKAGE = 'ntools'
MAX_BYTES = 32 * 1024 * 1024
_RESTART_REQUIRED = False
INSTALLER_VERSION = '1.0.7'
_SEPARATOR = '<ntools:shelf-separator>'
_SHELF_SAVE_PENDING = False
_UPDATE_BUSY = False


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


def _check_shelf_names():
    """Reject malformed nTools tabs/files before shelf operations.

    Older releases passed a .mel suffix to saveShelf, which adds it itself.
    Never auto-delete malformed legacy prefs: Maya must be closed for recovery.
    """
    cmds, _ = _maya()
    top = _shelf_parent()
    tabs = cmds.shelfTabLayout(top, q=True, childArray=True) or []
    names = [t.split('|')[-1] for t in tabs]
    bad = [n for n in names if n.casefold().startswith('ntools.')]
    folder = _shelf_path().parent
    if folder.is_dir():
        bad += [f.name for f in folder.iterdir()
                if f.name.casefold().startswith('shelf_ntools.mel.mel')]
    # Maya tracks shelf names and file basenames in numbered optionVars.
    # Read only; do not rewrite global shelf preferences.
    if cmds.optionVar(exists='numShelves'):
        count = int(cmds.optionVar(q='numShelves'))
        if count < 0 or count > 1000:
            raise RuntimeError('Unexpected Maya shelf preference count.')
        for i in range(1, count+1):
            for key in ('shelfName', 'shelfFile'):
                k = key+str(i)
                if cmds.optionVar(exists=k):
                    v = str(cmds.optionVar(q=k)).replace('\\','/').split('/')[-1]
                    if v.casefold().startswith(('ntools.', 'shelf_ntools.mel.mel')):
                        bad.append(k+'='+v)
    if bad or names.count(SHELF)>1:
        raise RuntimeError('旧版の不正なnToolsシェルフが残っています。Mayaを終了し、READMEの復旧手順を実行してください。\n'+', '.join(bad))


def _save_ntools_shelf():
    """Maya saveShelf accepts a basename, not a filename with .mel."""
    cmds, _ = _maya()
    _check_shelf_names()
    path = _shelf_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Maya appends .mel. Passing path itself creates shelf_nTools.mel.mel.
    if not cmds.saveShelf(SHELF, path.with_suffix('').as_posix()):
        raise RuntimeError('Could not save nTools shelf.')
    if not path.is_file():
        raise RuntimeError('Expected shelf_nTools.mel was not created.')
    _check_shelf_names()


def _command(action):
    # Resolve per-user paths when clicked, not the teacher's machine path.
    return ('import sys, maya.cmds as cmds\n'
            'p = cmds.internalVar(userScriptDir=True)\n'
            'if p not in sys.path: sys.path.insert(0,p)\n'
            'from ntools import installer as nt\n'+action)


def _ui_snapshot():
    """Read-only guard: never modify menu sets or the workspace."""
    cmds, _ = _maya()
    sets = tuple(sorted(cmds.menuSet(q=True, allMenuSets=True) or []))
    current = cmds.menuSet(q=True, currentMenuSet=True)
    if not sets or not current or current not in sets:
        raise RuntimeError('Mayaのメニューセットが正常ではありません。UIを復旧してから実行してください。')
    top = _shelf_parent()
    if not top or not cmds.shelfTabLayout(top, exists=True):
        raise RuntimeError('Mayaのシェルフが利用できません。UIを復旧してください。')
    _check_shelf_names()
    return (sets, current, tuple(cmds.menuSet(q=True, menuArray=True) or []))


def _shelf():
    return _shelf_parent()+'|'+SHELF


def _backup_ui():
    # Read/copy only. Never save/reset global prefs, change Maya.env or userSetup.
    cmds, _ = _maya()
    folder = _target().parent / '.ntools-ui-backups' / uuid.uuid4().hex
    folder.mkdir(parents=True)
    prefs = Path(cmds.internalVar(userPrefDir=True))
    for name in ('userPrefs.mel', 'menuSetPrefs.mel', 'windowPrefs.mel', 'userHotkeys.mel'):
        src = prefs/name
        if src.is_file(): shutil.copy2(src, folder/name)
    path = _shelf_path()
    if path.is_file(): shutil.copy2(path, folder/path.name)
    print('nTools UI backup:', folder)
    return folder


def _shelf_item(path):
    """Read a shelf button or a native vertical shelf separator.

    Maya may generate a different separator UI name on restart; recognize
    the native control by type/style/orientation, not by name or docTag.
    """
    cmds, _ = _maya()
    if cmds.shelfButton(path, exists=True):
        return (cmds.shelfButton(path, q=True, command=True) or '').strip()
    if (cmds.separator(path, exists=True)
            and cmds.separator(path, q=True, style=True) == 'shelf'
            and not cmds.separator(path, q=True, horizontal=True)):
        return _SEPARATOR
    raise RuntimeError('管理対象外のシェルフ項目があります。変更しません。')


def _new_separator(shelf):
    cmds, _ = _maya()
    return cmds.separator(parent=shelf, style='shelf', horizontal=False,
                          width=12, height=34)


def _owned_shelf():
    # Read-only ownership check; also accept the native separator after restart.
    cmds, _ = _maya(); shelf = _shelf()
    if not cmds.shelfLayout(shelf, exists=True): return False
    try:
        items = [_shelf_item(p) for p in _button_paths(shelf)]
    except (RuntimeError, TypeError, ValueError):
        return False
    if not items or items.count(_SEPARATOR)>1: return False
    for item in items:
        if item == _SEPARATOR: continue
        if 'from ntools import installer as nt' not in item: return False
        if not re.search(r"nt\.(?:launch\(|update\(|manage\(|uninstall_from_shelf\(|help\()", item): return False
    return True


def _layout_signature(m):
    return ([(t['id'],t['label'],t['short'],t['icon'],t['description']) for t in m['tools']],
            'scripts/ntools/icons/uninstall.png' in m['files'],
            'scripts/ntools/icons/help.png' in m['files'])


def help():
    """Open the GitHub student guide without modifying Maya or the shelf."""
    try:
        if not webbrowser.open(REPO):
            raise RuntimeError('ブラウザを開けませんでした。')
    except Exception as exc:
        _notify(str(exc)+'\n'+REPO)


def _management_button(kind):
    if kind == 'help':
        return dict(label='Help nTools', annotation='Open nTools Japanese user manuals',
                    image1=(_target()/'icons'/'help.png').as_posix(),
                    imageOverlayLabel='Help', sourceType='python',
                    command=_command('nt.help()'))
    if kind == 'uninstall':
        return dict(label='Uninstall nTools', annotation='Uninstall nTools (confirmation required)',
                    image1=(_target()/'icons'/'uninstall.png').as_posix(),
                    imageOverlayLabel='Uninstall', sourceType='python',
                    command=_command('nt.uninstall_from_shelf()'))
    return dict(label='Update nTools', annotation='Check GitHub for updates',
                image1=(_target()/'icons'/'update.png').as_posix(),
                imageOverlayLabel='Update', sourceType='python',
                command=_command('nt.update()'))


def _button_paths(shelf):
    cmds, _ = _maya()
    return [child if child.startswith(shelf+'|') else shelf+'|'+child.split('|')[-1]
            for child in (cmds.shelfLayout(shelf,q=True,childArray=True) or [])]


def add_uninstall_button():
    """Compatibility entry point for the older management menu."""
    add_help_button()


def _sync_management_buttons(m):
    """Add a native separator and missing management buttons, without rebuild.

    A known partial tail is retryable. Unknown/custom controls, duplicate
    separators and changes to the four tool buttons are never auto-edited.
    """
    global _SHELF_SAVE_PENDING
    cmds, _ = _maya()
    shelf = _shelf()
    before = _ui_snapshot()
    if not cmds.shelfLayout(shelf, exists=True):
        return 'nToolsシェルフがありません。Repair Shelfで登録してください。'
    if not _owned_shelf():
        raise RuntimeError('管理対象外の項目があります。シェルフは変更しません。')
    expected = [_command('nt.launch('+repr(t['id'])+')').strip() for t in m['tools']]
    kinds = ('help','uninstall','update')
    command_for = {k: _management_button(k)['command'].strip() for k in kinds}
    desired = [k for k in kinds if 'scripts/ntools/icons/'+k+'.png' in m['files']]
    if 'update' not in desired: raise RuntimeError('Update icon is missing from manifest.')
    paths = _button_paths(shelf)
    items = [_shelf_item(p) for p in paths]
    n = len(expected)
    tail = items[n:]
    target_tail = [_SEPARATOR] + [command_for[k] for k in desired]
    if items[:n] != expected or len(tail) != len(set(tail)) or not set(tail) <= set(target_tail) or command_for['update'] not in tail:
        raise RuntimeError('既知のnTools構成と一致しません。シェルフは変更しません。')
    goal = expected + target_tail
    if items == goal and not _SHELF_SAVE_PENDING:
        return 'シェルフ：最新のボタン構成です。'
    for kind in desired:
        if not (_target()/'icons'/(kind+'.png')).is_file():
            raise RuntimeError('Missing icon: '+kind)
    backup = _backup_ui()
    parent = cmds.setParent(q=True)
    added = []
    try:
        _SHELF_SAVE_PENDING = True
        if _SEPARATOR not in tail:
            _new_separator(shelf)
            added.append('Separator')
        for kind in desired:
            if command_for[kind] not in tail:
                cmds.shelfButton(parent=shelf, **_management_button(kind))
                added.append(kind.title())
        # Move only the separator and management controls, never tool buttons.
        for index, wanted in enumerate(target_tail, n+1):
            current = _button_paths(shelf)
            actual = [_shelf_item(p) for p in current]
            if actual[index-1] != wanted:
                p = current[actual.index(wanted)]
                cmds.shelfLayout(shelf,e=True,position=(p.split('|')[-1],index))
        actual = [_shelf_item(p) for p in _button_paths(shelf)]
        if actual != goal: raise RuntimeError('シェルフの項目順序が一致しません。')
        if _ui_snapshot()!=before: raise RuntimeError('Mayaのメニュー状態が変化しました。')
        _save_ntools_shelf()
        if _ui_snapshot()!=before: raise RuntimeError('Mayaのメニュー状態が変化しました。')
        _SHELF_SAVE_PENDING = False
    except Exception as exc:
        # Do not delete/rebuild a live shelf; retry known partial tails only.
        raise RuntimeError(str(exc)+'\nシェルフ操作を中止しました。バックアップ：'+str(backup)+'\nUIが正常ならUpdateで再試行できます。') from exc
    finally:
        if parent:
            try: cmds.setParent(parent)
            except RuntimeError: pass
    return 'シェルフ：'+(' / '.join(added)+' を追加しました。' if added else '項目の順序・保存を確認しました。')


def add_help_button():
    """Optional manual recovery; Update now performs this migration itself."""
    try:
        if getattr(sys,'_ntools_restart_required',False):
            _notify('先にMayaを再起動してください。'); return
        m = _installed()
        if m is None or 'scripts/ntools/icons/help.png' not in m['files']:
            raise RuntimeError('先にnTools v1.0.7以降を導入してください。')
        if not _confirm('nToolsの管理ボタンとSeparatorを確認・追加します。既存のタブは削除しません。','Add'): return
        _notify(_sync_management_buttons(m))
    except Exception as exc:
        traceback.print_exc(); _notify('ボタン追加中止：\n'+str(exc))


def register_shelf(manifest=None):
    """Create ONLY a missing shelf. Never delete/rebuild an existing tab."""
    cmds,mel = _maya(); m = manifest or _installed()
    if m is None: raise RuntimeError('nTools is not installed.')
    before = _ui_snapshot(); top = _shelf_parent(); shelf = top+'|'+SHELF
    if cmds.shelfLayout(shelf,exists=True):
        raise RuntimeError('nToolsシェルフが既にあります。既存のタブは変更しません。')
    if _shelf_path().exists():
        raise RuntimeError('既存の shelf_nTools.mel があります。Mayaを再起動して確認してください。')
    _backup_ui()
    parent = cmds.setParent(q=True)
    try:
        mel.eval('addNewShelfTab "nTools";')
        if not cmds.shelfLayout(shelf,exists=True): raise RuntimeError('Cannot create nTools shelf.')
        for t in m['tools']:
            cmds.shelfButton(parent=shelf,label=t['label'],annotation=t['label']+' | '+t['description'],image1=(_target()/'icons'/t['icon']).as_posix(),imageOverlayLabel=t['short'],sourceType='python',command=_command('nt.launch('+repr(t['id'])+')'))
        _new_separator(shelf)
        if (_target()/'icons'/'help.png').is_file():
            cmds.shelfButton(parent=shelf,**_management_button('help'))
        if (_target()/'icons'/'uninstall.png').is_file():
            cmds.shelfButton(parent=shelf,**_management_button('uninstall'))
        cmds.shelfButton(parent=shelf,**_management_button('update'))
        if _ui_snapshot()!=before: raise RuntimeError('Mayaのメニュー状態が変化しました。作業を中止しました。')
        # Save only this shelf, not all Maya preferences.
        _save_ntools_shelf()
        if _ui_snapshot()!=before: raise RuntimeError('Mayaのメニュー状態が変化しました。バックアップを確認してください。')
    finally:
        # Do not try to delete a partially created shelf in an error handler.
        # The user can remove it using Maya's own shelf editor after inspection.
        if parent:
            try: cmds.setParent(parent)
            except RuntimeError: pass
    return shelf


def repair_shelf():
    """Rebuild only a missing tab; never automatically remove a live tab."""
    try:
        _ui_snapshot(); m=_installed()
        if m is None: raise RuntimeError('先に install.py で本体を導入してください。')
        cmds,_=_maya()
        if cmds.shelfLayout(_shelf(),exists=True):
            _notify('既存の nTools シェルフは変更していません。\n再作成する場合は、MayaのShelf Editorで nTools タブだけを削除し、再起動後に Repair Shelf を実行してください。');return
        if not _confirm('nToolsシェルフを新規登録します。既存のシェルフやメニュー設定は変更しません。','Repair'): return
        register_shelf(m)
        _notify('nToolsシェルフを登録しました。\nツールは今すぐ使用できます。')
    except Exception as exc:
        traceback.print_exc(); _notify('シェルフ登録失敗：\n'+str(exc)+'\n本体は保持しています。MayaのUIを確認してください。')


def _uninstall_guide():
    """Display copyable instructions without modifying the shelf or package."""
    code = _command('nt.uninstall()')
    try:
        try:
            from PySide6 import QtGui, QtWidgets
            from shiboken6 import wrapInstance
        except ImportError:
            from PySide2 import QtGui, QtWidgets
            from shiboken2 import wrapInstance
        import maya.OpenMayaUI as omui
        ptr = omui.MQtUtil.mainWindow()
        parent = wrapInstance(int(ptr), QtWidgets.QWidget) if ptr else None
        dialog = QtWidgets.QDialog(parent)
        dialog.setWindowTitle('nTools — アンインストール')
        dialog.resize(690, 405)
        dialog.setMinimumWidth(510)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QtWidgets.QLabel('シェルフと本体を順番に削除します。')
        font = title.font(); font.setBold(True); title.setFont(font)
        title.setWordWrap(True); layout.addWidget(title)
        steps = QtWidgets.QLabel(
            '① Maya標準のShelf Editorで nTools タブだけを削除。\n'
            '② Save All Shelves で保存し、Mayaを再起動。\n'
            '③ 再起動後、Script EditorのPythonタブに下のコードを貼り付けて実行。')
        steps.setWordWrap(True); layout.addWidget(steps)

        code_header = QtWidgets.QLabel('本体削除用 Pythonコード')
        layout.addWidget(code_header)
        row = QtWidgets.QHBoxLayout(); layout.addLayout(row)
        editor = QtWidgets.QPlainTextEdit()
        editor.setPlainText(code)
        editor.setReadOnly(True)
        editor.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        font_db = QtGui.QFontDatabase
        fixed = getattr(font_db, 'FixedFont', None)
        if fixed is None: fixed = font_db.SystemFont.FixedFont
        editor.setFont(font_db.systemFont(fixed))
        editor.setMinimumHeight(135)
        row.addWidget(editor, 1)
        side = QtWidgets.QVBoxLayout(); row.addLayout(side)
        copy_button = QtWidgets.QPushButton('コピー')
        copy_button.setMinimumWidth(88)
        copy_button.setAutoDefault(False)
        copy_button.setToolTip('Pythonコードだけをクリップボードにコピーします。')
        side.addWidget(copy_button); side.addStretch(1)
        status = QtWidgets.QLabel('コピーしたコードは再起動前にメモ帳などへ保存しておくと確実です。')
        status.setWordWrap(True); layout.addWidget(status)

        def copy_code():
            clipboard = QtWidgets.QApplication.clipboard()
            if clipboard is None:
                status.setText('コピーできませんでした。Script Editorにコードを表示しました。')
                print(code)
                return
            clipboard.setText(code)
            status.setText('コードをコピーしました。再起動前にメモ帳などへ貼り付けて保存できます。')
        copy_button.clicked.connect(copy_code)
        notice = QtWidgets.QLabel('この画面ではシェルフも本体も削除しません。コードを実行すると最終確認が表示されます。')
        notice.setWordWrap(True); layout.addWidget(notice)
        bottom = QtWidgets.QHBoxLayout(); layout.addLayout(bottom)
        bottom.addStretch(1)
        close = QtWidgets.QPushButton('閉じる'); close.setAutoDefault(False)
        close.clicked.connect(dialog.reject); bottom.addWidget(close)
        if hasattr(dialog, 'exec'): dialog.exec()
        else: dialog.exec_()
    except Exception:
        # Preserve the two-stage removal if Qt is unavailable; never attempt
        # automatic deletion as a fallback. Code remains available in the log.
        traceback.print_exc()
        print('nTools: 本体削除用 Pythonコード:\n'+code)
        _notify('Shelf EditorでnToolsだけを削除し、Save All Shelvesで保存・再起動してください。\n'
                '再起動前にScript Editorの履歴に表示したPythonコードを保存し、再起動後に実行してください。\n'
                'この段階では何も削除していません。')


def uninstall_from_shelf():
    # No automatic deletion of a running Maya shelf. Guide user to native UI.
    uninstall()


def uninstall():
    """Two-stage uninstall; never delete a live shelf programmatically."""
    try:
        _ui_snapshot(); cmds,_=_maya(); dest=_target()
        if getattr(sys,'_ntools_restart_required',False):
            _notify('先にMayaを再起動してください。'); return
        if _installed() is None: raise RuntimeError('認識できるnTools本体がありません。変更しません。')
        if cmds.shelfLayout(_shelf(),exists=True):
            if not _owned_shelf():
                raise RuntimeError('nToolsシェルフに未確認のボタンがあります。自動削除しません。')
            _backup_ui()
            _uninstall_guide()
            return
        # Check persistent registrations before moving the package.
        if _shelf_path().exists():
            raise RuntimeError('シェルフファイルが残っています。Shelf Editorで削除・保存し、再起動してください。')
        if cmds.optionVar(exists='numShelves'):
            count=int(cmds.optionVar(q='numShelves'))
            for i in range(1,count+1):
                for key in ('shelfName','shelfFile'):
                    k=key+str(i)
                    if cmds.optionVar(exists=k):
                        v=str(cmds.optionVar(q=k)).replace('\\','/').split('/')[-1].casefold()
                        if v in ('ntools','shelf_ntools','shelf_ntools.mel'):
                            raise RuntimeError('nToolsのシェルフ登録情報が残っています。Mayaを再起動して確認してください。')
        if not _confirm('nTools本体を復元可能なバックアップに移動します。\nシーン・他のシェルフ・Maya.envは変更しません。\n作業を保存し、nToolsのウィンドウを閉じてください。','Uninstall'):return
        backup=dest.parent/('.ntools-uninstalled-'+uuid.uuid4().hex)
        dest.rename(backup); sys._ntools_restart_required=True
        _notify('nTools本体をアンインストールしました。Mayaを再起動してください。\nバックアップ：'+str(backup))
    except Exception as exc:
        traceback.print_exc(); _notify('アンインストール中止：\n'+str(exc))


def manage():
    cmds,_=_maya()
    choice=cmds.confirmDialog(title='nTools Manager',message='nToolsの管理操作を選んでください。',button=['Update','Repair Shelf','Add Help Button','Add Uninstall Button','Uninstall','Cancel'],defaultButton='Cancel',cancelButton='Cancel',dismissString='Cancel')
    if choice=='Update': update()
    elif choice=='Repair Shelf': repair_shelf()
    elif choice=='Add Help Button': add_help_button()
    elif choice=='Add Uninstall Button': add_uninstall_button()
    elif choice=='Uninstall': uninstall()


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
    """File transaction only. Never access or mutate Maya UI here."""
    dest=_target(); dest.parent.mkdir(parents=True,exist_ok=True)
    old=_installed()
    if dest.is_symlink() or (dest.exists() and old is None):
        raise RuntimeError('Existing unrecognized ntools folder. No files changed: '+str(dest))
    stage=Path(tempfile.mkdtemp(prefix='.ntools-stage-',dir=str(dest.parent)))
    backup=dest.parent/('.ntools-backup-'+uuid.uuid4().hex)
    moved=False; installed=False
    try:
        for relative,data in payload.items():
            p=stage/relative; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(data)
        if dest.exists(): dest.rename(backup); moved=True
        stage.rename(dest); installed=True
        importlib.invalidate_caches()
    except Exception:
        if installed: shutil.rmtree(dest)
        if moved: backup.rename(dest)
        raise
    finally:
        if stage.exists(): shutil.rmtree(stage,ignore_errors=True)
    # Keep all backups; never prune directories that could contain user data.
    if moved: print('nTools previous package:', backup)
    if old is not None: sys._ntools_restart_required=True
    return old is not None


def _confirm(message, yes='Install'):
    cmds,_=_maya()
    return cmds.confirmDialog(title='nTools',message=message,button=[yes,'Cancel'],defaultButton='Cancel',cancelButton='Cancel',dismissString='Cancel')==yes


def _notify(message):
    cmds,_=_maya(); cmds.confirmDialog(title='nTools',message=message,button=['OK'])


def install(source=None):
    """Install local release; create shelf only if absent and safe."""
    try:
        if getattr(sys,'_ntools_restart_required',False):
            _notify('前回の更新・アンインストールを反映するため、先にMayaを再起動してください。');return
        _ui_snapshot()
        path=Path(source).resolve() if source else None
        if path and path.is_file(): path=path.parent
        if path is None:
            file=globals().get('__file__'); path=Path(file).resolve().parent if file else None
        local=path is not None and (path/'version.json').is_file() and (path/'scripts'/'ntools').is_dir()
        m,payload=_local(path) if local else _online()
        if _version(m['version'])<_version(INSTALLER_VERSION): raise RuntimeError('旧版はインストールできません。')
        old=_installed(); cmds,_=_maya(); exists=cmds.shelfLayout(_shelf(),exists=True)
        if old is None and exists: raise RuntimeError('同名の既存シェルフがあります。変更しません。')
        if old and _version(m['version'])<_version(old['version']): raise RuntimeError('旧版はインストールできません。')
        msg='nTools '+m['version']+' を導入します。\n既存のシェルフは削除・再構築しません。\nInstall + Shelfでは不足する管理ボタンとSeparatorのみ追加します。'
        if old is None: msg+='\n初回導入は再起動不要です。'
        choice=cmds.confirmDialog(title='nTools',message=msg,button=['Install + Shelf','Files Only','Cancel'],defaultButton='Install + Shelf',cancelButton='Cancel',dismissString='Cancel')
        if choice not in ('Install + Shelf','Files Only'):return
        restart=_apply(m,payload)
        if not exists and choice=='Install + Shelf':
            try: register_shelf(m)
            except Exception as exc:
                traceback.print_exc(); _notify('本体の導入は完了しましたが、シェルフ登録を中止しました。\n'+str(exc)+'\nMayaのUIを確認後、Repair Shelfを実行してください。');return
        note='既存の本体を更新したため、Mayaを再起動してください。' if restart else '再起動は不要です。nTools シェルフを選ぶと、今すぐ使用できます。'
        if not exists and choice=='Files Only':
            note='本体のみ導入しました。管理画面のRepair Shelfでシェルフを登録してください。'
            note+='\n既存の本体を更新したため、先にMayaを再起動してください。' if restart else '\n初回導入は再起動不要です。'
        if exists and choice=='Install + Shelf':
            try: note+='\n'+_sync_management_buttons(m)
            except Exception as exc:
                traceback.print_exc(); note+='\n本体は導入済みですが、シェルフの同期は中止しました：\n'+str(exc)
        if exists and choice=='Files Only': note+='\n既存のシェルフは変更していません。再起動後、Updateで管理ボタンとSeparatorを確認できます。'
        _notify('インストール完了！ nTools '+m['version']+'\n'+note)
    except Exception as exc:
        traceback.print_exc();_notify('インストール失敗：\n'+str(exc)+'\n詳細は Script Editor を確認してください。')


def update():
    """Update package and synchronize the known management buttons.

    Old v1.0.3–1.0.5 updaters cannot run this new code until restart. On the
    next click, even an already-current manifest triggers shelf sync.
    """
    global _UPDATE_BUSY
    if _UPDATE_BUSY: return
    if getattr(sys,'_ntools_restart_required',False):
        _notify('先にMayaを再起動してください。'); return
    _UPDATE_BUSY = True
    scheduled = False
    try:
        old = _installed()
        if old is None: raise RuntimeError('nTools is not installed. Run install.py again.')
        # Check Maya before network/file changes, especially legacy bad tabs.
        _ui_snapshot()
        m,payload = _online()
        newer = _version(m['version']) > _version(old['version'])
        if newer:
            if not _confirm('nTools '+old['version']+' → '+m['version']+'\n本体を更新し、不足する管理ボタンとSeparatorがあれば追加します。\nシェルフは削除・再構築しません。シーンを保存し、ツールの作業を終えてください。\n本体更新後はMayaの再起動が必要です。','Update'): return
            _apply(m,payload)
            title = '更新完了：nTools '+m['version']+'\n本体の反映にはMayaを再起動してください。'
        else:
            title = ('現在の nTools '+old['version']+' は最新版です。' if m['version']==old['version'] else '現在の nTools '+old['version']+' はGitHub版より新しいため、本体は変更しません。')
        def finish():
            global _UPDATE_BUSY
            try:
                # Re-read installed metadata after the file transaction; the
                # currently executing updater may be an older in-memory module.
                message = _sync_management_buttons(_installed())
                _notify(title+'\n'+message)
            except Exception as exc:
                traceback.print_exc()
                _notify(title+'\nシェルフの同期は中止しました：\n'+str(exc))
            finally:
                _UPDATE_BUSY = False
        # Let the original shelf button callback finish before moving buttons.
        # The deferred callable is not stored as a shelf command.
        cmds,_ = _maya()
        cmds.evalDeferred(finish)
        scheduled = True
    except Exception as exc:
        traceback.print_exc(); _notify('更新失敗：\n'+str(exc)+'\n詳細は Script Editor を確認してください。')
    finally:
        if not scheduled: _UPDATE_BUSY = False


def onMayaDroppedPythonFile(*args):
    install(globals().get('__file__'))


if __name__=='__main__':
    install(globals().get('__file__'))
