import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from ntools.tools import standin_look_controller as lc


def test_whitelist_and_attribute_names():
    assert set(lc.CONTROLS)=={'sss_weight','sss_saturation','base_exposure','base_saturation','coat_weight'}
    assert lc.maya_standin_attr('sss_weight')=='mtoa_constant_ntools_sss_weight'
    try:
        lc.maya_standin_attr('unsupported')
        assert False
    except KeyError:
        pass


def test_profile_rejects_unmanaged_standins():
    class Fake:
        def attributeQuery(self,name,node,exists):
            return name in ('ntoolsLookProfile','mtoa_constant_ntools_sss_weight')
        def getAttr(self,plug):
            if plug.endswith('ntoolsLookProfile'):
                return '{"schema": 1, "producer": "unknown", "controls": ["sss_weight"]}'
    with mock.patch.object(lc,'cmds',Fake()):
        assert lc.read_profile('treeShape') is None


def test_apply_all_matching_only_changes_whitelisted_attrs():
    class Fake:
        def __init__(self):
            self.values={}
        def getAttr(self,plug):
            return 'file.ass' if plug.endswith('.dso') else 0
        def ls(self,**kwargs):
            return ['a','b','c']
        def setAttr(self,plug,value):
            self.values[plug]=value
        def undoInfo(self,**kwargs): pass
    fake=Fake()
    with mock.patch.object(lc,'cmds',fake),mock.patch.object(lc,'read_profile',side_effect=lambda s:{'controls':['sss_weight']} if s!='c' else None):
        assert lc.apply_controls(['a'],{'sss_weight':0.3},True)==2
        assert fake.values=={'a.mtoa_constant_ntools_sss_weight':0.3,'b.mtoa_constant_ntools_sss_weight':0.3}


def test_apply_refuses_unsupported_controls_before_mutation():
    class Fake:
        def getAttr(self,plug): return 'file.ass'
        def setAttr(self,*args): raise AssertionError('should not modify anything')
        def undoInfo(self,*args,**kwargs): raise AssertionError('no undo chunk expected')
    with mock.patch.object(lc,'cmds',Fake()),mock.patch.object(lc,'read_profile',return_value={'controls':['base_exposure']}):
        try:
            lc.apply_controls(['tree'],{'sss_weight':0.1},False)
            assert False
        except ValueError:
            pass


def test_scope_does_not_override_arbitrary_channel():
    try:
        lc.apply_controls(['a'],{'geometryOpacity':0.0})
        assert False
    except ValueError:
        pass


def test_profile_data_survives_serialized_scene():
    class Fake:
        def __init__(self): self.attrs={};self.values={};self.names={}
        def nodeType(self,node):return 'aiStandIn'
        def attributeQuery(self,name,node,exists=True):return name in self.attrs.get(node,set())
        def addAttr(self,node,longName,**kwargs):self.attrs.setdefault(node,set()).add(longName)
        def setAttr(self,plug,val,**kwargs):self.values[plug]=val
        def getAttr(self,plug):return self.values[plug]
    fake=Fake()
    with mock.patch.object(lc,'cmds',fake):
        lc.attach_profile('shape1',{'schema':1,'producer':'nTools/PolyHaven','controls':['sss_weight','coat_weight']})
        assert lc.read_profile('shape1')['controls']==['sss_weight','coat_weight']
        assert fake.values['shape1.mtoa_constant_ntools_sss_weight']==0.0


def test_new_version_built_on_exact_baseline():
    src=(Path(__file__).resolve().parents[1]/'tools'/'nonexistent')
    browser=(Path(__file__).resolve().parents[1]/'scripts'/'ntools'/'tools'/'polyhaven_asset_browser.py').read_text(encoding='utf-8')
    assert "export_standin(root,asset,log,settings.get('standin_split','auto'),materials)" in browser
    assert "button(row,'Stand-in Look Controller'" in browser

