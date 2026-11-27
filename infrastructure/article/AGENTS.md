# article：工具接口与 tools 双向联动

本文件约束本项目涉及可复用能力的新增、修改、迁移与删除；执行范围仍以用户当前任务为准。

## 先确认关系

- 本项目关系表：[tool-dependencies.json](tool-dependencies.json)。`exports` 是本项目维护的已登记工具；`tools` 是使用的已登记工具；`module_dependencies` 是尚未独立登记的跨项目模块引用。
- 统一入口：[tools/README.md](../../../tools/README.md)、[registry.json](../../../tools/registry.json)、[项目索引](../../../tools/projects.json)。开始修改公共接口前先读相关工具卡和 [联动流程](../../../tools/tool_registry/README.md)。
- 当前关系：项目通过 src/web_gpt_adapter.py 调用上游源码；web_gpt 已退出中央工具登记。

## 接口更新必须同时维护 tools

1. 参数、默认值、返回值、错误、超时、并发、环境变量、依赖、数据结构、路径和副作用发生变化时，识别本项目关系表中受影响的工具与模块。内部修复若改变已登记文件，也需核对源码指纹和实际行为；纯页面样式不触发无关工具更新。
2. 修改已登记导出时，在唯一权威源码位置完成实现及相关验证；同一任务更新原接口说明、tools 对应工具卡、registry.json 的接口/配置/限制/指纹及真实验证范围，追加 tools/CHANGELOG.md。有新增/移除/改名还需同步 tools/README.md 索引。
3. 修改使用方式时，同步本项目适配层与 tool-dependencies.json；在 registry.json 的 consumers 更新反向登记。修改导出前用 consumers 以及 projects.json 中其他项目的 module_dependencies 查找使用方，不能只看直接导入。
4. 对其他项目维护的工具提出通用修改，在其权威源码目录处理并同步 tools；业务定制留在本项目。已登记代码只有一个维护位置，不整目录双向覆盖。
5. 新增可复用接口按 [新增规范](../../../tools/tool_registry/README.md) 交付。尚未提取/验证的能力只更新候选/模块关系，不能直接写成已可用工具。
6. 登记源码检查和运行验收时分开记录：source_inspected / inspected_at / observed_source_files_sha256 表示静态核对；verified_at / verified_source_files_sha256 只用于实际接入验收。不要为让检查通过而只刷新摘要；未验证浏览器生成不可填成已验证。

## 结束接口任务前检查

```bash
python3 ../../../tools/tool_registry/check_links.py
```

检查为只读：核对源码基线、维护方/使用方双向关系、规则文件与路径；不会调用浏览器或业务接口，也不会修改摘要。

必须在最终说明中列出本项目与 tools 同步的文件、实际检查结果和未完成项。若权限或当前任务范围导致某处不能更新，明确列为待办并说明原因，不报告“已同步”。历史 audits 报告是当时快照，不因源码更新而改写原有证据。

这些是开发任务的完成规则，不是后台文件监听；手工绕过规则修改代码时，需要主动执行检查并同步说明。

## 工具调用

从[工具目录](../../../tools/README.md)选择工具，按对应 README 调用。接口变化时同步[登记表](../../../tools/registry.json)和本项目依赖，再运行 `python3 ../../../tools/tool_registry/sync_tools.py update` 和 `python3 ../../../tools/tool_registry/check_links.py`。

完整运行授权见工作区根AGENTS.md，不启动历史应用或暂停模型。
