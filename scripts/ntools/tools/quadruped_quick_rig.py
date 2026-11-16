# -*- coding: utf-8 -*-
"""Quadruped Quick Rig v2.4 (Maya 2027 / Python 3)

One-file tool. Copy the complete file into Maya Script Editor (Python) and run.
No third-party plugins. Uses maya.cmds and maya.api.OpenMaya.

FUNCTIONS
 - Horse / Dog / Wolf / Cat guide presets; independent character tags
 - World-origin motion root (0,0,0), separate anatomical pelvis
 - Editable guide locators, mirror left to right
 - Quick Rig-style vertical, numbered user interface (new scenes only)
 - Deformation skeleton, hierarchical torso FK, separate FK/IK driver legs
 - 2-joint RP IK to ankle + 1-joint SC IK to paw, PV, foot/toe controls
 - Per-leg IK/FK weighted orient constraint and visibility switch
 - Pose matching at current frame (approximate when IK foot rotates)
 - Bind selected polygon meshes, prevent accidental rebinding
 - Inspect source skeleton, auto-suggest and manually edit 31 mappings
 - Source re-selection clears stale mappings; prevents source/target mix-ups
 - Experimental sampled FK animation transfer (quaternion world delta;
   optional heading alignment & translation scaling) + baked keyframes

IMPORTANT LIMITATIONS
 This is not a certified MotionMaker/HumanIK character definition. Motion
 transfer is a generic pose-delta solution; it is not Autodesk HumanIK and
 does not guarantee contact, anatomical equivalence or stride correction.
 Generate animation on MotionMaker Equine or Canine first, then identify the
 *animated source JOINT hierarchy* in Maya, inspect the proposed mappings,
 and bake. For best results use same-species source/target; repair feet with IK.
 Test in a copy of your scene. Actual Maya 2027 runtime has not been tested.

Assumptions: world Y up, animal faces +Z, character left is +X,
 transforms have unit scale and no shear. Root at world origin is THIS
 rig's workflow choice; it is not a universal HumanIK requirement.
 Direction does NOT by itself make
 this skeleton HumanIK-characterized: HIK needs correct mapping and T-stance. The rest frame for transfer is chosen by the user.
"""
from __future__ import division
import json
import math
import re
import traceback
import webbrowser

import maya.cmds as cmds
import maya.api.OpenMaya as om

VERSION = '2.4.0'
WIN = 'QQR2027_v24_WIN'
ANIM_ROLES = [
    'root', 'pelvis', 'spine1', 'chest', 'neck1', 'neck2', 'head',
    'nose', 'tail1', 'tail2', 'tail3'
]
SIDES = ('L', 'R')
LIMBS = ('front', 'hind')
SEGMENTS = ('hip', 'knee', 'ankle', 'paw', 'toe')
BODY_PARENT = {
    'root': None, 'pelvis': 'root', 'spine1': 'pelvis',
    'chest': 'spine1', 'neck1': 'chest', 'neck2': 'neck1',
    'head': 'neck2', 'nose': 'head', 'tail1': 'pelvis',
    'tail2': 'tail1', 'tail3': 'tail2'
}
for _side in SIDES:
    for _limb in LIMBS:
        _base = '%s_%s_' % (_side, _limb)
        ANIM_ROLES.extend(_base + seg for seg in SEGMENTS)

PRESETS = {
    'Horse': dict(L=9.0, H=6.0, N=3.0, T=3.0, W=.19, kind='equine'),
    'Dog':   dict(L=6.0, H=4.1, N=1.5, T=2.6, W=.19, kind='canine'),
    'Wolf':  dict(L=7.2, H=4.8, N=1.8, T=2.9, W=.17, kind='canine'),
    'Cat':   dict(L=5.0, H=3.4, N=1.25, T=3.2, W=.15, kind='feline')
}
_UI = {}


def _prefix(tag):
    value = re.sub(r'[^A-Za-z0-9_]', '_', str(tag).strip())
    if not value or not re.match(r'^[A-Za-z_]', value):
        raise ValueError('Character tag must start with a letter or underscore.')
    return 'QQR_%s_' % value


def _n(tag, suffix):
    return _prefix(tag) + suffix


def _at(node):
    return cmds.xform(node, q=True, ws=True, t=True)


def _setpos(node, pos):
    cmds.xform(node, ws=True, t=[float(x) for x in pos])


def _vec(a, b):
    return [a[i] - b[i] for i in range(3)]


def _length(v):
    return math.sqrt(sum(x * x for x in v))


def _vadd(a, b):
    return [a[i] + b[i] for i in range(3)]


def _scale(v, k):
    return [x * k for x in v]


def _unit(v, fallback=(0, 0, 1)):
    d = _length(v)
    return [x / d for x in v] if d > 1e-8 else list(fallback)


def _project_pv(a, b, c, distance):
    a, b, c = _at(a), _at(b), _at(c)
    ac = _vec(c, a)
    t = sum((b[i] - a[i]) * ac[i] for i in range(3)) / max(1e-8, sum(v*v for v in ac))
    line = _vadd(a, _scale(ac, t))
    direction = _vec(b, line)
    if _length(direction) < 1e-5:
        direction = [0.0, 0.0, 1.0 if b[2] >= 0 else -1.0]
    return _vadd(b, _scale(_unit(direction), distance))


def _add_string(node, name, value):
    if not cmds.attributeQuery(name, node=node, exists=True):
        cmds.addAttr(node, ln=name, dt='string')
    cmds.setAttr(node + '.' + name, str(value), type='string')


def _read_string(node, attr, default=''):
    if cmds.objExists(node) and cmds.attributeQuery(attr, node=node, exists=True):
        return cmds.getAttr(node + '.' + attr) or default
    return default


def _color(ctrl, index):
    for sh in cmds.listRelatives(ctrl, s=True, ni=True, f=True) or []:
        cmds.setAttr(sh + '.overrideEnabled', 1)
        cmds.setAttr(sh + '.overrideColor', index)


def _curve(tag, role, position, radius, parent=None, color=17, normal=(0, 1, 0)):
    ctrl = cmds.circle(n=_n(tag, 'CTRL_' + role), nr=normal, r=radius,
                       ch=False, s=12)[0]
    zero = cmds.group(ctrl, n=_n(tag, 'ZERO_' + role))
    _setpos(zero, position)
    if parent:
        cmds.parent(zero, parent)  # retain world transform
    _color(ctrl, color)
    # Controls are intentionally not scaleable. Scaling live IK/FK hierarchies
    # with mixed joint constraints can create solver or skin artifacts.
    for axis in 'xyz':
        cmds.setAttr(ctrl+'.s'+axis, lock=True, keyable=False, channelBox=False)
    return ctrl, zero


