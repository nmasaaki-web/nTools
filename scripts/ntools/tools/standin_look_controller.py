# -*- coding: utf-8 -*-
"""nTools Stand-in Look Controller v1.0 (Maya 2027 / MtoA).

Safe, opt-in per-procedural look controls for ASS created by PolyHaven v5.4.7+.
The shader network is prepared before .ass export; the values are subsequently
controlled by Arnold user data on aiStandIn shapes. No ASS files are edited.

This intentionally does *not* apply arbitrary shader overrides to unrelated,
old or third-party ASS archives. Those lack guaranteed control nodes.
"""
import json
from collections import OrderedDict

try:
    import maya.cmds as cmds
except ImportError:
    cmds = None
try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    try:
        from PySide2 import QtCore, QtWidgets
    except ImportError:
        QtCore = QtWidgets = None

PROFILE_ATTR = 'ntoolsLookProfile'
# Maya's mtoa_constant_ prefix maps a procedural attribute to Arnold user data.
CONTROLS = OrderedDict([
    ('sss_weight',       ('Plant SSS', 'Subsurface Weight',       0.0, 0.0, 1.0)),
    ('sss_saturation',   ('Plant SSS', 'SSS Color Saturation',     1.0, 0.0, 2.0)),
    ('base_exposure',    ('Surface',   'Base Color Exposure',    0.0,-3.0, 3.0)),
    ('base_saturation',  ('Surface',   'Base Color Saturation',   1.0, 0.0, 2.0)),
    ('coat_weight',      ('Surface',   'Coat Weight',             0.0, 0.0, 1.0)),
])


def arnold_user_attr(control):
    if control not in CONTROLS:
        raise KeyError('Unknown look control: ' + str(control))
    return 'ntools_' + control


def maya_standin_attr(control):
    return 'mtoa_constant_' + arnold_user_attr(control)


def _has_attr(node, name):
    try:
        return cmds.attributeQuery(name, node=node, exists=True)
    except Exception:
        return False


def _source(plug):
    return (cmds.listConnections(plug, source=True, destination=False, plugs=True) or [None])[0]


def _userdata_float(target, attribute, control):
    """Connect constant-default aiUserDataFloat only to a free float input.

    The defaults reproduce the prior appearance when procedural user data is
    absent. The node's floatAttrName is per-stand-in, not per polygon shape.
    """
    dest = target + '.' + attribute
    if not _has_attr(target, attribute) or _source(dest):
        return False
    node = None
    try:
        node = cmds.shadingNode('aiUserDataFloat', asUtility=True,
                                name=target.split('|')[-1] + '_'+control+'_UserData')
        cmds.setAttr(node+'.floatAttrName', arnold_user_attr(control), type='string')
        cmds.setAttr(node+'.defaultValue', CONTROLS[control][2])
        cmds.connectAttr(node+'.outValue', dest, force=False)
        return True
    except Exception:
        if node and cmds.objExists(node):
            try: cmds.delete(node)
            except Exception: pass
        return False


def _base_color_correction(mat):
    """Insert neutral aiColorCorrect *without losing* texture/UV connectivity."""
    original = _source(mat+'.baseColor') if _has_attr(mat,'baseColor') else None
    if not original:
        return None
    node = None
    try:
        node=cmds.shadingNode('aiColorCorrect', asUtility=True,
                              name=mat.split('|')[-1]+'_StandInBaseAdjust')
        input_attr = next((a for a in ('input','inputColor','inColor') if _has_attr(node,a)), None)
        output_attr = next((a for a in ('outColor','outValue') if _has_attr(node,a)), None)
        if not input_attr or not output_attr:
            raise RuntimeError('Unsupported aiColorCorrect input/output')
        cmds.connectAttr(original,node+'.'+input_attr,force=True)
        cmds.disconnectAttr(original,mat+'.baseColor')
        cmds.connectAttr(node+'.'+output_attr,mat+'.baseColor',force=False)
        return node
    except Exception:
        try:
            if _source(mat+'.baseColor') != original:
                if _source(mat+'.baseColor'):
                    cmds.disconnectAttr(_source(mat+'.baseColor'),mat+'.baseColor')
                cmds.connectAttr(original,mat+'.baseColor',force=True)
        finally:
            if node and cmds.objExists(node):
                try:cmds.delete(node)
                except Exception:pass
        return None


