# -*- coding: utf-8 -*-
"""Offline conversion tests. Maintainers: python tests/test_sketchfab_specgloss.py
Uses NumPy and Pillow to simulate Maya's bundled NumPy/PySide QImage APIs.
Does not execute Maya, and does not prove rendering parity.
"""
from pathlib import Path
import ast
import json
import math
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np
from PIL import Image as PILImage

SCRIPT = Path(__file__).parents[1] / 'scripts/ntools/tools/sketchfab_asset_browser.py'

class FakeSize:
    def __init__(self, w, h): self._w, self._h = w, h
    def width(self): return self._w
    def height(self): return self._h
    def isValid(self): return self._w > 0 and self._h > 0

class FakeImage:
    Format_RGBA8888 = 'rgba8888'
    def __init__(self, *args, pil=None):
        if pil is not None: self.img = pil.convert('RGBA')
        else:
            data, w, h, stride, _ = args
            assert stride == w*4
            self.img = PILImage.frombytes('RGBA', (w, h), data)
    def isNull(self): return self.img is None
    def width(self): return self.img.width
    def height(self): return self.img.height
    def convertToFormat(self, _): return FakeImage(pil=self.img)
    def sizeInBytes(self): return self.width()*self.height()*4
    def constBits(self): return memoryview(self.img.tobytes())
    def scaled(self, w, h, *args): return FakeImage(pil=self.img.resize((w,h),PILImage.Resampling.BICUBIC))
    def save(self, filename, _): self.img.save(filename,format='PNG'); return True

class FakeReader:
    def __init__(self, filename):
        self.filename = filename
        try:
            with PILImage.open(filename) as f: self.original = FakeSize(*f.size)
        except Exception: self.original = FakeSize(0,0)
        self.scaled_size = None
    def size(self): return self.original
    def setScaledSize(self, size): self.scaled_size = size
    def read(self):
        im=PILImage.open(self.filename).convert('RGBA')
        if self.scaled_size: im=im.resize((self.scaled_size.width(),self.scaled_size.height()),PILImage.Resampling.BICUBIC)
        return FakeImage(pil=im)
    def errorString(self): return ''

class FakeCmds:
    def __init__(self, work): self.work = work; self.serial=0;self.attrs={};self.connections=[]
    def currentUnit(self, **kwargs): return 'cm'
    def workspace(self, **kwargs): return str(self.work)
    def shadingNode(self, nodetype, **kwargs):
        self.serial+=1;return kwargs.get("name",nodetype).replace("#",str(self.serial))
    def sets(self, **kwargs):
        self.serial+=1;return 'SG'+str(self.serial)
    def connectAttr(self, a, b, **kwargs): self.connections.append((a,b))
    def setAttr(self, target, *vals, **kwargs): self.attrs[target] = vals if len(vals)!=1 else vals[0]
    def attributeQuery(self, *args, **kwargs): return True
    def colorManagementPrefs(self, **kwargs): return ['sRGB','Raw']
    def createNode(self, nodetype, **kwargs):
        self.serial+=1;return kwargs.get("name",nodetype).replace("#",str(self.serial))

# Load the actual GLTF class and math functions without importing Maya / PySide.
tree = ast.parse(SCRIPT.read_text(encoding='utf8'))
names = {'_sf_brightness','_sf_convert_factor','_sf_srgb_to_linear','_sf_linear_to_srgb','_sf_convert_array'}
nodes = [n for n in tree.body if (isinstance(n,ast.FunctionDef) and n.name in names) or (isinstance(n,ast.ClassDef) and n.name=='GLTF')]
code = compile(ast.Module(body=nodes,type_ignores=[]),str(SCRIPT),'exec')

class SpecGlossTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.cmds=FakeCmds(self.base)
        self.ns = dict(
            math=math,os=__import__('os'),json=json,hashlib=__import__('hashlib'),
            Path=Path,struct=__import__('struct'),base64=__import__('base64'),
            c=self.cmds,
            QtGui=SimpleNamespace(QImageReader=FakeReader,QImage=FakeImage),
            QtCore=SimpleNamespace(Qt=SimpleNamespace(IgnoreAspectRatio=0,SmoothTransformation=1),QSize=FakeSize),
            cache_dir=lambda:self.base/'sourceimages'/'Sketchfab',
            local=lambda root,uri:(root/uri).resolve(),
            safe=lambda s:s,
            _SPEC_DIELECTRIC=0.04,
        )
        exec(code,self.ns)
    def tearDown(self): self.tmp.cleanup()
    def gltf(self, material, images=None, sampler=None):
        data={
            'asset':{'version':'2.0'},'extensionsRequired':['KHR_materials_pbrSpecularGlossiness'],
            'materials':[material],'meshes':[], 'images':images or [],
            'textures':[{'source':i} for i in range(len(images or []))],
        }
        if sampler is not None: data['samplers']=sampler
        path=self.base/'scene.gltf';path.write_text(json.dumps(data))
        return self.ns['GLTF'](path)

    def test_factors_dieletric(self):
        material={'alphaMode':'BLEND','extensions':{'KHR_materials_pbrSpecularGlossiness':{'diffuseFactor':[0.8,0.4,0.2,0.7],'specularFactor':[.04,.04,.04],'glossinessFactor':.75}}}
        gltf=self.gltf(material)
        gltf.material(0)
        self.assertEqual(gltf.specgloss_count,1)
        color=[v for k,v in self.cmds.attrs.items() if k.endswith('.baseColor')][0]
        self.assertTrue(np.allclose(color,[.8,.4,.2],rtol=.0001))
        self.assertTrue(any(k.endswith('.specularRoughness') and abs(v-.25)<1e-6 for k,v in self.cmds.attrs.items()))
        self.assertTrue(any(k.endswith('.geometryOpacity') and abs(v-.7)<1e-6 for k,v in self.cmds.attrs.items()))

    def test_metal_gold_factors(self):
        f=self.ns['_sf_convert_factor']
        color,metal,rough=f([0,0,0],[1,.766,.336],.9)
        self.assertAlmostEqual(metal,1.,places=5)
        self.assertTrue(np.allclose(color,[1,.766,.336],atol=.003))
        self.assertAlmostEqual(rough,.1)

    def test_textured_alpha_and_glossiness(self):
        PILImage.new('RGBA',(2,2),(128,64,32,128)).save(self.base/'d.png')
        spec=PILImage.new('RGBA',(2,2),(56,56,56,128));spec.putpixel((0,0),(255,200,80,0));spec.save(self.base/'s.png')
        material={'alphaMode':'BLEND','extensions':{'KHR_materials_pbrSpecularGlossiness':{
            'diffuseFactor':[1.,1.,1.,.8], 'diffuseTexture':{'index':0},
            'specularFactor':[1.,1.,1.], 'specularGlossinessTexture':{'index':1}, 'glossinessFactor':.5
        }}}
        gltf=self.gltf(material,[{'uri':'d.png'},{'uri':'s.png'}])
        gltf.material(0)
        self.assertEqual(gltf.specgloss_count,1)
        output=list((self.base/'sourceimages'/'Sketchfab'/'_converted_specgloss').rglob('*.png'))
        self.assertEqual(len(output),2)
        bc=next(p for p in output if 'basecolor' in p.name)
        mr=next(p for p in output if 'metalrough' in p.name)
        alpha=PILImage.open(bc).getpixel((1,1))[3]
        self.assertAlmostEqual(alpha,round(128/255*.8*255),delta=1)
        self.assertEqual(PILImage.open(mr).getpixel((0,0))[1],255) # gloss=0 -> rough=1
        self.assertAlmostEqual(PILImage.open(mr).getpixel((1,1))[1],round(.75*255),delta=1)
        self.assertTrue(any(k.endswith('.fileTextureName') and '_converted_specgloss' in v for k,v in self.cmds.attrs.items()))
        self.assertTrue(any(dst.endswith('.geometryOpacity') for src,dst in self.cmds.connections))
        # Same material reused, not baked a second time.
        previous=len(output)
        self.assertEqual(gltf.material(0),gltf.materials[0])
        self.assertEqual(len(list((self.base/'sourceimages'/'Sketchfab'/'_converted_specgloss').rglob('*.png'))),previous)

    def test_ordinary_metallic_roughness_unchanged(self):
        material={'pbrMetallicRoughness':{
            'baseColorFactor':[.5,.7,.9,1.0], 'metallicFactor':.3,'roughnessFactor':.6}}
        gltf=self.gltf(material)
        gltf.material(0)
        self.assertEqual(gltf.specgloss_count,0)
        self.assertTrue(any(k.endswith('.baseMetalness') and abs(v-.3)<1e-6 for k,v in self.cmds.attrs.items()))
        self.assertTrue(any(k.endswith('.specularRoughness') and abs(v-.6)<1e-6 for k,v in self.cmds.attrs.items()))

    def test_pbr_specgloss_wins_over_mr_fallback(self):
        material={'pbrMetallicRoughness':{'metallicFactor':0.2,'roughnessFactor':0.8},
          'extensions':{'KHR_materials_pbrSpecularGlossiness':{
              'diffuseFactor':[.9,.9,.9,1.],'specularFactor':[.04,.04,.04],
              'glossinessFactor':.75}}}
        gltf=self.gltf(material)
        gltf.material(0)
        self.assertEqual(gltf.specgloss_count,1)
        self.assertTrue(any(k.endswith('.specularRoughness') and abs(v-.25)<1e-6 for k,v in self.cmds.attrs.items()))

    def test_both_factor_and_array_conversion_agree(self):
        convert=self.ns['_sf_convert_factor']
        arr=self.ns['_sf_convert_array']
        d=np.array([[0.6,0.2,0.8]],dtype=np.float32)
        sp=np.array([[0.1,0.2,0.4]],dtype=np.float32)
        gloss=np.array([.65],dtype=np.float32)
        base,metal,rough=arr(d,sp,gloss,np)
        scalar=convert(d[0],sp[0],gloss[0])
        self.assertTrue(np.allclose(base[0],scalar[0],atol=1e-5))
        self.assertAlmostEqual(float(metal[0]),scalar[1],places=5)
        self.assertAlmostEqual(float(rough[0]),scalar[2],places=5)

    def test_required_extension_now_accepted_draco_still_rejected(self):
        material={'extensions':{'KHR_materials_pbrSpecularGlossiness':{}}}
        self.gltf(material)
        obj={'extensionsRequired':['KHR_draco_mesh_compression'],'materials':[material]}
        (self.base/'scene.gltf').write_text(json.dumps(obj))
        with self.assertRaisesRegex(ValueError,'Unsupported required glTF extensions'):
            self.ns['GLTF'](self.base/'scene.gltf')

    def test_uv_transform_fails_safe(self):
        PILImage.new('RGBA',(2,2),(128,128,128,255)).save(self.base/'d.png')
        mat={'extensions':{'KHR_materials_pbrSpecularGlossiness':{'diffuseTexture':{'index':0,'extensions':{'KHR_texture_transform':{'offset':[.5,.5]}}}}}}
        gltf=self.gltf(mat,[{'uri':'d.png'}])
        with self.assertRaisesRegex(ValueError,'KHR_texture_transform'):
            gltf.material(0)

if __name__=='__main__': unittest.main(verbosity=2)