def _guide_positions(preset):
    d = PRESETS[preset]
    L, H, N, T, W = (d[k] for k in ('L', 'H', 'N', 'T', 'W'))
    result = {
        'root': (0.0, 0.0, 0.0),  # ground-level motion root at world origin
        'pelvis': (-L*.36, H*.95, 0),
        'spine1': (-L*.09, H*.99, 0),
        'chest': (L*.30, H*1.01, 0),
        'neck1': (L*.38, H*1.08, 0),
        'neck2': (L*.38 + N*.5, H*1.27, 0),
        'head': (L*.38 + N*.85, H*1.37, 0),
        'nose': (L*.38 + N*1.28, H*1.30, 0),
        'tail1': (-L*.45, H*.94, 0),
        'tail2': (-L*.45 - T*.52, H*.82, 0),
        'tail3': (-L*.45 - T, H*.69, 0)
    }
    for side in SIDES:
        z = L * W * (1 if side == 'L' else -1)
        for leg in LIMBS:
            x = L * (.30 if leg == 'front' else -.36)
            if d['kind'] == 'equine':
                if leg == 'front':
                    pts = [(x, H*.97, z), (x-L*.045, H*.69, z),
                           (x-L*.005, H*.37, z), (x+L*.02, H*.11, z),
                           (x+L*.15, H*.065, z)]
                else:
                    pts = [(x, H*.95, z), (x+L*.14, H*.70, z),
                           (x-L*.08, H*.39, z), (x-L*.015, H*.12, z),
                           (x+L*.12, H*.065, z)]
            else:
                if leg == 'front':
                    pts = [(x, H*.98, z), (x-L*.07, H*.63, z),
                           (x+L*.025, H*.28, z), (x+L*.085, H*.075, z),
                           (x+L*.17, H*.055, z)]
                else:
                    pts = [(x, H*.94, z), (x+L*.12, H*.68, z),
                           (x-L*.115, H*.35, z), (x-L*.065, H*.08, z),
                           (x+L*.03, H*.055, z)]
            result.update(('%s_%s_%s' % (side, leg, seg), p)
                          for seg, p in zip(SEGMENTS, pts))
    # Anatomical guides above use (forward, height, lateral) internally.
    # Place into Maya world coordinates with +Z forward, +Y up, and
    # character LEFT on +X (the HumanIK default orientation).
    # This is intentionally a coordinate mapping, not a transform-node rotation.
    return {role: (pos[2], pos[1], pos[0])
            for role, pos in result.items()}


def _guide(tag, role, pos, root, radius):
    node = cmds.spaceLocator(n=_n(tag, 'G_' + role))[0]
    _setpos(node, pos)
    cmds.parent(node, root)
    for axis in 'XYZ':
        cmds.setAttr(node + '.localScale' + axis, radius)
    return node


def create_guides(tag='Animal', preset='Horse'):
    if preset not in PRESETS:
        raise ValueError('Unknown preset: ' + str(preset))
    if cmds.objExists(_n(tag, 'GUIDES')) or cmds.objExists(_n(tag, 'RIG')):
        raise RuntimeError('This tag already has guides or a rig. Use another tag.')
    root = cmds.group(em=True, n=_n(tag, 'GUIDES'))
    _add_string(root, 'qqrPreset', preset)
    _add_string(root, 'qqrForwardAxis', '+Z')
    _add_string(root, 'qqrLeftAxis', '+X')
    positions = _guide_positions(preset)
    radius = PRESETS[preset]['H'] * .045
    for role in ANIM_ROLES:
        _guide(tag, role, positions[role], root, radius)
    cmds.select(root, r=True)
    return root


def _validate_guide_axis(tag):
    """Check that current guides have the project's expected +Z orientation."""
    group = _n(tag, 'GUIDES')
    if not cmds.objExists(group):
        raise RuntimeError('Create Guides first for character: ' + tag)
    if _read_string(group, 'qqrForwardAxis', '') != '+Z':
        raise RuntimeError('Unexpected guide axis. Please create fresh +Z guides with this tool.')


def mirror_left_to_right(tag='Animal'):
    if not cmds.objExists(_n(tag, 'GUIDES')):
        raise RuntimeError('Create guides first.')
    _validate_guide_axis(tag)
    for leg in LIMBS:
        for seg in SEGMENTS:
            left = _n(tag, 'G_L_%s_%s' % (leg, seg))
            right = _n(tag, 'G_R_%s_%s' % (leg, seg))
            if not cmds.objExists(left) or not cmds.objExists(right):
                raise RuntimeError('Missing guide: %s or %s' % (left, right))
            x, y, z = _at(left)
            _setpos(right, (-x, y, z))


def _joint(tag, role, p, parent=None):
    cmds.select(cl=True)
    j = cmds.joint(n=_n(tag, 'J_' + role), p=p, radius=.16)
    if parent:
        cmds.parent(j, parent)
    return j


def _leg_children(root):
    result = []
    current = root
    for i in range(len(SEGMENTS)):
        result.append(current)
        children = cmds.listRelatives(current, c=True, type='joint', f=True) or []
        if i != len(SEGMENTS) - 1:
            if len(children) != 1:
                raise RuntimeError('Expected one joint child in leg chain: ' + current)
            current = children[0]
    return result


def _clone_leg(tag, deform_root, label, side, limb, ctrl_parent):
    dup = cmds.duplicate(deform_root, rc=True)[0]
    cmds.parent(dup, ctrl_parent)
    chain = _leg_children(dup)
    renamed = {}
    # Rename leaf first to keep parent DAG paths valid during renaming.
    for seg, node in reversed(list(zip(SEGMENTS, chain))):
        renamed[seg] = cmds.rename(node, _n(tag, '%s_%s_%s_%s' %
                                           (label, side, limb, seg)))
    return renamed


def _orient_leg(joints):
    chain = [joints[s] for s in SEGMENTS]
    # Non-recursive. Each joint is oriented once; no silent errors.
    for j in chain[:-1]:
        cmds.joint(j, e=True, oj='xyz', sao='zup', ch=False, zso=True)
    cmds.joint(chain[-1], e=True, oj='none', zso=True)


def _prepare_skeleton(tag, positions):
    J = {}
    for role in ANIM_ROLES[:11]:
        parent = BODY_PARENT[role]
        J[role] = _joint(tag, role, positions[role], J[parent] if parent else None)
    for side in SIDES:
        for limb in LIMBS:
            base = '%s_%s_' % (side, limb)
            torso = 'chest' if limb == 'front' else 'pelvis'
            parent = J[torso]
            for seg in SEGMENTS:
                name = base + seg
                J[name] = _joint(tag, name, positions[name], parent)
                parent = J[name]
            _orient_leg({s: J[base+s] for s in SEGMENTS})
    return J


def _switch_attr(side, limb):
    return '%s_%s_ikFk' % (side, limb)