def prepare_export_materials(materials, log=print):
    """Prepare eligible OpenPBR shaders before Arnold ASS export.

    `materials`: asset material records returned by the PolyHaven importer.
    Multiple materials intentionally share controls for a *single* stand-in.
    Returns profile for persistence on the resulting aiStandIn shape.
    """
    available = set()
    for record in materials.values():
        mat = record.get('mat')
        if not mat or not cmds.objExists(mat) or cmds.nodeType(mat) != 'openPBRSurface':
            continue
        if (record.get('foliage') and _has_attr(mat,'subsurfaceColor')
                and _source(mat+'.subsurfaceColor')):
            if _userdata_float(mat,'subsurfaceWeight','sss_weight'):
                available.add('sss_weight')
            if _has_attr(mat,'subsurfaceColor'):
                ss_src = _source(mat+'.subsurfaceColor')
                if ss_src:
                    ss_node=ss_src.split('.')[0]
                    if cmds.nodeType(ss_node)=='aiColorCorrect' and _userdata_float(
                            ss_node,'saturation','sss_saturation'):
                        available.add('sss_saturation')
        cc=_base_color_correction(mat)
        if cc:
            if _userdata_float(cc,'exposure','base_exposure'):
                available.add('base_exposure')
            if _userdata_float(cc,'saturation','base_saturation'):
                available.add('base_saturation')
        # A nonzero existing coat is artist-authored. Never replace its default
        # with the controller's zero baseline when creating a neutral archive.
        if (_has_attr(mat,'coatWeight') and not _source(mat+'.coatWeight')
                and abs(float(cmds.getAttr(mat+'.coatWeight'))) < 1e-6
                and _userdata_float(mat,'coatWeight','coat_weight')):
            available.add('coat_weight')
    profile = {'schema':1,'producer':'nTools/PolyHaven',
               'controls':[key for key in CONTROLS if key in available]}
    log('[Stand-in Look] Prepared controls: '+(', '.join(profile['controls']) or 'none'))
    return profile


def attach_profile(shape, profile):
    """Create whitelisted procedural user attributes on a new aiStandIn."""
    if cmds.nodeType(shape) != 'aiStandIn':
        raise ValueError('Expected an aiStandIn shape')
    if not _has_attr(shape,PROFILE_ATTR):
        cmds.addAttr(shape, longName=PROFILE_ATTR, dataType='string')
    cmds.setAttr(shape+'.'+PROFILE_ATTR,json.dumps(profile,ensure_ascii=False),type='string')
    for control in profile['controls']:
        plug=maya_standin_attr(control)
        if not _has_attr(shape,plug):
            cmds.addAttr(shape,longName=plug,attributeType='float',keyable=True)
        cmds.setAttr(shape+'.'+plug,CONTROLS[control][2])


def read_profile(shape):
    if cmds is None or not _has_attr(shape, PROFILE_ATTR):
        return None
    try:
        data=json.loads(cmds.getAttr(shape+'.'+PROFILE_ATTR))
        if data.get('schema')!=1 or data.get('producer')!='nTools/PolyHaven':
            return None
        valid=[k for k in data.get('controls',[]) if k in CONTROLS
               and _has_attr(shape,maya_standin_attr(k))]
        return {'schema':1,'controls':valid,'producer':'nTools/PolyHaven'}
    except (ValueError,TypeError,RuntimeError,AttributeError):
        return None


def standins_in_selection():
    if cmds is None: return []
    found=[]
    for selected in cmds.ls(selection=True,long=True) or []:
        obj=selected.split('.',1)[0]
        if cmds.nodeType(obj)=='aiStandIn':
            found.append(obj)
        else:
            found.extend(cmds.listRelatives(obj,shapes=True,fullPath=True,type='aiStandIn') or [])
    return list(dict.fromkeys(found))


