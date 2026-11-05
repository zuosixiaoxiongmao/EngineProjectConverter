"""Copy-based Unity/Tuanjie project format converter. Python 3.10+, stdlib only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from datetime import datetime, timezone

ROOTS = ('Assets', 'Packages', 'ProjectSettings')
TEXT_EXT = {'.meta', '.asset', '.scene', '.unity', '.prefab', '.mat', '.anim',
            '.controller', '.overridecontroller', '.playable', '.rendertexture',
            '.lighting', '.physicsmaterial2d', '.physicmaterial', '.cubemap',
            '.guiskin', '.mask', '.flare', '.scenetemplate', '.terrainlayer',
            '.asmdef', '.asmref', '.json', '.cs', '.shader', '.shadergraph',
            '.shadersubgraph', '.vfx', '.compute', '.txt'}
HEX_GUID = re.compile(r'^[0-9a-fA-F]{32}$')
VERSION = re.compile(r'^\d+\.\d+\.\d+[abfpt]\d+(?:c\d+)?$')
YAML_GUID = re.compile(r'(\bguid\s*:\s*)([^\s,}\"\']+)')
JSON_GUID = re.compile(r'((?:"guid"\s*:\s*"|GUID:))([^"\s]+)')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def version_info(project):
    return dict(re.findall(r'^(\w+):\s*(.*?)\s*$',
                          (project / 'ProjectSettings/ProjectVersion.txt').read_text(encoding='utf-8-sig'), re.M))


def project_files(source):
    for root in ROOTS:
        folder = source / root
        if not folder.exists():
            continue
        if folder.is_symlink() or (hasattr(folder, 'is_junction') and folder.is_junction()):
            raise ValueError(f'项目目录不能是链接：{folder}')
        for directory, dirs, files in os.walk(folder, followlinks=False):
            for name in dirs + files:
                p = Path(directory) / name
                if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
                    raise ValueError(f'发现符号链接或目录联接，请先将资源放入项目中：{p}')
            for name in files:
                yield Path(directory) / name


def read_text(path):
    data = path.read_bytes()
    if b'\0' in data:
        return None
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        return None


def editor_packages(editor):
    if not editor:
        return {}
    editor = Path(editor).resolve()
    if not editor.is_file():
        raise ValueError(f'编辑器不存在：{editor}')
    candidates = [editor.parent / 'Data/Resources/PackageManager/Editor/manifest.json',
                  editor.parent.parent / 'Resources/PackageManager/Editor/manifest.json']
    for p in candidates:
        if p.is_file():
            return read_json(p).get('packages', {})
    raise ValueError('未找到该编辑器的 PackageManager/Editor/manifest.json')


def inspect(source):
    source = Path(source).resolve()
    for name in ('Assets', 'ProjectSettings/ProjectVersion.txt', 'Packages/manifest.json'):
        if not (source / name).exists():
            raise ValueError(f'不是完整的项目根目录，缺少：{name}')
    info = version_info(source)
    files = list(project_files(source))
    invalid, seen, binaries = {}, {}, []
    for p in files:
        if p.suffix.lower() not in TEXT_EXT:
            continue
        text = read_text(p)
        if text is None:
            # These can contain serialized references; remapping cannot repair binaries.
            if p.suffix.lower() in {'.asset', '.scene', '.unity', '.prefab', '.mat', '.controller', '.anim'}:
                binaries.append(str(p.relative_to(source)))
            continue
        if p.suffix.lower() != '.meta':
            continue
        match = re.search(r'^guid:\s*(\S+)', text, re.M)
        if not match:
            raise ValueError(f'meta 缺少 GUID：{p.relative_to(source)}')
        guid = match[1]
        key = guid.lower() if HEX_GUID.fullmatch(guid) else guid
        if key in seen:
            raise ValueError(f'重复 GUID：{seen[key]} 与 {p.relative_to(source)}')
        seen[key] = str(p.relative_to(source))
        if not HEX_GUID.fullmatch(guid):
            invalid[guid] = hashlib.sha256(guid.encode()).hexdigest()[:32]
    if len(set(invalid.values())) != len(invalid) or set(invalid.values()) & set(seen):
        raise ValueError('GUID 映射发生冲突，已停止')
    manifest = read_json(source / 'Packages/manifest.json')
    dependencies = manifest.get('dependencies', {})
    return {'source': str(source), 'engine': 'tuanjie' if 'm_TuanjieEditorVersion' in info or 't' in info.get('m_EditorVersion', '') else 'unity',
            'version': info, 'file_count': len(files), 'invalid_guid_count': len(invalid),
            'guid_map': invalid, 'binary_serialized_files': binaries,
            'local_packages': {k: v for k, v in dependencies.items() if v.startswith('file:')},
            'tuanjie_packages': [k for k in dependencies if k.startswith('cn.tuanjie.')],
            'scenes': [str(p.relative_to(source)) for p in files if p.suffix in ('.scene', '.unity')]}


def prepare(source, output, target, version, tuanjie_version='', editor=None, allow_downgrade=False):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError('输出必须是源项目以外的独立目录，不能相互嵌套')
    if output.exists():
        raise ValueError('输出目录已经存在，请指定一个尚不存在的新目录')
    if target not in ('unity', 'tuanjie') or not VERSION.fullmatch(version):
        raise ValueError('目标版本应填写编辑器版本，例如 6000.6.0f1 或 2022.3.62t16')
    if target == 'unity' and 't' in version:
        raise ValueError('Unity 目标不能使用团结 t 版本号')
    if target == 'tuanjie' and (not re.fullmatch(r'\d+\.\d+\.\d+', tuanjie_version) or 't' not in version):
        raise ValueError('团结目标需同时填写基础编辑器 t 版本号和团结产品版本号')
    report = inspect(source)
    if (source / 'Temp/UnityLockfile').exists():
        raise ValueError('源项目可能正在编辑器中打开，请先关闭后转换，避免复制到不一致的文件')
    report.update(target=target, target_version=version, warnings=[], removed_packages={}, package_changes={})
    old = report['version'].get('m_EditorVersion', '')
    old_numbers = tuple(map(int, re.match(r'(\d+)\.(\d+)\.(\d+)', old).groups())) if re.match(r'(\d+)\.(\d+)\.(\d+)', old) else None
    new_numbers = tuple(map(int, re.match(r'(\d+)\.(\d+)\.(\d+)', version).groups()))
    if old_numbers and new_numbers < old_numbers:
        if not allow_downgrade:
            raise ValueError(f'{old} → {version} 涉及降级。无法自动还原新版 API/资源。需显式启用实验性降级')
        report['warnings'].append('实验性降级：仅处理项目格式，不能还原新版 API、渲染管线或序列化字段。')
    if report['binary_serialized_files']:
        report['warnings'].append('发现二进制序列化资源；无法重写其内部引用，请在原引擎中使用 Force Text 重新保存。')
        if target == 'unity' and report['invalid_guid_count']:
            raise ValueError('同时存在非标准 GUID 和二进制序列化资源，无法安全同步引用。请先在原引擎中转为 Force Text')
    packages = editor_packages(editor)
    if editor:
        editor_path = Path(editor).resolve()
        if editor_path.stem.lower() in ('unity', 'tuanjie') and editor_path.stem.lower() != target:
            raise ValueError('所选编辑器与目标引擎不一致')
        installed = next((p.name for p in editor_path.parents if VERSION.fullmatch(p.name)), None)
        if installed and installed != version:
            raise ValueError(f'所选编辑器版本为 {installed}，与填写的 {version} 不一致')
    if not packages:
        report['warnings'].append('未选择目标编辑器：保留现有包版本，首次打开可能需要手动调整依赖。')
    manifest = read_json(source / 'Packages/manifest.json')
    deps = manifest.setdefault('dependencies', {})
    for name, value in list(deps.items()):
        spec = packages.get(name, {})
        remove = target == 'unity' and (name.startswith('cn.tuanjie.') or name == 'com.unity.modules.infinity')
        remove = remove or bool(spec.get('removeOnProjectUpgrade'))
        if remove:
            report['removed_packages'][name] = value
            del deps[name]
        elif value.startswith('file:'):
            path = Path(value[5:])
            resolved = path.resolve() if path.is_absolute() else (source / 'Packages' / path).resolve()
            if not resolved.exists():
                raise ValueError(f'本地包不存在：{name} → {resolved}；请先修复依赖')
            if not resolved.is_relative_to(source / 'Packages'):
                raise ValueError(f'外部本地包不会随项目复制：{name} → {resolved}。请先嵌入 Packages 目录')
            deps[name] = 'file:' + resolved.relative_to(source / 'Packages').as_posix()
        elif spec.get('minimumVersion') and re.fullmatch(r'\d+\.\d+\.\d+(?:[-+].*)?', value):
            # Pin to the target editor catalog. For downgrades this is only a starting point.
            recommended = spec.get('version') or spec['minimumVersion']
            if recommended != value:
                deps[name] = recommended
                report['package_changes'][name] = {'from': value, 'to': recommended}
    registry = 'https://packages.unity.com' if target == 'unity' else 'https://packages.tuanjie.cn'
    if 'registry' in manifest:
        manifest['registry'] = registry
    if target == 'unity':
        for item in manifest.get('scopedRegistries', []):
            if 'tuanjie.cn' in item.get('url', ''):
                report['warnings'].append(f'保留自定义团结包源，请检查其用途：{item.get("url")}')
    # Embedded engine-specific packages cannot be removed by editing dependencies alone.
    for p in (source / 'Packages').glob('*/package.json'):
        if target == 'unity' and read_json(p).get('name', '').startswith('cn.tuanjie.'):
            raise ValueError(f'存在团结专有嵌入包 {p.parent.name}，请先移出 Packages 再转换')
    old_ext, new_ext = ('.scene', '.unity') if target == 'unity' else ('.unity', '.scene')
    for p in (source / 'Assets').rglob('*' + old_ext):
        dest = p.with_suffix(new_ext)
        if dest.exists() or Path(str(dest) + '.meta').exists():
            raise ValueError(f'场景重命名目标冲突：{dest.relative_to(source)}')
    report['warnings'].append('第三方插件、引擎专有 API、着色器及渲染效果仍需在目标编辑器中验证。')
    report['target_registry'] = registry
    return report, manifest


def convert(source, output, target, version, tuanjie_version='', editor=None, allow_downgrade=False, dry_run=False):
    report, manifest = prepare(source, output, target, version, tuanjie_version, editor, allow_downgrade)
    if dry_run:
        return report
    source, output = Path(source).resolve(), Path(output).resolve()
    files = list(project_files(source))
    old_ext, new_ext = ('.scene', '.unity') if target == 'unity' else ('.unity', '.scene')
    renames = {str(p.relative_to(source)).replace('\\', '/'): str(p.relative_to(source).with_suffix(new_ext)).replace('\\', '/')
               for p in files if p.suffix == old_ext and p.is_relative_to(source / 'Assets')}
    for old, new in renames.items():
        if (source / new).exists() or (source / (new + '.meta')).exists():
            raise ValueError(f'场景重命名目标冲突：{new}')
    tag_from, tag_to = ('tag:yousandi.cn,2023:', 'tag:unity3d.com,2011:') if target == 'unity' else ('tag:unity3d.com,2011:', 'tag:yousandi.cn,2023:')
    guid_map = report['guid_map'] if target == 'unity' else {}
    report['renamed_scenes'] = renames
    report['changed_files'] = []
    report['created_utc'] = datetime.now(timezone.utc).isoformat()
    report['format_version'] = 1
    report['status'] = 'writing'
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'conversion-report.json', report)
    # On a failure the partial output and report are retained for inspection.
    try:
        for p in files:
            rel = str(p.relative_to(source)).replace('\\', '/')
            if rel == 'Packages/packages-lock.json':
                continue
            dest_rel = renames.get(rel, rel)
            if rel.endswith('.meta'):
                dest_rel = renames.get(rel[:-5], rel[:-5]) + '.meta'
            dest = output / dest_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            text = read_text(p) if p.suffix.lower() in TEXT_EXT else None
            if text is None:
                shutil.copy2(p, dest)
                continue
            updated = text.replace(tag_from, tag_to)
            if guid_map:
                updated = YAML_GUID.sub(lambda m: m[1] + guid_map.get(m[2], m[2]), updated)
                updated = JSON_GUID.sub(lambda m: m[1] + guid_map.get(m[2], m[2]), updated)
            for old, new in renames.items():
                updated = updated.replace(old, new)
            if rel == 'ProjectSettings/PackageManagerSettings.asset':
                updated = updated.replace('https://packages.tuanjie.cn', report['target_registry']).replace('https://packages.unity.com', report['target_registry'])
            if rel == 'Packages/manifest.json':
                updated = json.dumps(manifest, ensure_ascii=False, indent=2) + '\n'
            if rel == 'ProjectSettings/ProjectVersion.txt':
                updated = f'm_EditorVersion: {version}\n'
                if target == 'tuanjie':
                    updated += f'm_TuanjieEditorVersion: {tuanjie_version}\n'
            if updated != text or rel != dest_rel:
                dest.write_text(updated, encoding='utf-8')
                report['changed_files'].append(dest_rel)
            else:
                shutil.copy2(p, dest)
        report['status'] = 'converted-not-editor-validated'
        write_json(output / 'conversion-report.json', report)
    except Exception as exc:
        report.update(status='failed', error=str(exc))
        write_json(output / 'conversion-report.json', report)
        raise
    return report


def gui():
    import queue
    import threading
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    root = tk.Tk()
    root.title('Unity ↔ 团结项目转换器')
    root.geometry('900x650')
    root.minsize(780, 560)
    frame = ttk.Frame(root, padding=18)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Unity ↔ 团结项目转换器', font=('Microsoft YaHei UI', 18, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 8))
    ttk.Label(frame, text='在新目录生成项目副本。转换格式后，仍需用目标编辑器检查编译和运行。').grid(row=1, column=0, columnspan=3, sticky='w', pady=(0, 14))
    variables = {key: tk.StringVar() for key in ('source', 'output', 'editor', 'version', 'tuanjie_version')}
    target = tk.StringVar(value='unity')
    downgrade = tk.BooleanVar(value=False)
    def choose(key):
        path = filedialog.askopenfilename(filetypes=[('编辑器', '*.exe'), ('所有文件', '*')]) if key == 'editor' else filedialog.askdirectory()
        if path:
            if key == 'output':
                path = str(Path(path) / ((Path(variables['source'].get()).name or 'Project') + '-' + target.get()))
            variables[key].set(path)
    for row, key, label in ((2, 'source', '源项目目录'), (3, 'output', '新输出目录'), (4, 'editor', '目标编辑器（可选）')):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', pady=5)
        ttk.Entry(frame, textvariable=variables[key]).grid(row=row, column=1, sticky='ew', padx=10)
        ttk.Button(frame, text='选择…', command=lambda k=key: choose(k)).grid(row=row, column=2)
    ttk.Label(frame, text='转换为').grid(row=5, column=0, sticky='w', pady=5)
    ttk.Combobox(frame, textvariable=target, values=('unity', 'tuanjie'), state='readonly').grid(row=5, column=1, sticky='w', padx=10)
    for row, key, label in ((6, 'version', '目标编辑器版本'), (7, 'tuanjie_version', '团结产品版本（仅团结）')):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', pady=5)
        ttk.Entry(frame, textvariable=variables[key], width=30).grid(row=row, column=1, sticky='w', padx=10)
    ttk.Label(frame, text='示例：Unity 6000.6.0f1；团结基础版本 2022.3.62t7、产品版本 1.8.5。请按安装版本填写。').grid(row=8, column=0, columnspan=3, sticky='w', pady=8)
    ttk.Checkbutton(frame, text='允许实验性降级（不能还原新版 API 和资源）', variable=downgrade).grid(row=9, column=0, columnspan=3, sticky='w')
    buttons = ttk.Frame(frame)
    buttons.grid(row=10, column=0, columnspan=3, sticky='w', pady=12)
    log = tk.Text(frame, height=12, wrap='word', font=('Microsoft YaHei UI', 10))
    log.grid(row=11, column=0, columnspan=3, sticky='nsew')
    frame.columnconfigure(1, weight=1)
    frame.rowconfigure(11, weight=1)
    messages = queue.Queue()
    def run(scan):
        values = {k: v.get().strip() for k, v in variables.items()}
        if not values['source'] or not values['output'] or not values['version']:
            messagebox.showerror('信息不完整', '请填写源项目、新输出目录和目标版本。')
            return
        options = dict(target=target.get(), allow_downgrade=downgrade.get(), dry_run=scan)
        values['editor'] = values['editor'] or None
        for button in (scan_button, convert_button):
            button.configure(state='disabled')
        log.delete('1.0', 'end')
        log.insert('end', '正在扫描项目…\n' if scan else '正在复制和转换项目，请等待…\n')
        def work():
            try:
                messages.put((True, convert(**values, **options), scan, values['output']))
            except Exception as exc:
                messages.put((False, str(exc), scan, values['output']))
        threading.Thread(target=work, daemon=True).start()
    scan_button = ttk.Button(buttons, text='预检查（不写入文件）', command=lambda: run(True))
    scan_button.pack(side='left', padx=(0, 12))
    convert_button = ttk.Button(buttons, text='生成转换副本', command=lambda: run(False))
    convert_button.pack(side='left')
    def poll():
        try:
            ok, data, scan, output = messages.get_nowait()
        except queue.Empty:
            root.after(150, poll)
            return
        for button in (scan_button, convert_button):
            button.configure(state='normal')
        if ok:
            log.insert('end', f'源引擎：{data["engine"]}，文件：{data["file_count"]}，非标准 GUID：{data["invalid_guid_count"]}\n')
            log.insert('end', f'移除专有/停用包：{", ".join(data["removed_packages"]) or "无"}\n包版本调整：{len(data["package_changes"])}\n')
            for warning in data['warnings']:
                log.insert('end', '注意：' + warning + '\n')
            log.insert('end', '预检查完成，未写入文件。\n' if scan else f'已生成：{output}\n详细记录：conversion-report.json\n请使用目标编辑器打开该目录验证。\n')
        else:
            log.insert('end', '已停止：' + data + '\n')
        root.after(150, poll)
    root.after(150, poll)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description='Unity ↔ 团结项目格式转换器；无参数启动中文界面。原项目不改动。')
    parser.add_argument('source', nargs='?')
    parser.add_argument('output', nargs='?')
    parser.add_argument('--target', choices=('unity', 'tuanjie'))
    parser.add_argument('--version', help='目标编辑器版本，如 6000.6.0f1 或 2022.3.62t7')
    parser.add_argument('--tuanjie-version', default='', help='团结产品版本，如 1.8.5')
    parser.add_argument('--editor', help='目标 Unity.exe/Tuanjie.exe，用于读取匹配的包版本')
    parser.add_argument('--allow-downgrade', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not args.source:
        gui()
        return 0
    if not args.output or not args.target or not args.version:
        parser.error('命令行转换需填写 source、output、--target、--version')
    try:
        print(json.dumps(convert(**vars(args)), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print('转换已停止：' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
