"""Headless safety checks for Sketchfab Set Project confirmation."""
import ast
from pathlib import Path
import types
import unittest

SRC=Path(__file__).resolve().parents[1]/'scripts/ntools/tools/sketchfab_asset_browser.py'
TREE=ast.parse(SRC.read_text('utf-8'))


def compile_one(name, in_class=False):
    seq=TREE.body
    if in_class:
        seq=next(x for x in TREE.body if isinstance(x,ast.ClassDef) and x.name=='Browser').body
    node=next(x for x in seq if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) and x.name==name)
    if in_class:
        cls=ast.ClassDef(name='Only',bases=[],keywords=[],body=[node],decorator_list=[])
        return compile(ast.fix_missing_locations(ast.Module(body=[cls],type_ignores=[])),str(SRC),'exec')
    return compile(ast.Module(body=[node],type_ignores=[]),str(SRC),'exec')

class Button:
    def __init__(self): self.text=None
    def setText(self,txt): self.text=txt

class Check:
    selected=False
    def __init__(self,*args): self.checked=self.selected
    def isChecked(self):return self.checked

class Box:
    Yes=1; No=2; Question=3
    next_result=Yes
    shown=[]
    def __init__(self,owner): self.owner=owner; self.buttons={self.Yes:Button(), self.No:Button()}; self.check=None; self.shown.append(self)
    def setWindowTitle(self,x): self.title=x
    def setIcon(self,x): pass
    def setText(self,x): self.text=x
    def setInformativeText(self,x): self.detail=x
    def setCheckBox(self,x): self.check=x
    def setStandardButtons(self,x): pass
    def button(self,x): return self.buttons[x]
    def setDefaultButton(self,x): pass
    def setEscapeButton(self,x): pass
    def exec(self): return self.next_result

class SetProjectTests(unittest.TestCase):
    def setUp(self):
        Box.shown=[]; Box.next_result=Box.Yes; Check.selected=False
        self.root=['/maya/projects/A']
        ns={'QtWidgets':types.SimpleNamespace(QMessageBox=Box,QCheckBox=Check), 'workspace_root':lambda: self.root[0]}
        exec(compile_one('confirm_project_copy'),ns)
        self.confirm=ns['confirm_project_copy']; self.owner=types.SimpleNamespace()

    def test_no_is_cancelled_and_no_skip(self):
        Box.next_result=Box.No
        self.assertFalse(self.confirm(self.owner))
        self.assertEqual(len(Box.shown),1)
        self.assertFalse(hasattr(self.owner,'_confirmed_copy_root'))
        self.assertIn('Set Projectはしましたか？',Box.shown[0].text)
        self.assertIn('/maya/projects/A',Box.shown[0].detail)

    def test_confirmation_repeated_when_not_suppressed(self):
        self.assertTrue(self.confirm(self.owner))
        self.assertTrue(self.confirm(self.owner))
        self.assertEqual(len(Box.shown),2)

    def test_suppression_per_project_and_window(self):
        Check.selected=True
        self.assertTrue(self.confirm(self.owner))
        self.assertTrue(self.confirm(self.owner))
        self.assertEqual(len(Box.shown),1)
        self.root[0]='/maya/projects/B'
        self.assertTrue(self.confirm(self.owner))
        self.assertEqual(len(Box.shown),2)
        self.assertIn('/maya/projects/B',Box.shown[1].detail)
        self.assertTrue(self.confirm(types.SimpleNamespace()))
        self.assertEqual(len(Box.shown),3)

    def test_disabled_does_not_open_dialog(self):
        self.assertTrue(self.confirm(self.owner,False))
        self.assertFalse(Box.shown)

    def test_online_decline_no_download_no_files(self):
        calls=[]
        def project(owner): calls.append('project'); return False
        ns={'confirm_project_copy':project,'request':lambda *a,**kw:calls.append('request'),
            'API':'https://api.sketchfab.com/v3/',
            'c':types.SimpleNamespace(confirmDialog=lambda **kw: 'Import'),
            'acquire':lambda *a,**kw:calls.append('acquire'),
            'cache_dir':lambda: calls.append('cache_dir'),
            'Path':Path}
        exec(compile_one('download',in_class=True),ns)
        inst=ns['Only']()
        inst.model=lambda: {'uid':'123','name':'Demo'}
        inst.credit=lambda m:'credit'
        inst.token=types.SimpleNamespace(text=lambda: 'private token')
        inst.status=types.SimpleNamespace(setText=lambda x:calls.append('status'))
        inst.finish=lambda *a:calls.append('finish')
        # license metadata lookup necessarily occurs before showing license dialog
        ns['request']=lambda *args,**kw: {'uid':'123'}
        inst.download()
        self.assertEqual(calls,['project','status'])

    def test_local_decline_does_not_import(self):
        calls=[]
        ns={'c':types.SimpleNamespace(fileDialog2=lambda **kw:['/tmp/model.gltf']),
            'confirm_project_copy':lambda owner:calls.append('project') or False,
            'Path':Path}
        exec(compile_one('import_local',in_class=True),ns)
        inst=ns['Only']()
        inst.status=types.SimpleNamespace(setText=lambda x:calls.append('status'))
        inst.finish=lambda *args:calls.append('finish')
        inst.import_local()
        self.assertEqual(calls,['project','status'])

if __name__=='__main__':unittest.main()