def archive_key(shape):
    return str(cmds.getAttr(shape+'.dso') or '').replace('\\','/').lower()


def target_standins(selected, all_same_archive):
    """Expand selected stand-ins by exact archive path only after opting in."""
    selected=list(dict.fromkeys(selected))
    if not all_same_archive: return selected
    keys={archive_key(shape) for shape in selected}
    return [node for node in (cmds.ls(type='aiStandIn',long=True) or [])
            if archive_key(node) in keys and read_profile(node)]


def apply_controls(shapes, values, all_same_archive=True, confirm_instance=None):
    """Preflight all nodes, then apply changes as one Maya undo chunk.

    On selected-only operation, disable autoInstancing when multiple instances
    share the same ASS and the user explicitly consents to memory impact.
    """
    if not shapes or not values: raise ValueError('Select nTools Stand-ins and at least one control.')
    if any(key not in CONTROLS for key in values): raise ValueError('Unrecognized control.')
    for key,value in values.items():
        lo,hi=CONTROLS[key][3:5]
        if not lo<=float(value)<=hi: raise ValueError(key+' out of range.')
    targets=target_standins(shapes,all_same_archive)
    if not targets: raise ValueError('No matching Stand-ins.')
    # Preflight *all* targets before touching any scene attribute.
    for shape in targets:
        profile=read_profile(shape)
        if not profile or any(key not in profile['controls'] for key in values):
            raise ValueError(shape+': このASSには指定された調整チャンネルがありません。')
    disable_instances=[]
    if not all_same_archive:
        for shape in targets:
            siblings=[n for n in (cmds.ls(type='aiStandIn',long=True) or [])
                      if n!=shape and archive_key(n)==archive_key(shape)]
            if siblings and not _has_attr(shape,'autoInstancing'):
                raise ValueError('このMtoAではAuto Instancingの制御属性を確認できません。'
                                 '個別変更を中止しました。')
            if siblings and cmds.getAttr(shape+'.autoInstancing'):
                disable_instances.append(shape)
        if disable_instances:
            if confirm_instance is None or not confirm_instance(len(disable_instances)):
                raise ValueError('個別調整には自動インスタンス化OFFの確認が必要です。')
    undo_open=False
    try:
        cmds.undoInfo(openChunk=True,chunkName='nTools Stand-in Look')
        undo_open=True
        for shape in disable_instances:
            cmds.setAttr(shape+'.autoInstancing',False)
        for shape in targets:
            for key,val in values.items():
                cmds.setAttr(shape+'.'+maya_standin_attr(key),float(val))
    except Exception:
        if undo_open:
            cmds.undoInfo(closeChunk=True);undo_open=False
            try:cmds.undo()
            except Exception:pass
        raise
    finally:
        if undo_open:cmds.undoInfo(closeChunk=True)
    return len(targets)


_WINDOW = None

