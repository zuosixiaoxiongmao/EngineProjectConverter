# Unity ↔ 团结项目格式转换器

本地 Python 工具，带中文窗口和命令行，使用 Python 3.10 及以上版本，无需第三方库。

双击 **启动转换工具.cmd**，选择源项目根目录、新输出目录、目标引擎及编辑器版本。建议选择目标 `Unity.exe` 或 `Tuanjie.exe`，工具会读取该安装版本的包目录。先点“预检查”，再点“生成转换副本”。源项目请先关闭编辑器。

输出目录必须不存在；选择输出位置时，界面会在所选父目录下建议一个新项目名。只有 `Assets`、`Packages`、`ProjectSettings` 会复制，Library/Temp/存档/构建产物不会复制。项目根目录的外部脚本、文档和外部依赖需另行管理。

## 自动处理

- 团结 `.scene` 与 Unity `.unity` 场景及对应 meta 重命名，更新完整项目相对路径引用。
- Unity/团结 YAML 标记转换。
- 团结转 Unity：对非标准 GUID 生成稳定的 32 位标识，同步修改文本资源中 `guid:`、JSON `"guid"` 和程序集 `GUID:` 引用；合法 GUID 保持原值。
- 版本文件、默认包源转换；读取目标编辑器的包目录以调整已有直接依赖，移除目标编辑器明确停用的包。
- 转 Unity 时移除 `cn.tuanjie.*` 直接依赖和 `com.unity.modules.infinity`。不猜测这些专有功能的 Unity 替代实现。
- 移除旧 packages-lock，供目标编辑器重新解析。完整操作、警告和 GUID 映射写入输出根目录 `conversion-report.json`。
- 原项目不改动、不覆盖现有输出；重复 GUID、重命名冲突、外部本地包、链接目录会阻止转换。

## 能力边界

这是**项目格式迁移工具**，不保证任意版本、插件、平台无损互转。仅生成副本不代表编译或运行验证通过；报告状态明确标记 `converted-not-editor-validated`。

团结主要基于 Unity 2022 LTS。Unity 6 转回 2022 系列涉及降级，默认阻止；显式开启“允许实验性降级”只生成待手工适配的副本，不能还原新 API、URP/HDRP、Shader Graph、实体包和新版序列化数据。

GUID 转换是生成新标识并重写引用，**不是解密原 GUID**。反向转换保留已经合法的 GUID，不会恢复原来的非标准编码。被移除的包不自动恢复，可参考原项目或报告重新安装。

同时存在非标准 GUID 与二进制序列化资源时会停止，需先在源引擎将资源设为 Force Text 并重新保存。无法解析的自定义二进制格式、代码动态拼接的路径、自定义 GUID 字段仍需手工检查。自定义包源保持原样并提醒检查；团结专有嵌入包须先移出 Packages。不会自动下载安装或启动引擎。

## 命令行（PowerShell）

```powershell
# 团结 → 本机 Unity 6；先预检查，确认后去掉 --dry-run
python engine_converter.py 'D:\Projects\MyTuanjieGame' 'D:\Projects\MyUnityGame' --target unity --version 6000.6.0f1 --editor 'C:\Program Files\Unity\Hub\Editor\6000.6.0f1\Editor\Unity.exe' --dry-run

# Unity 2022 → 团结；两个版本号均填写目标实际安装版本
python engine_converter.py 'D:\Projects\Unity2022Game' 'D:\Projects\TuanjieGame' --target tuanjie --version 2022.3.62t7 --tuanjie-version 1.8.5

# 验证转换器逻辑
python -m unittest -v
```

## 参考

- [团结官方兼容说明](https://unity.cn/tuanjie/help-center)：Unity 2022 LTS 兼容范围及插件注意事项。
- [Codely 官方场景工具说明](https://codely-docs.tuanjie.cn/features-introduction/unity-tools-guide/)：两种场景扩展名。

此工具为独立实现，不是 Unity 或团结官方产品。

## 本机验证记录（2026-11-05）

- 10 项单元测试通过，包含双向格式转换、GUID 引用一致性、原项目不变、预检查不写文件、路径冲突、外部包和降级处理。
- 使用群侠项目转换前备份实测团结转 Unity：处理 1521 个文件、385 个非标准 GUID，在 Unity 6000.6.0f1 中完成编译，原项目的 45 关模拟测试输出 `[Campaign] RESULT errors=0`。
- 中文界面已启动并检查布局。反向转换尚未通过团结编辑器实机验收；Unity 6 降级不能视为已验证支持。
# EngineProjectConverter
# EngineProjectConverter
# EngineProjectConverter
