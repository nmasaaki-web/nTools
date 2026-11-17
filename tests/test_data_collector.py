# -*- coding: utf-8 -*-
"""Maya-independent Data Collector plan, relink, and safety checks."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'scripts/ntools/tools/data_collector.py'
spec=importlib.util.spec_from_file_location('data_collector_test',p)
collector=importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

class FakeCmds:
    def __init__(self,project,scene,files,fail_on=None):
        self.project=project;self.scene=scene;self.files=dict(files);self.fail_on=fail_on;self.modified=False
        self.attrs={**files};self.types={k.split('.')[0]:'file' for k in files}
    def file(self,*args,**kwargs):
        if kwargs.get('q'):
            if kwargs.get('sceneName'):return str(self.scene)
            if kwargs.get('modified'):return self.modified
        if 'loadReference' in kwargs:
            if self.fail_on==kwargs['loadReference']:raise RuntimeError('mock reference failed')
            self.attrs[kwargs['loadReference']]=str(args[0])
            return None
        raise AssertionError(kwargs)
    def workspace(self,**kwargs):return str(self.project)
    def ls(self,**kwargs):
        if kwargs.get('type')=='reference':return []
        if kwargs.get('type')=='cacheFile':return []
        return sorted({key.split('.')[0] for key in self.attrs
                       if self.types.get(key.split('.')[0])==kwargs.get('type')})
    def attributeQuery(self,attr,node=None,exists=None):return node+'.'+attr in self.attrs
    def getAttr(self,plug):
        if plug.endswith(('.uvTilingMode','.useFrameExtension')):return False
        return self.attrs[plug]
    def nodeType(self,node):return self.types[node]
    def referenceQuery(self,node,**kwargs):
        if kwargs.get('isNodeReferenced'):return False
        raise RuntimeError('not referenced')
    def setAttr(self,plug,value,**kwargs):
        if self.fail_on==plug:raise RuntimeError('mock relink failed')
        self.attrs[plug]=value

class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.project=self.base/'project';self.project.mkdir();(self.project/'workspace.mel').write_text('// workspace')
        scene_dir=self.project/'scenes';scene_dir.mkdir()
        self.scene=scene_dir/'animation.ma';self.scene.write_text('original scene')
        self.external=self.base/'external';self.external.mkdir()
    def file(self,name,data=b'img'):
        out=self.external/name;out.write_bytes(data);return out
    def make(self,paths,fail=None):
        fake=FakeCmds(self.project,self.scene,paths,fail_on=fail)
        _,records=collector.scan(fake)
        return fake,records
    def test_inside_uses_real_paths(self):
        self.assertTrue(collector.inside(self.project/'sourceimages/a.png',self.project))
        self.assertFalse(collector.inside(self.base/'project_other/file.png',self.project))
        self.assertFalse(collector.inside(self.project/'../external/a.png',self.project))
    def test_udim_and_frame_patterns(self):
        self.file('rock.1001.exr');self.file('rock.1002.exr')
        match,name,token=collector._expand_files(self.external/'rock.<UDIM>.exr')
        self.assertEqual(len(match),2);self.assertTrue(token)
        self.file('scene_0001.exr');self.file('scene_0002.exr')
        match,_,_=collector._expand_files(self.external/'scene_####.exr')
        self.assertEqual(len(match),2)
    def test_scan_only_external(self):
        src=self.file('external.png')
        inside=self.project/'sourceimages'/'local.png';inside.parent.mkdir();inside.write_bytes(b'local')
        fake,entries=self.make({'fileOutside.fileTextureName':str(src),'fileInside.fileTextureName':str(inside)})
        self.assertEqual(len(entries),1)
        self.assertEqual(entries[0]['label'],'fileOutside')
        self.assertTrue(entries[0]['members'])
    def test_scan_missing_external_shown_but_disabled(self):
        fake,entries=self.make({'fileMissing.fileTextureName':str(self.external/'missing.png')})
        self.assertEqual(len(entries),1)
        self.assertFalse(entries[0]['members'])
        self.assertIn('見つかりません',entries[0]['status'])
    def test_copies_and_relinks_and_backs_up_scene(self):
        src=self.file('rock.png',b'rocktex')
        fake,entries=self.make({'fileA.fileTextureName':str(src)})
        plan,total,size=collector.make_plan(self.project,entries)
        report,backup,num=collector.run_plan(fake,self.project,plan,self.scene)
        self.assertEqual((total,size,num),(1,7,1))
        self.assertFalse(Path(fake.attrs['fileA.fileTextureName']).is_absolute())
        target=self.project/fake.attrs['fileA.fileTextureName']
        self.assertTrue(target.exists());self.assertTrue(collector.inside(target,self.project))
        self.assertEqual(target.read_bytes(),src.read_bytes())
        self.assertEqual(backup.read_text(),'original scene')
        self.assertEqual(json.loads(report.read_text())['result'],'success')
        self.assertEqual(src.read_bytes(),b'rocktex')
    def test_two_nodes_same_texture_reuse_one_copy(self):
        src=self.file('shared.png',b'texture')
        fake,entries=self.make({'f1.fileTextureName':str(src),'f2.fileTextureName':str(src)})
        plan,total,_=collector.make_plan(self.project,entries)
        self.assertEqual(total,1)
        report,backup,num=collector.run_plan(fake,self.project,plan,self.scene)
        self.assertEqual(num,1)
        self.assertEqual(fake.attrs['f1.fileTextureName'],fake.attrs['f2.fileTextureName'])
    def test_preserve_existing_different_name_collision(self):
        src=self.file('same.exr',b'fresh')
        fake,entries=self.make({'f1.fileTextureName':str(src)})
        plan,_,_=collector.make_plan(self.project,entries)
        target=plan[0]['files'][0][1]
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'old')
        plan2,_,_=collector.make_plan(self.project,entries)
        self.assertNotEqual(target,plan2[0]['files'][0][1])
        self.assertEqual(target.read_bytes(),b'old')
    def test_rollback_after_relink_error(self):
        a=self.file('first.png',b'first');b=self.file('second.png',b'second')
        fake,entries=self.make({'a.fileTextureName':str(a),'b.fileTextureName':str(b)},fail='b.fileTextureName')
        plan,_,_=collector.make_plan(self.project,entries)
        with self.assertRaisesRegex(RuntimeError,'mock relink failed'):
            collector.run_plan(fake,self.project,plan,self.scene)
        self.assertEqual(fake.attrs['a.fileTextureName'],str(a))
        self.assertEqual(fake.attrs['b.fileTextureName'],str(b))
        self.assertFalse(any(dst.exists() for row in plan for src,dst in row['files']))
        reports=list((self.project/'data/nToolsCollected/reports').glob('collect_*.json'))
        self.assertEqual(json.loads(reports[0].read_text())['result'],'failed')
    def test_reject_unsaved_scene(self):
        a=self.file('source.png')
        fake,entries=self.make({'a.fileTextureName':str(a)})
        plan,_,_=collector.make_plan(self.project,entries)
        fake.modified=True
        with self.assertRaisesRegex(RuntimeError,'未保存'):
            collector.run_plan(fake,self.project,plan,self.scene)
    def test_cache_group(self):
        folder=self.external/'water_cache';folder.mkdir()
        (folder/'water.xml').write_text('<cache/>')
        (folder/'waterFrame1.mcx').write_bytes(b'cache')
        fake=FakeCmds(self.project,self.scene,{})
        fake.attrs={'cache1.cachePath':str(folder),'cache1.cacheName':'water'}
        entry=collector._cache_entry(fake,self.project,'cache1')
        self.assertEqual(len(entry['members']),2)
        plan,_,_=collector.make_plan(self.project,[entry])
        self.assertEqual(Path(plan[0]['new_path']).name,plan[0]['group'].name)
    def test_reference_detect_top_level(self):
        ref=self.file('rig.ma',b'rig')
        class Ref(FakeCmds):
            def referenceQuery(self,node,**kw):
                if kw.get('filename'):return str(ref)
                if kw.get('parent'):raise RuntimeError('no parent reference')
                if kw.get('isLoaded'):return True
                return False
        fake=Ref(self.project,self.scene,{})
        entry=collector._reference_entry(fake,self.project,'myRigRN')
        self.assertIsNotNone(entry)
        self.assertFalse(entry['readonly'])

if __name__=='__main__':unittest.main()