if QtWidgets is not None:
    class LookDialog(QtWidgets.QDialog):
        def __init__(self,parent=None):
            super(LookDialog,self).__init__(parent)
            self.setObjectName('nToolsStandinLookController')
            self.setWindowTitle('nTools | Stand-in Look Controller')
            self.resize(520,470)
            root=QtWidgets.QVBoxLayout(self)
            intro=QtWidgets.QLabel('PolyHavenで作成したASSを選択し、変更する項目だけチェックしてください。')
            intro.setWordWrap(True);root.addWidget(intro)
            buttons=QtWidgets.QHBoxLayout()
            self.targets_label=QtWidgets.QLabel('Stand-in未選択')
            buttons.addWidget(self.targets_label,1)
            scan=QtWidgets.QPushButton('選択を読み込み');scan.clicked.connect(self.refresh);buttons.addWidget(scan)
            root.addLayout(buttons)
            self.tabs=QtWidgets.QTabWidget();root.addWidget(self.tabs,1)
            self.inputs={}
            for section in ('Plant SSS','Surface'):
                widget=QtWidgets.QWidget();lay=QtWidgets.QVBoxLayout(widget)
                for name,(cat,label,default,low,high) in CONTROLS.items():
                    if cat!=section:continue
                    row=QtWidgets.QHBoxLayout();check=QtWidgets.QCheckBox(label)
                    check.setToolTip('チェックした場合のみ書き換えます。')
                    spin=QtWidgets.QDoubleSpinBox();spin.setRange(low,high)
                    spin.setDecimals(3);spin.setSingleStep(0.05);spin.setValue(default)
                    spin.valueChanged.connect(lambda _value,c=check:c.setChecked(True))
                    row.addWidget(check,1);row.addWidget(spin)
                    lay.addLayout(row);self.inputs[name]=(check,spin)
                if section=='Surface':
                    note=QtWidgets.QLabel('Roughness・Metalnessのテクスチャ接続は変更しません。\n'
                         'Base Color Exposure/Saturationは元の色テクスチャを保持します。')
                    note.setWordWrap(True);lay.addWidget(note)
                lay.addStretch(1);self.tabs.addTab(widget,section)
            self.same=QtWidgets.QCheckBox('同じASSを使用するすべてのStand-inに適用')
            self.same.setChecked(True);root.addWidget(self.same)
            self.message=QtWidgets.QLabel('注：既存の旧ASS・外部ASSには制御チャンネルがありません。')
            self.message.setWordWrap(True);root.addWidget(self.message)
            actions=QtWidgets.QHBoxLayout();actions.addStretch(1)
            apply=QtWidgets.QPushButton('選択した項目を適用');apply.clicked.connect(self.apply);actions.addWidget(apply)
            close=QtWidgets.QPushButton('閉じる');close.clicked.connect(self.close);actions.addWidget(close);root.addLayout(actions)
            self.refresh()

        def refresh(self):
            self.shapes=standins_in_selection()
            supported=[s for s in self.shapes if read_profile(s)]
            self.targets_label.setText('選択: %d 件 / nTools対応: %d 件' % (len(self.shapes),len(supported)))
            common=set.intersection(*(set(read_profile(s)['controls']) for s in supported)) if supported else set()
            for name,(check,spin) in self.inputs.items():
                check.setChecked(False);check.setEnabled(name in common)
                spin.setEnabled(name in common)
                if name in common:
                    val=cmds.getAttr(supported[0]+'.'+maya_standin_attr(name))
                    spin.blockSignals(True);spin.setValue(float(val));spin.blockSignals(False)
            self.message.setText('調整できる項目: '+(', '.join(common) or 'なし')+
                '。非対応ASSは最新版PolyHavenで再生成してください。')

        def _confirm_instances(self,n):
            return QtWidgets.QMessageBox.question(self,'個別ASSの負荷について',
                '個別の見た目を保持するため%d件のAuto InstancingをOFFにします。\n'
                '複製が多い場合、レンダリングメモリ使用量が増える可能性があります。続けますか？' % n,
                QtWidgets.QMessageBox.Yes|QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No)==QtWidgets.QMessageBox.Yes

        def apply(self):
            values={k:spin.value() for k,(check,spin) in self.inputs.items() if check.isChecked()}
            try:
                n=apply_controls(self.shapes,values,self.same.isChecked(),self._confirm_instances)
                QtWidgets.QMessageBox.information(self,'Stand-in Look','%d件のStand-inを更新しました。\nArnold RenderViewで結果をご確認ください。'%n)
                self.refresh()
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self,'更新を中止しました',str(exc))


def show(parent=None):
    global _WINDOW
    if cmds is None or QtWidgets is None:
        raise RuntimeError('Run inside Maya 2027 with Qt / Arnold.')
    if _WINDOW is not None:
        try:_WINDOW.close();_WINDOW.deleteLater()
        except RuntimeError:pass
    _WINDOW=LookDialog(parent)
    _WINDOW.show();_WINDOW.raise_();_WINDOW.activateWindow()
    return _WINDOW