def build_rig(tag='Animal'):
    guide_root, rig_name = _n(tag, 'GUIDES'), _n(tag, 'RIG')
    if not cmds.objExists(guide_root):
        raise RuntimeError('Create guides first for: ' + tag)
    if cmds.objExists(rig_name):
        raise RuntimeError('Rig already exists for: ' + tag)
    _validate_guide_axis(tag)
    positions = {}
    for role in ANIM_ROLES:
        g = _n(tag, 'G_' + role)
        if not cmds.objExists(g):
            raise RuntimeError('Missing guide: ' + g)
        positions[role] = _at(g)
    if _length(positions['root']) > 1e-4:
        cmds.warning('QQR v2.4: Root guide is not at world origin. '
                     'For the recommended ground-root layout, click '
                     'Move the G_root guide to (0,0,0) BEFORE Build Rig.')
    for side in SIDES:
        for limb in LIMBS:
            base = '%s_%s_' % (side, limb)
            p0, p1, p2 = (positions[base+s] for s in SEGMENTS[:3])
            if _length(_vec(p0, p1)) < .05 or _length(_vec(p1, p2)) < .05:
                raise RuntimeError('Too short / overlapping bone: ' + base)

    rig = cmds.group(em=True, n=rig_name)
    skeleton = cmds.group(em=True, n=_n(tag, 'SKELETON'), p=rig)
    controls = cmds.group(em=True, n=_n(tag, 'CONTROLS'), p=rig)
    drivers = cmds.group(em=True, n=_n(tag, 'DRIVERS'), p=rig)
    ik_system = cmds.group(em=True, n=_n(tag, 'IK_SYSTEM'), p=rig)
    J = _prepare_skeleton(tag, positions)
    cmds.parent(J['root'], skeleton)
    # No torso joint reorientation: controls match unrotated body joints.
    # The driver legs are duplicated AFTER deform-leg orientation.

    preset = _read_string(guide_root, 'qqrPreset', 'Horse')
    H = PRESETS.get(preset, PRESETS['Horse'])['H']
    global_ctrl, _ = _curve(tag, 'global', [0, 0, 0], H*.28,
                            parent=controls, color=17)
    body_controls = {}
    for role in ANIM_ROLES[:11]:
        parent_role = BODY_PARENT[role]
        parent_ctrl = body_controls[parent_role] if parent_role else global_ctrl
        c, zero = _curve(tag, role, positions[role], H*.095,
                         parent=parent_ctrl, color=17, normal=(0, 0, 1))
        body_controls[role] = c
        cmds.parentConstraint(c, J[role], mo=False,
                              n=_n(tag, 'PC_' + role))
    settings, _ = _curve(tag, 'settings',
                         _vadd(positions['chest'], [0, H*.22, 0]),
                         H*.085, parent=global_ctrl, color=22)
    # Settings control is for the ikFk attributes only.
    for channel in ('tx', 'ty', 'tz', 'rx', 'ry', 'rz', 'sx', 'sy', 'sz'):
        cmds.setAttr(settings + '.' + channel, lock=True,
                     keyable=False, channelBox=False)

    for side in SIDES:
        for limb in LIMBS:
            base = '%s_%s_' % (side, limb)
            torso_ctrl = body_controls['chest' if limb == 'front' else 'pelvis']
            fk = _clone_leg(tag, J[base+'hip'], 'FKJ', side, limb, torso_ctrl)
            ik = _clone_leg(tag, J[base+'hip'], 'IKJ', side, limb, torso_ctrl)
            col = 6 if side == 'L' else 13

            # FK controller hierarchy follows the driver hierarchy.
            parent_ctrl = torso_ctrl
            fk_vis_group = None
            for seg in SEGMENTS:
                role = base + seg + '_FK'
                c, z = _curve(tag, role, positions[base+seg], H*.065,
                              parent=parent_ctrl, color=col, normal=(0, 0, 1))
                # The zero group must share the driver's JOINT WORLD orientation.
                # Otherwise the first FK orientConstraint immediately changes
                # the bind pose and IK/FK switching pops at frame zero.
                cmds.xform(z, ws=True, ro=cmds.xform(fk[seg], q=True, ws=True, ro=True))
                if fk_vis_group is None:
                    fk_vis_group = z
                cmds.orientConstraint(c, fk[seg], mo=False,
                                      n=_n(tag, 'FKOC_' + base + seg))
                parent_ctrl = c
            # Toe also has an FK controller for manual rotation and retarget.

            foot, foot_grp = _curve(tag, base+'foot_IK', positions[base+'paw'],
                                    H*.085, parent=global_ctrl, color=col)
            pv_p = _project_pv(ik['hip'], ik['knee'], ik['ankle'], H*.28)
            pv, pv_grp = _curve(tag, base+'pole_IK', pv_p, H*.045,
                                parent=foot_grp, color=col)
            # Pole control must live in world/character space, NOT under the
            # foot control. Reparent it under global preserving world pose.
            cmds.parent(pv_grp, global_ctrl)
            toe, _ = _curve(tag, base+'toe_IK', positions[base+'toe'],
                             H*.04, parent=foot, color=col)
            rp_handle, _ = cmds.ikHandle(n=_n(tag, 'RP_' + base),
                                        sj=ik['hip'], ee=ik['ankle'],
                                        sol='ikRPsolver')
            sc_handle, _ = cmds.ikHandle(n=_n(tag, 'SC_' + base),
                                        sj=ik['ankle'], ee=ik['paw'],
                                        sol='ikSCsolver')
            ankle_target = cmds.group(em=True, n=_n(tag, 'ANKLE_' + base))
            _setpos(ankle_target, positions[base+'ankle'])
            cmds.parent(ankle_target, foot)
            cmds.parent(rp_handle, ankle_target)
            cmds.parent(sc_handle, foot)
            cmds.poleVectorConstraint(pv, rp_handle,
                                      n=_n(tag, 'PV_' + base))
            cmds.orientConstraint(foot, ik['paw'], mo=True,
                                  n=_n(tag, 'PAWOC_' + base))
            cmds.orientConstraint(toe, ik['toe'], mo=True,
                                  n=_n(tag, 'TOEOC_' + base))

            sw = _switch_attr(side, limb)
            cmds.addAttr(settings, ln=sw, at='double', min=0.0, max=1.0,
                         dv=1.0, k=True)
            rev = cmds.createNode('reverse', n=_n(tag, 'REV_' + base))
            cmds.connectAttr(settings+'.'+sw, rev+'.inputX')
            for seg in SEGMENTS:
                oc = cmds.orientConstraint(fk[seg], ik[seg], J[base+seg],
                                          mo=False,
                                          n=_n(tag, 'BLEND_' + base+seg))[0]
                cmds.setAttr(oc + '.interpType', 1)  # shortest quaternion interpolation
                aliases = cmds.orientConstraint(oc, q=True, wal=True)
                if len(aliases) != 2:
                    raise RuntimeError('IK/FK blend constraint failed: ' + oc)
                cmds.connectAttr(rev+'.outputX', oc+'.'+aliases[0], f=True)
                cmds.connectAttr(settings+'.'+sw, oc+'.'+aliases[1], f=True)
            cmds.connectAttr(rev+'.outputX', fk_vis_group+'.visibility')
            cmds.connectAttr(settings+'.'+sw, foot_grp+'.visibility')
            cmds.connectAttr(settings+'.'+sw, pv_grp+'.visibility')
            cmds.setAttr(fk['hip']+'.visibility', 0)
            cmds.setAttr(ik['hip']+'.visibility', 0)
    cmds.setAttr(drivers+'.visibility', 0)
    # Handles are already parented to the IK controls; the empty IK_SYSTEM
    # group is reserved for future handle additions. Do not hide foot controls.
    cmds.setAttr(ik_system+'.visibility', 0)
    cmds.setAttr(guide_root+'.visibility', 0)
    _add_string(rig, 'qqrVersion', VERSION)
    _add_string(rig, 'qqrTag', tag)
    _add_string(rig, 'qqrPreset', preset)
    cmds.select(global_ctrl, r=True)
    cmds.warning('QQR v2.4: Built basic IK/FK rig. Motion transfer is EXPERIMENTAL, not HumanIK.')
    return rig


