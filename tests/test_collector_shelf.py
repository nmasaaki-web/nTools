# -*- coding: utf-8 -*-
"""Known shelf migrations: preserve existing controls; insert Collector after RIG."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('nt_installer_collector_test',ROOT/'install.py')
manager=importlib.util.module_from_spec(spec);spec.loader.exec_module(manager)

class Cmds:
    def __init__(self,items):
        self.entries=[];self.n=0
        for item in items:self.add(item)
    def add(self,item):
        self.n+=1
        self.entries.append(('obj'+str(self.n),item))
    def shelfLayout(self,element,**kw):
        if kw.get('exists'):return True
        if kw.get('e'):
            key,position=kw['position']
            old=next((i for i,p in enumerate(self.entries) if p[0]==key),None)
            assert old is not None,key
            val=self.entries.pop(old);self.entries.insert(position-1,val)
            return
        raise AssertionError(kw)
    def shelfButton(self,**kwargs):self.add(kwargs['command'].strip())
    def setParent(self,where=None,**kw):return 'root' if kw.get('q') else None

class ShelfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest=json.loads((ROOT/'version.json').read_text(encoding='utf-8'))
    def signatures(self):
        with mock.patch.object(manager,'_target',return_value=ROOT/'scripts'/'ntools'):
            expected=[manager._tool_button(t)['command'].strip() for t in self.manifest['tools']]
            tail=[manager._SEPARATOR]+[manager._management_button(k)['command'].strip() for k in ('help','uninstall','update')]
        return expected,tail
    def execute(self,items,fail=False):
        fake=Cmds(items)
        def paths(shelf):return [shelf+'|'+name for name,_ in fake.entries]
        def item(path):return next(value for name,value in fake.entries if name==path.rsplit('|',1)[-1])
        saved=[]
        with (mock.patch.object(manager,'_target',return_value=ROOT/'scripts'/'ntools'),
              mock.patch.object(manager,'_maya',return_value=(fake,None)),
              mock.patch.object(manager,'_shelf',return_value='tab|nTools'),
              mock.patch.object(manager,'_ui_snapshot',return_value=('Modeling',)),
              mock.patch.object(manager,'_owned_shelf',return_value=not fail),
              mock.patch.object(manager,'_backup_ui',return_value=Path('/tmp/backup')),
              mock.patch.object(manager,'_button_paths',side_effect=paths),
              mock.patch.object(manager,'_shelf_item',side_effect=item),
              mock.patch.object(manager,'_new_separator',side_effect=lambda shelf:fake.add(manager._SEPARATOR)),
              mock.patch.object(manager,'_save_ntools_shelf',side_effect=lambda:saved.append(True))):
            message=manager._sync_management_buttons(self.manifest)
        return [value for _,value in fake.entries],message,saved
    def test_migrate_five_tools_to_six(self):
        expected,tail=self.signatures()
        migrated,message,saved=self.execute(expected[:5]+tail)
        self.assertEqual(migrated,expected+tail)
        self.assertIn('Data Collector',message)
        self.assertEqual(saved,[True])
    def test_migrate_original_four_tools_to_six(self):
        expected,tail=self.signatures()
        migrated,message,saved=self.execute([expected[i] for i in (0,1,3,4)]+tail[1:])
        self.assertEqual(migrated,expected+tail)
        self.assertEqual(len(saved),1)
    def test_up_to_date_shelf_is_unchanged(self):
        expected,tail=self.signatures()
        migrated,message,saved=self.execute(expected+tail)
        self.assertEqual(migrated,expected+tail)
        self.assertEqual(saved,[])
    def test_unknown_shelf_item_rejected(self):
        expected,tail=self.signatures()
        fake=Cmds(expected[:5]+['cmds.deleteUI("MayaWindow")']+tail)
        with (mock.patch.object(manager,'_target',return_value=ROOT/'scripts'/'ntools'),
              mock.patch.object(manager,'_maya',return_value=(fake,None)),
              mock.patch.object(manager,'_shelf',return_value='tab|nTools'),
              mock.patch.object(manager,'_ui_snapshot',return_value=('Modeling',)),
              mock.patch.object(manager,'_owned_shelf',return_value=False)):
            with self.assertRaisesRegex(RuntimeError,'管理対象外'):
                manager._sync_management_buttons(self.manifest)

if __name__=='__main__':unittest.main()
