import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from engine_converter import convert, inspect


class ConverterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'Original'
        for root in ('Assets/Scenes', 'Assets/Editor', 'Packages', 'ProjectSettings'):
            (self.source / root).mkdir(parents=True)
        self.guid = 'C3IfsC/+B3gWefFU0CWUzZnFGungDCCTnndpn6b4lW/q6+kRP07nFcU='
        self.put('ProjectSettings/ProjectVersion.txt', 'm_EditorVersion: 2022.3.62t7\nm_TuanjieEditorVersion: 1.8.5\n')
        self.put('Packages/manifest.json', json.dumps({'dependencies': {'cn.tuanjie.codely.bridge': '1.0.89', 'com.unity.ugui': '1.0.0'}}))
        self.put('Assets/Scenes/Main.scene', '%YAML 1.1\n%TAG !u! tag:yousandi.cn,2023:\n--- !u!1 &1\nMonoBehaviour:\n  m_Script: {fileID: 11500000, guid: ' + self.guid + ', type: 3}\n')
        self.put('Assets/Scenes/Main.scene.meta', 'fileFormatVersion: 2\nguid: 1234567890abcdef1234567890abcdef\nDefaultImporter:\n')
        self.put('Assets/Editor/Boot.cs.meta', 'fileFormatVersion: 2\nguid: ' + self.guid + '\nMonoImporter:\n')
        self.put('Assets/Editor/Boot.cs', 'class Boot { string p = "Assets/Scenes/Main.scene"; }')
        self.put('ProjectSettings/EditorBuildSettings.asset', 'path: Assets/Scenes/Main.scene\n')
        self.put('Assets/Test.asmdef', '{"references": ["GUID:' + self.guid + '"]}')
        self.put('Assets/Graph.shadergraph', '{"guid": "' + self.guid + '"}')
        self.put('Assets/image.png', b'\x89PNG\0\x01' + self.guid.encode())
        self.put('Packages/packages-lock.json', '{}')
        self.output = self.base / 'Unity'

    def put(self, name, content):
        p = self.source / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes) else content.encode('utf-8'))

    def hashes(self):
        return {str(p.relative_to(self.source)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.source.rglob('*') if p.is_file()}

    def run_conversion(self, **kw):
        return convert(self.source, self.output, 'unity', '2022.3.62f1', **kw)

    def test_convert_and_reference_consistency(self):
        before = self.hashes()
        report = self.run_conversion()
        new = report['guid_map'][self.guid]
        self.assertEqual(before, self.hashes())
        self.assertTrue((self.output / 'Assets/Scenes/Main.unity').exists())
        for name in ('Assets/Scenes/Main.unity', 'Assets/Editor/Boot.cs.meta', 'Assets/Test.asmdef', 'Assets/Graph.shadergraph'):
            text = (self.output / name).read_text()
            self.assertIn(new, text)
            self.assertNotIn(self.guid, text)
        self.assertEqual((self.output / 'Assets/image.png').read_bytes(), (self.source / 'Assets/image.png').read_bytes())
        self.assertNotIn('cn.tuanjie.codely.bridge', json.loads((self.output / 'Packages/manifest.json').read_text())['dependencies'])
        self.assertFalse((self.output / 'Packages/packages-lock.json').exists())
        self.assertIn('tag:unity3d.com,2011:', (self.output / 'Assets/Scenes/Main.unity').read_text())
        self.assertIn('Assets/Scenes/Main.unity', (self.output / 'Assets/Editor/Boot.cs').read_text())
        self.assertEqual(inspect(self.output)['invalid_guid_count'], 0)

    def test_dry_run_writes_nothing(self):
        before = self.hashes()
        self.run_conversion(dry_run=True)
        self.assertFalse(self.output.exists())
        self.assertEqual(before, self.hashes())

    def test_reverse_preserves_new_guids(self):
        report = self.run_conversion()
        reverse = self.base / 'Tuanjie'
        convert(self.output, reverse, 'tuanjie', '2022.3.62t7', '1.8.5')
        self.assertTrue((reverse / 'Assets/Scenes/Main.scene').exists())
        self.assertIn(report['guid_map'][self.guid], (reverse / 'Assets/Scenes/Main.scene').read_text())
        self.assertIn('tag:yousandi.cn,2023:', (reverse / 'Assets/Scenes/Main.scene').read_text())
        self.assertEqual(inspect(reverse)['engine'], 'tuanjie')

    def test_existing_output_and_nested_paths(self):
        for out in (self.source, self.source / 'Copy', self.base):
            with self.assertRaises(ValueError):
                convert(self.source, out, 'unity', '2022.3.62f1')
        self.output.mkdir()
        with self.assertRaises(ValueError):
            self.run_conversion()

    def test_duplicate_guid_stops_before_copy(self):
        self.put('Assets/Other.cs.meta', (self.source / 'Assets/Editor/Boot.cs.meta').read_bytes())
        with self.assertRaisesRegex(ValueError, '重复 GUID'):
            self.run_conversion()
        self.assertFalse(self.output.exists())

    def test_binary_serialized_stops_remap(self):
        self.put('Assets/Binary.asset', b'\0\x01binary')
        with self.assertRaisesRegex(ValueError, 'Force Text'):
            self.run_conversion()

    def test_scene_conflict_detected_in_scan(self):
        self.put('Assets/Scenes/Main.unity', 'conflict')
        with self.assertRaisesRegex(ValueError, '冲突'):
            self.run_conversion(dry_run=True)

    def test_external_package_stops(self):
        self.put('Packages/manifest.json', '{"dependencies":{"test.pkg":"file:../../external"}}')
        (self.base / 'external').mkdir()
        with self.assertRaisesRegex(ValueError, '外部本地包'):
            self.run_conversion()

    def test_downgrade_requires_explicit_option(self):
        self.put('ProjectSettings/ProjectVersion.txt', 'm_EditorVersion: 6000.6.0f1\n')
        with self.assertRaisesRegex(ValueError, '降级'):
            convert(self.source, self.output, 'tuanjie', '2022.3.62t7', '1.8.5')
        report = convert(self.source, self.output, 'tuanjie', '2022.3.62t7', '1.8.5', allow_downgrade=True)
        self.assertTrue(any('实验性降级' in x for x in report['warnings']))

    def test_target_editor_catalog(self):
        editor = self.base / '2022.3.62f1/Editor/Unity.exe'
        editor.parent.mkdir(parents=True)
        editor.touch()
        catalog = editor.parent / 'Data/Resources/PackageManager/Editor/manifest.json'
        catalog.parent.mkdir(parents=True)
        catalog.write_text('{"packages":{"com.unity.ugui":{"minimumVersion":"2.0.0","version":"2.0.1"}}}')
        report = self.run_conversion(editor=editor)
        self.assertEqual(report['package_changes']['com.unity.ugui']['to'], '2.0.1')


if __name__ == '__main__':
    unittest.main()