def bind_selected_meshes(tag='Animal'):
    if not cmds.objExists(_n(tag, 'SKELETON')):
        raise RuntimeError('Build rig first.')
    selection = cmds.ls(sl=True, l=True) or []
    meshes = []
    for item in selection:
        if cmds.nodeType(item) == 'mesh':
            if not cmds.getAttr(item+'.intermediateObject'):
                meshes.extend(cmds.listRelatives(item, p=True, f=True) or [])
        elif cmds.nodeType(item) == 'transform':
            valid_shapes = [s for s in (cmds.listRelatives(item, s=True,
                                             ni=True, type='mesh', f=True) or [])]
            if valid_shapes:
                meshes.append(item)
    meshes = list(dict.fromkeys(meshes))
    if not meshes:
        raise RuntimeError('Select polygon mesh transforms or mesh shapes.')
    joints = cmds.listRelatives(_n(tag, 'SKELETON'), ad=True, type='joint', f=True) or []
    if not joints:
        raise RuntimeError('No deform joints found.')
    completed = []
    for mesh in meshes:
        existing = cmds.ls(cmds.listHistory(mesh) or [], type='skinCluster') or []
        if existing:
            cmds.warning('Skipped already-skinned mesh: ' + mesh)
            continue
        clean = re.sub(r'[^A-Za-z0-9_]', '_', mesh.split('|')[-1])
        cmds.skinCluster(joints, mesh, tsb=True, mi=4, nw=1,
                         n=_n(tag, 'SKIN_' + clean))
        completed.append(mesh)
    cmds.select(completed, r=True)
    return completed


def match_and_switch(tag, side, limb, key=False):
    """Best-effort one-leg pose matching. Not a perfect foot roll snap."""
    rig = _n(tag, 'RIG')
    if not cmds.objExists(rig):
        raise RuntimeError('Build rig first.')
    settings = _n(tag, 'CTRL_settings')
    plug = settings + '.' + _switch_attr(side, limb)
    base = '%s_%s_' % (side, limb)
    currently_ik = cmds.getAttr(plug) >= .5
    if currently_ik:
        # IK -> FK: align FK controls to current deform-joint orientations.
        pose = {seg: cmds.xform(_n(tag, 'J_'+base+seg), q=True, ws=True, ro=True)
                for seg in SEGMENTS}
        for seg in SEGMENTS:
            c = _n(tag, 'CTRL_'+base+seg+'_FK')
            cmds.xform(c, ws=True, ro=pose[seg])
            if key:
                cmds.setKeyframe(c, at='rotate')
        cmds.setAttr(plug, 0.0)
    else:
        # FK -> IK: place foot at paw, and PV along current bend plane.
        foot = _n(tag, 'CTRL_'+base+'foot_IK')
        pv = _n(tag, 'CTRL_'+base+'pole_IK')
        paw = _n(tag, 'J_'+base+'paw')
        coords = _at(paw)
        rotation = cmds.xform(paw, q=True, ws=True, ro=True)
        pv_target = _project_pv(_n(tag, 'J_'+base+'hip'),
                                 _n(tag, 'J_'+base+'knee'),
                                 _n(tag, 'J_'+base+'ankle'),
                                 max(.2, _length(_vec(_at(_n(tag, 'J_'+base+'hip')),
                                                     _at(_n(tag, 'J_'+base+'ankle'))))*.6))
        _setpos(foot, coords)
        cmds.xform(foot, ws=True, ro=rotation)
        _setpos(pv, pv_target)
        if key:
            for c in (foot, pv):
                cmds.setKeyframe(c, at=['translate', 'rotate'])
        cmds.setAttr(plug, 1.0)
    if key:
        cmds.setKeyframe(settings, at=_switch_attr(side, limb))
    return 'FK' if currently_ik else 'IK'


def validate_rig(tag='Animal'):
    """Structure-only smoke check in Maya; does NOT certify rig motion."""
    issues = []
    rig = _n(tag, 'RIG')
    if not cmds.objExists(rig):
        return ['Rig not found: ' + rig]
    required = ['RIG', 'SKELETON', 'CONTROLS', 'CTRL_global',
                'CTRL_root', 'CTRL_chest', 'CTRL_settings']
    required.extend('J_' + role for role in ANIM_ROLES)
    for side in SIDES:
        for limb in LIMBS:
            base = '%s_%s_' % (side, limb)
            required.extend(['CTRL_'+base+'foot_IK', 'CTRL_'+base+'pole_IK',
                             'RP_'+base, 'SC_'+base, 'CTRL_'+base+'toe_IK'])
            required.extend('CTRL_'+base+seg+'_FK' for seg in SEGMENTS)
            sw = _switch_attr(side, limb)
            settings = _n(tag, 'CTRL_settings')
            if not cmds.attributeQuery(sw, node=settings, exists=True):
                issues.append('Missing IK/FK switch: '+sw)
    for suffix in required:
        if not cmds.objExists(_n(tag, suffix)):
            issues.append('Missing node: '+_n(tag, suffix))
    for side in SIDES:
        for limb in LIMBS:
            base = '%s_%s_' % (side, limb)
            for seg in SEGMENTS:
                c = _n(tag, 'BLEND_'+base+seg)
                if not cmds.objExists(c):
                    issues.append('Missing IK/FK blend: '+c)
    return issues


# -------------------- source joint detection / mapping --------------------

def _find_joint_root(selection):
    if not selection or not cmds.objExists(selection):
        raise ValueError('Select an animated MotionMaker source root joint or hierarchy.')
    if cmds.nodeType(selection) == 'joint':
        return selection
    candidates = cmds.listRelatives(selection, ad=True, type='joint', f=True) or []
    if not candidates:
        raise ValueError('No joints found below selected transform.')
    s = set(candidates)
    roots = [j for j in candidates if not (cmds.listRelatives(j, p=True, f=True) or [''])[0] in s]
    if len(roots) != 1:
        raise ValueError('Found %d skeleton roots; select one source root JOINT.' % len(roots))
    return roots[0]


def _target_rig_members(tag):
    """All nodes parented inside QQR target RIG; uses full Maya DAG paths."""
    rig = _n(tag, 'RIG')
    if not cmds.objExists(rig):
        return set()
    long_rig = (cmds.ls(rig, l=True) or [rig])[0]
    return {long_rig} | set(cmds.listRelatives(long_rig, ad=True, f=True) or [])


def _is_target_member(tag, node):
    if not node or not cmds.objExists(node):
        return False
    long_node = (cmds.ls(node, l=True) or [node])[0]
    return long_node in _target_rig_members(tag)


def _mapping_target_conflicts(tag, mapping):
    """Return (role, full_path) for accidental source joints from target."""
    target_members = _target_rig_members(tag)
    return [(role, (cmds.ls(node, l=True) or [node])[0])
            for role, node in mapping.items()
            if cmds.objExists(node)
            and (cmds.ls(node, l=True) or [node])[0] in target_members]


def _same_dag_node(a, b):
    if not a or not b or not cmds.objExists(a) or not cmds.objExists(b):
        return False
    return (cmds.ls(a, l=True) or [a])[0] == (cmds.ls(b, l=True) or [b])[0]


def _source_joints(src_root):
    source = _find_joint_root(src_root)
    source = (cmds.ls(source, l=True) or [source])[0]
    return [source] + (cmds.listRelatives(source, ad=True, type='joint', f=True) or [])


def _tokens(name):
    part = name.split('|')[-1].split(':')[-1]
    part = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', part)
    return [s for s in re.sub(r'[^a-zA-Z0-9]+', '_', part).lower().split('_') if s]


def _side_type(tokens, compact):
    if 'left' in tokens or 'left' in compact or any(s in tokens for s in ('lf', 'lh')):
        return 'L'
    if 'right' in tokens or 'right' in compact or any(s in tokens for s in ('rf', 'rh')):
        return 'R'
    if re.search(r'(^|_)(l)(_|$)', '_'.join(tokens)):
        return 'L'
    if re.search(r'(^|_)(r)(_|$)', '_'.join(tokens)):
        return 'R'
    return None


