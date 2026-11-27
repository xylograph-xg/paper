# 项目开发规则

<!-- tools-all:begin -->
## all 公共接口规则（自动维护）

开始接口任务先读 [all/RULES.md](all/RULES.md)、[工具清单](/Users/xiaoyanhao/project/tools/registry.json) 和对应工具卡。
修改接口后必须运行 `python3 "/Users/xiaoyanhao/project/tools/scripts/sync_tools.py" update`；同一任务完成说明、适配及待审查记录，结束前运行 `python3 "/Users/xiaoyanhao/project/tools/scripts/check_links.py"`。
新项目只需复制 all/ 并运行一次 `python3 all/setup.py`。本块与 all/ 公共文件由全局命令管理，项目定制放在本块之外。
<!-- tools-all:end -->

完整运行授权见工作区根AGENTS.md，不启动历史应用或暂停模型。
