# 项目开发规则

## 工具调用

从[工具目录](../../../tools/README.md)选择工具，按对应 README 调用。接口变化时同步[登记表](../../../tools/registry.json)和本项目依赖，再运行 `python3 ../../../tools/tool_registry/sync_tools.py update` 和 `python3 ../../../tools/tool_registry/check_links.py`。

完整运行授权见工作区根AGENTS.md，不启动历史应用或暂停模型。