def _limb_type(tokens, compact):
    if any(s in tokens for s in ('front', 'fore', 'foreleg', 'forelimb', 'lf', 'rf')) or 'front' in compact:
        return 'front'
    if any(s in tokens for s in ('hind', 'rear', 'back', 'hindleg', 'lh', 'rh')) or 'hind' in compact:
        return 'hind'
    # Common anatomical names when limb type is not explicit.
    if any(s in tokens for s in ('shoulder', 'elbow', 'carpus', 'wrist', 'forearm')):
        return 'front'
    if any(s in tokens for s in ('stifle', 'hock', 'thigh', 'femur', 'tarsus')):
        return 'hind'
    return None


_ALIAS = {
    'root': ('root', 'motionroot', 'reference'),
    'pelvis': ('pelvis', 'hips', 'hiproot'),
    'spine1': ('spine1', 'spine', 'back', 'lumbar'),
    'chest': ('chest', 'thorax', 'spine2', 'upperback', 'ribcage'),
    'neck1': ('neck1', 'neck', 'cervical'),
    'neck2': ('neck2', 'neckend', 'upperneck'),
    'head': ('head', 'skull'),
    'nose': ('nose', 'snout', 'muzzle'),
    'tail1': ('tail1', 'tailbase', 'tail'),
    'tail2': ('tail2', 'tailmid'),
    'tail3': ('tail3', 'tailtip'),
    'hip': ('shoulder', 'scapula', 'upperarm', 'thigh', 'femur', 'hip', 'upperleg'),
    'knee': ('elbow', 'knee', 'stifle', 'lowerarm', 'lowerleg'),
    'ankle': ('ankle', 'wrist', 'carpus', 'hock', 'tarsus', 'cannon'),
    'paw': ('paw', 'foot', 'hoof', 'metacarpal', 'metatarsal', 'fetlock'),
    'toe': ('toe', 'toes', 'tip', 'hoofend', 'digit')
}


def _name_score(role, name):
    toks = _tokens(name)
    compact = ''.join(toks)
    if not compact:
        return -999
    if compact == role.lower().replace('_', ''):
        return 100
    if role in BODY_PARENT:
        if _side_type(toks, compact):
            return -999
        aliases = _ALIAS[role]
        match = max((len(a) for a in aliases if a in compact), default=0)
        if not match:
            return -999
        if role == 'neck1' and ('neck2' in compact or 'neckend' in compact):
            return -999
        if role == 'tail1' and any(s in compact for s in ('tail2', 'tail3', 'tailtip')):
            return -999
        return 30 + match
    side, limb, seg = role.split('_')
    if _side_type(toks, compact) != side:
        return -999
    kind = _limb_type(toks, compact)
    if kind and kind != limb:
        return -999
    aliases = _ALIAS[seg]
    match = max((len(a) for a in aliases if a in compact), default=0)
    if not match:
        return -999
    if seg == 'hip' and 'hip' in compact and limb == 'front':
        return -999
    score = 28 + match + (18 if kind == limb else 0)
    return score


def auto_map_source(source_root):
    source_root = (cmds.ls(_find_joint_root(source_root), l=True) or [source_root])[0]
    joints = _source_joints(source_root)
    unused = set(joints)
    result = {'root': source_root}
    unused.discard(source_root)
    for role in ANIM_ROLES[1:]:
        ranked = sorted(((_name_score(role, j), j) for j in unused),
                        key=lambda p: (-p[0], p[1]))
        if ranked and ranked[0][0] > 0:
            result[role] = ranked[0][1]
            unused.discard(ranked[0][1])
    return result


def _world_quat(node):
    mat = om.MMatrix(cmds.xform(node, q=True, ws=True, m=True))
    return om.MTransformationMatrix(mat).rotation(asQuaternion=True)


def _align_yaw(src_p, src_c, tgt_p, tgt_c):
    sf = _vec(src_c, src_p)
    tf = _vec(tgt_c, tgt_p)
    if math.hypot(sf[0], sf[2]) < 1e-5 or math.hypot(tf[0], tf[2]) < 1e-5:
        return 0.0
    return math.atan2(sf[2], sf[0]) - math.atan2(tf[2], tf[0])


def _yaw_displacement(v, theta):
    sn, cs = math.sin(theta), math.cos(theta)
    return [cs*v[0] + sn*v[2], v[1], -sn*v[0] + cs*v[2]]


def _target_ctrl(tag, role):
    if role in BODY_PARENT:
        return _n(tag, 'CTRL_'+role)
    return _n(tag, 'CTRL_'+role+'_FK')


