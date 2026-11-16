# -*- coding: utf-8 -*-
"""Run INSIDE Maya Python. Uses the user's acquired Megascans texture set.
No asset download, no scene reset, no save, no replacement of existing objects.
"""
import sys
from pathlib import Path
import maya.cmds as cmds


def run():
    if cmds.confirmDialog(title='Megascans demo', message='保存済みのテストシーンで実行してください。File > Set Projectを確認しましたか？\n新しい球とOpenPBRを作成し、テクスチャをプロジェクトへコピーします。既存オブジェクトは変更しません。', button=['Continue','Cancel'], defaultButton='Cancel', cancelButton='Cancel', dismissString='Cancel') != 'Continue':
        return
    p=cmds.internalVar(userScriptDir=True)
    if p not in sys.path: sys.path.insert(0,p)
    from ntools.tools import material_creator as mc
    mode=cmds.confirmDialog(title='Megascans source', message='取得済みのMegascans Stone Surfaceのフォルダ、または対応するJSONを指定してください。', button=['Texture Folder','JSON File','Cancel'], defaultButton='Texture Folder', cancelButton='Cancel', dismissString='Cancel')
    if mode=='Cancel': return
    json_mode=mode=='JSON File'
    paths=cmds.fileDialog2(fileMode=1 if json_mode else 3, caption='Select acquired Megascans asset', **({'fileFilter':'JSON (*.json)'} if json_mode else {})) or []
    if not paths: return
    a=mc.load_megascans_input(paths[0],json_mode)
    keys=sorted(k for k,roles in a.textures.items() if roles.get('base'))
    if len(keys)>1:
        # Use the full UI for ambiguous multi-material source packages.
        cmds.confirmDialog(title='Megascans demo',message='複数のTexture setが検出されました。MATのUIで対象を選択してください。',button=['OK']); mc.show(); return
    key=keys[0]; tier,maps=mc.megascans_maps(a,key,2,None)
    lines=['Asset: '+a.name,'Texture set: '+key,'Tier: '+str(tier)] + [role+': '+str(t.path.name) for role,t in sorted(maps.items())]
    if not maps.get('base'): raise ValueError('Base Color not found.')
    print('\n'.join(lines))
    if cmds.confirmDialog(title='Verify detected maps',message='\n'.join(lines)+'\n\nこの素材でテスト球を作成しますか？',button=['Create','Cancel'],defaultButton='Cancel',cancelButton='Cancel',dismissString='Cancel')!='Create':return
    sphere=cmds.polySphere(name='nTools_Megascans_Demo#',radius=1,subdivisionsX=48,subdivisionsY=32)[0]
    cmds.select(sphere,replace=True)
    settings=dict(resolution=2,normal='Auto (file name)',assign=True,copy=True,displacement=False,height=0.2,mid=0.5,subdiv=2)
    mat=mc.create_megascans_material(a,key,settings,tier,print)
    print('Megascans demo finished:',sphere,mat['mat'])
    cmds.confirmDialog(title='Megascans demo',message='作成した球：'+sphere+'\nマテリアル：'+mat['mat']+'\nHypershadeで接続を確認し、Arnoldで照明を用意してレンダーしてください。',button=['OK'])
    return sphere,mat

if __name__=='__main__': run()
