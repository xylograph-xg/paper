# 共享运行项目规则

业务授权、暂停和数据保护以 [工作区AGENTS](../AGENTS.md) 为准；本目录维护共享接口、运行数据、配置、唯一浏览器所有者和全局工具登记。禁止复制业务实现或恢复暂停任务。数据备份由用户明确禁用。

## 工具调用

从[工具目录](../../tools/README.md)选择工具，按对应 README 调用。接口变化时同步[登记表](../../tools/registry.json)和本项目依赖，再运行 `python3 ../../tools/tool_registry/sync_tools.py update` 和 `python3 ../../tools/tool_registry/check_links.py`。