def transfer_animation(tag, mapping, start, end, rest_frame=None,
                       scale_factor=1.0, align_heading=True, every=1):
    """Bake world-space source rotation *deltas* to target FK controls.

    Source data are sampled at every chosen frame. Rotation deltas are
    quaternion-based; this is a generic retargeter, NOT MotionMaker's HIK.
    Target leg IK/FK attributes are set to FK=0 for the sampled span.
    """
    rig = _n(tag, 'RIG')
    if not cmds.objExists(rig):
        raise RuntimeError('No rig for tag: ' + tag)
    start, end, every = int(start), int(end), int(every)
    rest_frame = int(start if rest_frame is None else rest_frame)
    if start > end or every < 1 or (end - start) > 3000:
        raise ValueError('Invalid range, step, or range over 3000 frames.')
    if not 0.01 <= float(scale_factor) <= 100.0:
        raise ValueError('Translation scale must be between 0.01 and 100.')
    mapped = {role: node for role, node in mapping.items()
              if role in ANIM_ROLES and isinstance(node, str) and cmds.objExists(node)
              and cmds.nodeType(node) == 'joint' and _target_ctrl(tag, role)}
    if 'root' not in mapped or len(mapped) < 8:
        raise ValueError('Map a source root and at least 7 other source joints.')
    normalized = {r: (cmds.ls(n, l=True) or [n])[0] for r, n in mapped.items()}
    if len(set(normalized.values())) != len(normalized):
        raise ValueError('A source joint has been assigned to multiple roles.')
    # Check target contamination before validating the source hierarchy.
    # Otherwise a stale mixed map produces a cryptic hierarchy error.
    conflicts = _mapping_target_conflicts(tag, normalized)
    if conflicts:
        details = '\n'.join('%s -> %s' % (role, joint)
                            for role, joint in conflicts[:8])
        raise ValueError(
            'Source mapping contains joints from YOUR QQR target rig.\n'
            'Select the MotionMaker skeleton (moma:pelvis), press Use selected,\n'
            'then press 05-A Auto-map Source Joints again.\n'
            'Incorrect mappings:\n' + details)
    src_set = set(_source_joints(normalized['root']))
    if any(node not in src_set for node in normalized.values()):
        raise ValueError('Mapped joints must belong to the mapped source ROOT hierarchy.')
    mapped = normalized
    target = {role: _target_ctrl(tag, role) for role in mapped}
    if not all(cmds.objExists(n) for n in target.values()):
        raise RuntimeError('One or more target FK controls do not exist.')
    steps = list(range(start, end+1, every))
    if steps[-1] != end:
        steps.append(end)
    settings = _n(tag, 'CTRL_settings')
    original_time = cmds.currentTime(q=True)
    was_autokey = cmds.autoKeyframe(q=True, state=True)
    cmds.autoKeyframe(state=False)
    cmds.undoInfo(openChunk=True, chunkName='QQR Retarget Animation')
    progress_started = False
    failed = False
    try:
        cmds.currentTime(rest_frame, e=True)
        s_rest = {role: _world_quat(node) for role, node in mapped.items()}
        t_rest = {role: _world_quat(node) for role, node in target.items()}
        s_root_pos = _at(mapped['root'])
        t_root_pos = _at(target['root'])
        theta = 0.0
        if align_heading and all(role in mapped for role in ('pelvis', 'chest')):
            theta = _align_yaw(_at(mapped['pelvis']), _at(mapped['chest']),
                               _at(_n(tag, 'J_pelvis')), _at(_n(tag, 'J_chest')))
        q_yaw = om.MQuaternion(0.0, math.sin(theta*.5), 0.0, math.cos(theta*.5))
        q_yaw_inv = q_yaw.inverse()
        # Remove only the keyed channels in the selected range. External
        # user animation OUTSIDE the selected range is retained.
        for c in target.values():
            cmds.cutKey(c, time=(start, end), at='rotate', option='keys')
        cmds.cutKey(target['root'], time=(start, end), at='translate', option='keys')
        for side in SIDES:
            for limb in LIMBS:
                sw = _switch_attr(side, limb)
                cmds.cutKey(settings, time=(start, end), at=sw, option='keys')
                cmds.setAttr(settings+'.'+sw, 0.0)
                cmds.setKeyframe(settings, at=sw, t=start, v=0.0)
                cmds.setKeyframe(settings, at=sw, t=end, v=0.0)
        cmds.progressWindow(title='QQR - Baking retarget', progress=0,
                            maxValue=len(steps), status='Sampling animation...',
                            isInterruptable=True)
        progress_started = True
        for index, frame in enumerate(steps):
            if cmds.progressWindow(q=True, isCancelled=True):
                raise RuntimeError('Retarget cancelled. Changes undone.')
            cmds.currentTime(frame, e=True)
            # Cache source poses BEFORE editing target controls.
            poses = {r: _world_quat(node) for r, node in mapped.items()}
            displacement = _vec(_at(mapped['root']), s_root_pos)
            displacement = _scale(_yaw_displacement(displacement, theta), float(scale_factor))
            _setpos(target['root'], _vadd(t_root_pos, displacement))
            cmds.setKeyframe(target['root'], at='translate', t=frame)
            for role in ANIM_ROLES:
                if role not in mapped:
                    continue
                delta = poses[role] * s_rest[role].inverse()
                delta = q_yaw * delta * q_yaw_inv
                q_target = delta * t_rest[role]
                euler = q_target.asEulerRotation()
                c = target[role]
                cmds.xform(c, ws=True, ro=[math.degrees(euler.x),
                                           math.degrees(euler.y),
                                           math.degrees(euler.z)])
                cmds.setKeyframe(c, at='rotate', t=frame)
            cmds.progressWindow(e=True, progress=index+1)
        return len(steps), len(mapped)
    except Exception:
        failed = True
        raise
    finally:
        if progress_started:
            cmds.progressWindow(endProgress=True)
        cmds.currentTime(original_time, e=True)
        cmds.autoKeyframe(state=was_autokey)
        cmds.undoInfo(closeChunk=True)
        if failed:
            # Roll back ONLY this attempted transfer, not the user's prior work.
            cmds.undo()


# -------------------------- Guide names -----------------------------
# Exact Maya names are generated by _n(tag, 'G_' + role). Keep anatomical
# terms (such as hoof) descriptive only; do not silently rename 'paw'.
BODY_GUIDE_JA = {
    'root': '全体移動の基準 / 地面の原点',
    'pelvis': '骨盤 / 腰の中心',
    'spine1': '背骨の中間',
    'chest': '胸郭の中心',
    'neck1': '首の付け根',
    'neck2': '首の中間',
    'head': '頭の中心',
    'nose': '鼻先',
    'tail1': '尻尾の付け根',
    'tail2': '尻尾の中間',
    'tail3': '尻尾の先',
}
LEG_GUIDE_JA = {
    'front': {
        'hip': '肩 / 前脚の付け根',
        'knee': '肘（前脚の中間関節）',
        'ankle': '手根 / 前手首',
        'paw': '前足先',
        'toe': '前つま先',
    },
    'hind': {
        'hip': '股関節 / 後脚の付け根',
        'knee': '膝（stifle）',
        'ankle': '飛節 / 後足首（hock）',
        'paw': '後足先',
        'toe': '後つま先',
    }
}


def guide_description_ja(role, preset='Horse'):
    if role in BODY_GUIDE_JA:
        return BODY_GUIDE_JA[role]
    side, limb, seg = role.split('_')
    prefix = '左' if side == 'L' else '右'
    anatomical = LEG_GUIDE_JA[limb][seg]
    if seg == 'paw' and preset == 'Horse':
        anatomical = '前蹄（hoof）' if limb == 'front' else '後蹄（hoof）'
    if seg == 'toe' and preset == 'Horse':
        anatomical = '前蹄先端' if limb == 'front' else '後蹄先端'
    return prefix + anatomical


def guide_manifest(tag='Animal', preset='Horse'):
    """One authoritative manifest shared by UI help and image generation."""
    if preset not in PRESETS:
        raise ValueError('Unknown preset: ' + str(preset))
    return [{'role': role, 'maya_name': _n(tag, 'G_' + role),
             'description_ja': guide_description_ja(role, preset),
             'position': list(_guide_positions(preset)[role])}
            for role in ANIM_ROLES]


# ------------------------------- UI ---------------------------------

def _tag_from_ui():
    return cmds.textFieldGrp(_UI['tag'], q=True, text=True).strip()


def _preset_from_ui():
    return cmds.optionMenuGrp(_UI['preset'], q=True, v=True)


def _ui_action(fn, *args, **kwargs):
    """Maya Undo chunk around one creation/modification action."""
    opened, failed = False, False
    try:
        cmds.undoInfo(openChunk=True, chunkName='QQR '+fn.__name__)
        opened = True
        out = fn(*args, **kwargs)
        cmds.inViewMessage(amg='QQR: %s complete' % fn.__name__,
                           pos='midCenter', fade=True)
        return out
    except Exception as exc:
        failed = True
        cmds.warning('QQR: %s' % exc)
        traceback.print_exc()
        cmds.confirmDialog(title='Quadruped Quick Rig', message=str(exc),
                           button=['OK'], defaultButton='OK')
        return None
    finally:
        if opened:
            cmds.undoInfo(closeChunk=True)
            if failed:
                try:
                    cmds.undo()
                except Exception:
                    cmds.warning('QQR: Undo failed. Check the scene before retrying.')


def _ui_guides(*unused):
    return _ui_action(create_guides, _tag_from_ui(), _preset_from_ui())


def _ui_select_guides(*unused):
    name = _n(_tag_from_ui(), 'GUIDES')
    if not cmds.objExists(name):
        cmds.warning('Please create guides first.')
        return
    cmds.select(name, r=True)


def _ui_mirror(*unused):
    return _ui_action(mirror_left_to_right, _tag_from_ui())


def _ui_build(*unused):
    return _ui_action(build_rig, _tag_from_ui())


def _ui_bind(*unused):
    return _ui_action(bind_selected_meshes, _tag_from_ui())


def _ui_validate(*unused):
    issues = validate_rig(_tag_from_ui())
    message = ('構造チェックは合格です（IK・モーションの動作保証ではありません）。'
               if not issues else '\n'.join(issues[:20]))
    cmds.confirmDialog(title='QQR リグ構造チェック', message=message,
                       button=['OK'])


