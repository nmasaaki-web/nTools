"""nTools v1.0.24: unit tests for conservative leaf SSS; no Maya required."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/ntools/tools/polyhaven_asset_browser.py'
spec = importlib.util.spec_from_file_location('polyhaven_sss_under_test', SOURCE)
ph = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ph)


class FakeMaya:
    def __init__(self):
        self.nodes = {'leaf_OpenPBR': 'openPBRSurface', 'bark_OpenPBR': 'openPBRSurface',
                      'baseFile': 'file', 'existing_OpenPBR': 'openPBRSurface'}
        self.connections = {}
        self.set_events = []
        self.attrs = {
            'leaf_OpenPBR': {'subsurfaceColor', 'subsurfaceWeight', 'baseColor', 'geometryThinWalled'},
            'bark_OpenPBR': {'subsurfaceColor', 'subsurfaceWeight', 'baseColor', 'geometryThinWalled'},
            'existing_OpenPBR': {'subsurfaceColor', 'subsurfaceWeight', 'baseColor', 'geometryThinWalled'},
            'baseFile': {'outColor'},
        }
        self.deleted = []
        self.chunks = 0
        self.gets = {'leaf_OpenPBR.subsurfaceWeight': 0.3, 'existing_OpenPBR.subsurfaceWeight': 0.7}
        self.materials = ['leaf_OpenPBR', 'bark_OpenPBR', 'existing_OpenPBR']
    def objExists(self, thing):
        return thing.split('.')[0] in self.nodes
    def attributeQuery(self, attr_name, node=None, exists=False):
        return attr_name in self.attrs.get(node, set())
    def listConnections(self, plug, source=True, destination=False, plugs=True, **kw):
        return [self.connections[plug]] if plug in self.connections else []
    def pluginInfo(self, *args, **kw): return True
    def loadPlugin(self, *args, **kw): return True
    def shadingNode(self, node_type, asUtility=False, name=None):
        name = name or ('node_%d' % len(self.nodes))
        self.nodes[name] = node_type
        if node_type == 'aiColorCorrect':
            self.attrs[name] = {'input', 'outColor', 'multiply', 'saturation'}
        return name
    def connectAttr(self, src, dest, force=False):
        if not force and dest in self.connections:
            raise ValueError('Already connected')
        self.connections[dest] = src
    def setAttr(self, plug, *values, **kw): self.set_events.append((plug, values, kw))
    def getAttr(self, plug, type=False):
        if type: return 'float3'
        return self.gets.get(plug, 0)
    def delete(self, obj):
        self.deleted.append(obj)
        self.nodes.pop(obj, None)
    def ls(self, type=None):
        return self.materials if type == 'openPBRSurface' else []
    def undoInfo(self, openChunk=False, closeChunk=False, **kw):
        if openChunk: self.chunks += 1
        if closeChunk: self.chunks -= 1


class PlantClassifier(unittest.TestCase):
    def test_foliage_names(self):
        for key in ('oak_leaves', 'grass_cluster', 'fern_a', 'flower_petals', 'plant_leaf', 'needle_02'):
            self.assertTrue(ph.is_plant_sss_target(key,'Plants',False), key)
    def test_woody_and_ground_never(self):
        for key in ('fir_tree_bark','fir_tree_trunk_a','oak_branch','wood_floor', 'stone_leaf_bark'):
            self.assertFalse(ph.is_plant_sss_target(key,'Plants',True), key)
        self.assertFalse(ph.is_plant_sss_target('rock','Surfaces',True))
        self.assertFalse(ph.is_plant_sss_target('wood_atlas','Plants',True))
    def test_twig_and_atlas_restricted(self):
        self.assertTrue(ph.is_plant_sss_target('fir_tree_twig','Plants',True))
        self.assertFalse(ph.is_plant_sss_target('fir_tree_twig','Plants',False))
        self.assertFalse(ph.is_plant_sss_target('twig','Surfaces',True))
        self.assertTrue(ph.is_plant_sss_target('leaf_atlas','Plants',True))


class PlantSssSetup(unittest.TestCase):
    def setUp(self):
        self.fake = FakeMaya()
        self.patcher = patch.object(ph, 'cmds', self.fake)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.logs = []
    def test_new_foliage_adds_editable_network_with_zero_weight(self):
        self.assertTrue(ph.setup_plant_sss_color('leaf_OpenPBR','baseFile.outColor',self.logs.append,True))
        cc = 'leaf_OpenPBR_SSS_ColorAdjust'
        self.assertEqual(self.fake.connections[cc+'.input'],'baseFile.outColor')
        self.assertEqual(self.fake.connections['leaf_OpenPBR.subsurfaceColor'], cc+'.outColor')
        self.assertIn(('leaf_OpenPBR.subsurfaceWeight',(0.0,),{}),self.fake.set_events)
        self.assertIn((cc+'.saturation',(1.0,),{}), self.fake.set_events)
        self.assertIn((cc+'.multiply',(1.0,1.0,1.0),{'type':'float3'}), self.fake.set_events)
        self.assertNotIn('leaf_OpenPBR.geometryThinWalled',[s[0] for s in self.fake.set_events])
    def test_existing_connection_never_overwritten(self):
        self.fake.connections['leaf_OpenPBR.subsurfaceColor']='artistCustom.outColor'
        self.assertFalse(ph.setup_plant_sss_color('leaf_OpenPBR','baseFile.outColor',self.logs.append,True))
        self.assertEqual(self.fake.connections['leaf_OpenPBR.subsurfaceColor'],'artistCustom.outColor')
        self.assertFalse(any(x.endswith('_SSS_ColorAdjust') for x in self.fake.nodes))
    def test_retrofit_preserves_weight_and_thin_walled(self):
        self.fake.connections['leaf_OpenPBR.baseColor']='baseFile.outColor'
        self.fake.connections['bark_OpenPBR.baseColor']='baseFile.outColor'
        n, skipped = ph.add_plant_sss_to_scene_materials(self.logs.append)
        self.assertEqual((n,skipped),(1,0))
        changed=[p for p, _, _ in self.fake.set_events]
        self.assertFalse(any(x.endswith('subsurfaceWeight') or x.endswith('geometryThinWalled') for x in changed))
        self.assertNotIn('bark_OpenPBR.subsurfaceColor',self.fake.connections)
        self.assertEqual(self.fake.chunks,0)
    def test_failure_undoes_only_created_node(self):
        def failed(*args,**kw):
            if args[1].endswith('subsurfaceColor'):
                raise RuntimeError('connection failure')
            self.fake.connections[args[1]]=args[0]
        self.fake.connectAttr=failed
        self.assertFalse(ph.setup_plant_sss_color('leaf_OpenPBR','baseFile.outColor',self.logs.append,True))
        self.assertIn('leaf_OpenPBR_SSS_ColorAdjust',self.fake.deleted)


if __name__ == '__main__': unittest.main()

# Exercise the real build_material decision path with stubbed Maya primitives.
class BuildMaterialIntegration(unittest.TestCase):
    def test_import_builds_sss_for_grass_not_bark(self):
        from types import SimpleNamespace
        from unittest.mock import patch as mkpatch
        class BuildFake(FakeMaya):
            def shadingNode(self,node_type,asShader=False,asUtility=False,name=None):
                result=super().shadingNode(node_type,asUtility=asUtility,name=name)
                if node_type=='openPBRSurface':
                    self.attrs[result]={'baseColor','baseMetalness','geometryThinWalled',
                                        'subsurfaceColor','subsurfaceWeight'}
                return result
            def sets(self, **kw): return 'testShadingEngine'
        f=BuildFake()
        asset=SimpleNamespace(name='Test Plant',category='Plants',folder=Path('/tmp/plant'))
        settings={'resolution':2,'copy':False,'normal':'Auto','displacement':False}
        def fake_maps(asset,key,*args):
            return {'base':SimpleNamespace(path=asset.folder/'textures'/(key+'_diff_2k.png'),res=2,tier=None,lod=None)}
        with mkpatch.object(ph,'cmds',f), mkpatch.object(ph,'texture_set',fake_maps), \
             mkpatch.object(ph,'create_file',lambda *a,**kw:'baseFile'):
            leaf=ph.build_material(asset,'grass',settings,None,None,lambda *_:None)
            bark=ph.build_material(asset,'tree_bark',settings,None,None,lambda *_:None)
            self.assertIn(leaf['mat']+'.subsurfaceColor', f.connections)
            self.assertNotIn(bark['mat']+'.subsurfaceColor', f.connections)
            self.assertEqual(f.connections[leaf['mat']+'.subsurfaceColor'],
                             leaf['mat']+'_SSS_ColorAdjust.outColor')
            self.assertNotIn('bark_OpenPBR.subsurfaceColor',f.connections)