class FakeShaderGraph:
    def __init__(self):
        self.types={'leaf':'openPBRSurface','rock':'openPBRSurface',
                    'leafDiffuse':'file','rockDiffuse':'file','leafSSS':'aiColorCorrect'}
        self.attrs={
            'leaf':{'baseColor','subsurfaceColor','subsurfaceWeight','coatWeight'},
            'rock':{'baseColor','coatWeight'},
            'leafSSS':{'outColor','saturation'},
            'leafDiffuse':{'outColor'},'rockDiffuse':{'outColor'},
        }
        self.inputs={'leaf.baseColor':'leafDiffuse.outColor',
                     'rock.baseColor':'rockDiffuse.outColor',
                     'leaf.subsurfaceColor':'leafSSS.outColor'}
        self.values={'leaf.coatWeight':0.0,'rock.coatWeight':0.3}
        self.events=[]
        self.count=0
    def objExists(self,n):return n.split('.')[0] in self.types
    def nodeType(self,n):return self.types[n]
    def attributeQuery(self,a,node,exists=True):return a in self.attrs.get(node,set())
    def listConnections(self,p,source=True,destination=False,plugs=True):
        return [self.inputs[p]] if p in self.inputs else []
    def shadingNode(self,kind,asUtility=False,name=None):
        self.count+=1
        n=(name or kind)+str(self.count)
        self.types[n]=kind
        self.attrs[n]={'floatAttrName','defaultValue','outValue'} if kind=='aiUserDataFloat' else {'input','outColor','saturation','exposure'}
        return n
    def setAttr(self,plug,v,**kw):self.values[plug]=v
    def getAttr(self,plug):return self.values.get(plug,0)
    def connectAttr(self,src,dst,force=False):
        if dst in self.inputs and not force: raise RuntimeError('occupied')
        self.inputs[dst]=src
    def disconnectAttr(self,src,dst):
        assert self.inputs[dst]==src
        del self.inputs[dst]
    def delete(self,node):
        self.types.pop(node,None)
        self.inputs={k:v for k,v in self.inputs.items() if not k.startswith(node+'.') and not v.startswith(node+'.')}


def test_prepare_export_preserves_base_textures_and_does_not_touch_existing_coat():
    graph=FakeShaderGraph()
    materials={'leaf':{'mat':'leaf','foliage':True},'rock':{'mat':'rock','foliage':False}}
    with mock.patch.object(lc,'cmds',graph):
        profile=lc.prepare_export_materials(materials,lambda msg:None)
    assert 'sss_weight' in profile['controls']
    assert 'sss_saturation' in profile['controls']
    assert 'base_exposure' in profile['controls']
    assert 'base_saturation' in profile['controls']
    assert 'coat_weight' in profile['controls']  # for leaf with original coat zero
    assert 'rock.coatWeight' not in graph.inputs  # retain author-authored 0.3
    assert 'leaf.subsurfaceWeight' in graph.inputs
    assert 'rock.subsurfaceWeight' not in graph.inputs
    base_nodes=[n for n,t in graph.types.items() if t=='aiColorCorrect' and 'StandInBaseAdjust' in n]
    assert len(base_nodes)==2
    leaf_node=next(n for n in base_nodes if n.startswith('leaf'))
    rock_node=next(n for n in base_nodes if n.startswith('rock'))
    assert graph.inputs[leaf_node+'.input']=='leafDiffuse.outColor'
    assert graph.inputs[rock_node+'.input']=='rockDiffuse.outColor'
    assert graph.inputs['leaf.baseColor']==leaf_node+'.outColor'
    assert graph.inputs['rock.baseColor']==rock_node+'.outColor'


def test_prepare_sss_requires_existing_sss_color_network():
    graph=FakeShaderGraph()
    del graph.inputs['leaf.subsurfaceColor']
    with mock.patch.object(lc,'cmds',graph):
        result=lc.prepare_export_materials({'leaf':{'mat':'leaf','foliage':True}},lambda msg:None)
    assert 'sss_weight' not in result['controls']
    assert 'sss_saturation' not in result['controls']