def _ui_guide_names(*unused):
    tag, preset = _tag_from_ui(), _preset_from_ui()
    try:
        manifest = guide_manifest(tag, preset)
    except Exception as exc:
        cmds.warning(str(exc))
        return
    name = 'QQR2027_v24_GUIDE_HELP'
    if cmds.window(name, exists=True):
        cmds.deleteUI(name)
    win = cmds.window(name, title='QQR ガイド名一覧（Mayaの実名）',
                      widthHeight=(620, 650), sizeable=True)
    cmds.columnLayout(adj=True, rowSpacing=6)
    cmds.text(l='Root は原点。+Z = 正面、+Y = 上、+X = キャラクター左。',
              align='left')
    cmds.text(l='Horse の蹄も内部名は paw です。画像では実際の名前を使用します。',
              align='left')
    lines = ['Maya guide name                        目安の部位', '-'*74]
    lines.extend('%-38s  %s' % (entry['maya_name'], entry['description_ja'])
                 for entry in manifest)
    cmds.scrollField(text='\n'.join(lines), editable=False, wordWrap=False,
                     font='fixedWidthFont', height=550)
    cmds.button(l='閉じる', h=32, c=lambda *_: cmds.deleteUI(win))
    cmds.showWindow(win)


def _ui_match(*unused):
    tag = _tag_from_ui()
    side = cmds.optionMenuGrp(_UI['side'], q=True, v=True)
    limb = cmds.optionMenuGrp(_UI['limb'], q=True, v=True)
    key = cmds.checkBox(_UI['keyMatch'], q=True, v=True)
    return _ui_action(match_and_switch, tag, side, limb, key)


def _ui_clear_mapping():
    """Invalidates mapping whenever source skeleton selection changes."""
    for field in _UI.get('mapFields', {}).values():
        cmds.textField(field, e=True, text='')
    if _UI.get('status'):
        cmds.text(_UI['status'], e=True,
                  l='転送元を選択しました。次に05-A Auto-mapを実行してください。')


def _ui_source_select(*unused):
    chosen = cmds.ls(sl=True, l=True) or []
    if not chosen:
        cmds.warning('Select the animated MotionMaker SOURCE skeleton root.')
        return
    try:
        tag = _tag_from_ui()
        src = _find_joint_root(chosen[0])
        if _is_target_member(tag, src):
            raise ValueError(
                'You selected a QQR TARGET joint, not MotionMaker. '
                'Select moma:pelvis under moma:equine instead.')
        cmds.textFieldButtonGrp(_UI['source'], e=True, text=src)
        _ui_clear_mapping()  # Never silently retain mappings to an old source.
    except Exception as exc:
        cmds.warning('QQR: ' + str(exc))


def _ui_assign(role):
    chosen = cmds.ls(sl=True, l=True, type='joint') or []
    if len(chosen) != 1:
        cmds.warning('Select exactly one SOURCE joint for ' + role)
        return
    cmds.textField(_UI['mapFields'][role], e=True, text=chosen[0])


def _ui_scan(*unused):
    src = cmds.textFieldButtonGrp(_UI['source'], q=True, text=True).strip()
    try:
        tag = _tag_from_ui()
        src = _find_joint_root(src)
        if _is_target_member(tag, src):
            raise ValueError('Source is a QQR TARGET joint. '
                             'Choose the MotionMaker moma:pelvis joint.')
        # Always clear stale fields before re-mapping, including on failure.
        _ui_clear_mapping()
        mapping = auto_map_source(src)
        conflicts = _mapping_target_conflicts(tag, mapping)
        if conflicts:
            raise ValueError('Auto-map unexpectedly included target joints: '
                             + ', '.join(role for role, _ in conflicts))
        for role, field in _UI['mapFields'].items():
            cmds.textField(field, e=True, text=mapping.get(role, ''))
        cmds.textFieldButtonGrp(_UI['source'], e=True, text=src)
        cmds.text(_UI['status'], e=True,
                  l='自動候補: %d / %d。転送元: %s。必ず対応を確認。' %
                    (len(mapping), len(ANIM_ROLES), src.split('|')[-1]))
    except Exception as exc:
        _ui_clear_mapping()
        cmds.warning('QQR: %s' % exc)


def _ui_bake(*unused):
    tag = _tag_from_ui()
    mapping = {role: cmds.textField(f, q=True, text=True).strip()
               for role, f in _UI['mapFields'].items()
               if cmds.textField(f, q=True, text=True).strip()}
    start = cmds.intFieldGrp(_UI['start'], q=True, value1=True)
    end = cmds.intFieldGrp(_UI['end'], q=True, value1=True)
    rest = cmds.intFieldGrp(_UI['rest'], q=True, value1=True)
    scale = cmds.floatFieldGrp(_UI['scale'], q=True, value1=True)
    every = cmds.intFieldGrp(_UI['every'], q=True, value1=True)
    heading = cmds.checkBox(_UI['heading'], q=True, v=True)
    try:
        selected_source = cmds.textFieldButtonGrp(_UI['source'], q=True,
                                                   text=True).strip()
        if not selected_source or not cmds.objExists(selected_source):
            raise ValueError('No valid MotionMaker source selected. '
                             'Use selected, then 05-A Auto-map.')
        root = _find_joint_root(selected_source)
        if not _same_dag_node(mapping.get('root'), root):
            raise ValueError(
                'Source root and mapping root differ (stale mapping).\n'
                'Press Use selected, then 05-A Auto-map Source Joints again.\n'
                'Source field: %s\nMapped root: %s' %
                (root, mapping.get('root', '(none)')))
        conflicts = _mapping_target_conflicts(tag, mapping)
        if conflicts:
            details = '\n'.join('%s -> %s' % (r, j)
                                for r, j in conflicts[:6])
            raise ValueError(
                'Mappings contain your own QQR target rig joints.\n'
                'Press 05-A Auto-map for the MotionMaker horse.\n' + details)
        if len(mapping) < 8:
            raise ValueError('Need root and at least 7 other mapped joints.')
        response = cmds.confirmDialog(
            title='試験的モーション転送 / Experimental',
            message=('対象 %s、%d 関節、%d～%d F にBakeしますか？\n'
                     '対象FKコントローラーの同区間のキーを置換します。\n'
                     'HumanIKではなく接地補正もありません。\n'
                     '必ずシーンを複製してからお試しください。' %
                     (tag, len(mapping), start, end)),
            button=['Bake', 'Cancel'], defaultButton='Cancel',
            cancelButton='Cancel', dismissString='Cancel')
        if response != 'Bake':
            return
        frames, roles = transfer_animation(tag, mapping, start, end, rest,
                                           scale, heading, every)
        cmds.text(_UI['status'], e=True,
                  l='Bake完了: %d フレーム / %d 関節。接地・方向を確認してください。' %
                    (frames, roles))
    except Exception as exc:
        cmds.warning('QQR: %s' % exc)
        traceback.print_exc()
        cmds.confirmDialog(title='QQR Transfer Error', message=str(exc),
                           button=['OK'])


def _ui_playback(*unused):
    low = int(cmds.playbackOptions(q=True, minTime=True))
    high = int(cmds.playbackOptions(q=True, maxTime=True))
    cmds.intFieldGrp(_UI['start'], e=True, value1=low)
    cmds.intFieldGrp(_UI['end'], e=True, value1=high)
    cmds.intFieldGrp(_UI['rest'], e=True, value1=low)


def _ui_step(number, title, note):
    """One full-width sequential frame; matching 'setParent' close below."""
    cmds.frameLayout(label='%s   %s' % (number, title), collapsable=True,
                     collapse=False, borderStyle='etchedIn',
                     marginWidth=10, marginHeight=8)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=6)
    if note:
        cmds.text(l=note, align='left', wordWrap=True)


def _ui_end_step():
    cmds.setParent('..')  # step columnLayout
    cmds.setParent('..')  # frameLayout


def show_ui():
    """Quick Rig-style workflow. All numbered actions run top to bottom."""
    _UI.clear()
    if cmds.window(WIN, exists=True):
        cmds.deleteUI(WIN)
    win = cmds.window(WIN, title='Quadruped Quick Rig v2.4 | Maya 2027',
                      widthHeight=(610, 830), sizeable=True)
    cmds.scrollLayout(childResizable=True)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=9)
    cmds.rowLayout(numberOfColumns=2, adjustableColumn=1, columnWidth2=(490, 80))
    cmds.text(l='QUADRUPED QUICK RIG v2.4', fn='boldLabelFont', align='left', h=25)
    cmds.button(l='Help', annotation='日本語マニュアルを開く', c=lambda *_: webbrowser.open('https://github.com/nmasaaki-web/nTools/blob/main/docs/tools/quadruped.md'))
    cmds.setParent('..')
    cmds.text(l='Y-up  /  +Z forward  /  +X = character left', align='left')
    cmds.text(l='新規キャラクター用 | 上から順番に操作してください。', align='left')

    # STEP 1 - Create guides, no adjacent build button.
    _ui_step('01', '動物を選択してガイドを作成',
             '同じ Character tag ではガイド／リグを重複生成しません。')
    _UI['tag'] = cmds.textFieldGrp(l='Character tag', text='Animal',
                                   adjustableColumn=2, columnWidth2=(125, 370))
    _UI['preset'] = cmds.optionMenuGrp(l='Animal preset',
                                       columnWidth2=(125, 180))
    for name in ('Horse', 'Dog', 'Wolf', 'Cat'):
        cmds.menuItem(l=name)
    cmds.button(l='01   Create Guides  /  ガイド作成', h=42, c=_ui_guides)
    _ui_end_step()

    # STEP 2 - Manual fitting is essential and happens before rig creation.
    _ui_step('02', 'ガイド位置をモデルに合わせる',
             'ガイド31個を移動してください。Root は原点(0,0,0)、'
             'Pelvis は骨盤内側。左側（L）の脚を調整したら左右反転できます。')
    cmds.button(l='ガイドグループを選択', h=30, c=_ui_select_guides)
    cmds.button(l='Mirror L → R  /  左脚を右脚へミラー', h=34, c=_ui_mirror)
    cmds.button(l='ガイド31個の正式名と配置説明を表示', h=32, c=_ui_guide_names)
    _ui_end_step()

    # STEP 3 - Create full rig.
    _ui_step('03', 'リグを生成',
             'ガイド調整を完了してから実行してください。')
    cmds.button(l='03   Build Rig  /  リグ生成', h=42, c=_ui_build)
    cmds.button(l='リグ構造のチェック（簡易）', h=30, c=_ui_validate)
    _ui_end_step()

    # STEP 4 - Bind skin.
    _ui_step('04', 'メッシュをスキニング',
             'スキニングするポリゴンメッシュを選択し、下のボタンを押します。')
    cmds.button(l='04   Bind Selected Meshes  /  スキニング', h=42,
                c=_ui_bind)
    _ui_end_step()

    # STEP 5 - MotionMaker transfer (experimental, not HumanIK).
    _ui_step('05', 'MotionMaker アニメーションを転送（試験機能）',
             'Equineは馬、Canineは犬・狼に推奨。猫は調整が必要。'
             'MotionMakerのpelvisジョイントを選択 → Use selected → 05-A Auto-map → 対応表確認 → Bake。')
    _UI['source'] = cmds.textFieldButtonGrp(l='Source root joint',
                buttonLabel='Use selected', bc=_ui_source_select,
                adjustableColumn=2, columnWidth3=(125, 335, 100))
    cmds.button(l='05-A   Auto-map Source Joints  /  対応名を推定',
                h=37, c=_ui_scan)
    _UI['status'] = cmds.text(l='転送元を変更すると古い対応表を消去します。05-Aで再マッピング。',
                              align='left')
    cmds.frameLayout(l='Source Joint Mapping（展開して確認・修正）',
                     collapsable=True, collapse=True, marginWidth=5,
                     marginHeight=6)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=3)
    _UI['mapFields'] = {}
    for role in ANIM_ROLES:
        cmds.rowLayout(numberOfColumns=3, adjustableColumn=2,
                       columnWidth3=(138, 325, 76))
        cmds.text(l=role, align='left')
        _UI['mapFields'][role] = cmds.textField(text='')
        cmds.button(l='Assign', c=lambda *_, k=role: _ui_assign(k))
        cmds.setParent('..')
    cmds.setParent('..')
    cmds.setParent('..')
    cmds.text(l='転送するフレーム範囲と補正設定', align='left', fn='boldLabelFont')
    _UI['start'] = cmds.intFieldGrp(l='Start frame', nf=1, v1=1,
                                    columnWidth2=(145, 95))
    _UI['end'] = cmds.intFieldGrp(l='End frame', nf=1, v1=120,
                                  columnWidth2=(145, 95))
    _UI['rest'] = cmds.intFieldGrp(l='Reference frame', nf=1, v1=1,
                                   columnWidth2=(145, 95))
    cmds.button(l='再生範囲を入力欄に反映', h=28, c=_ui_playback)
    _UI['every'] = cmds.intFieldGrp(l='Frame step', nf=1, v1=1,
                                    columnWidth2=(145, 95))
    _UI['scale'] = cmds.floatFieldGrp(l='Root motion scale', nf=1,
                                      v1=1.0, pre=3,
                                      columnWidth2=(145, 95))
    _UI['heading'] = cmds.checkBox(l='キャラクターの向き(+Z)を合わせる', v=True)
    cmds.button(l='05-B   Bake Motion to FK  /  転送・Bake（試験）',
                h=42, c=_ui_bake)
    cmds.text(l='※ HumanIK定義や自動足滑り補正ではありません。シーン複製で検証してください。',
              align='left', wordWrap=True)
    _ui_end_step()

    # Unnumbered utility tools AFTER core sequence.
    cmds.frameLayout(l='補助機能：脚の IK / FK ポーズ合わせ',
                     collapsable=True, collapse=True, marginWidth=10,
                     marginHeight=8)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=6)
    _UI['side'] = cmds.optionMenuGrp(l='Side', columnWidth2=(125, 110))
    for side in SIDES:
        cmds.menuItem(l=side)
    _UI['limb'] = cmds.optionMenuGrp(l='Leg', columnWidth2=(125, 110))
    for limb in LIMBS:
        cmds.menuItem(l=limb)
    _UI['keyMatch'] = cmds.checkBox(l='キーを現在フレームに打つ', v=False)
    cmds.button(l='Match + Switch IK/FK', h=34, c=_ui_match)
    cmds.setParent('..')
    cmds.setParent('..')

    cmds.text(l='注意：MotionMaker/HumanIKの正式キャラクター定義は未実装。',
              align='left')
    cmds.setParent('..')  # main column
    cmds.showWindow(win)
    return win


show_ui()
