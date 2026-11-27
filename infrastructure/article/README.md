# 网页工具适配接口

原登记web_gpt的会话适配、本机浏览器检查、工具导入根配置，以及向原唯一所有者请求浏览器就绪。

这是独立源码与接口文件夹，正式包名为 `article`。跨项目只调用 `article.api` 或本项目声明的CLI/JSON接口；不存在跨目录源码链接。

## 为什么选择、为什么保留

删除旧探索器、制卡worker、旧网页UI与独立运行环境，只保留仍被引用的web_gpt适配。保留已有调用签名、项目锁和显式provider校验；open_gpt入口现在请求原所有者，不独立创建Chrome。

## 接口与运行

- [interface.json](interface.json)：版本、依赖、全部公开出口及真实实现签名。
- [api.py](api.py)：接口入口，返回原函数/类对象，保留参数、异常与共享对象身份，不另复制实现。
- [pyproject.toml](pyproject.toml)：可单独构建/安装的Python子项目。

公共符号以 `模块__符号` 命名，避免各模块的 `status`、`enabled` 等同名函数冲突；模块出口用于保留已有有状态接口。调用参数、返回值与异常见真实函数签名及源码，不由适配层改写。

```python
from article.api import gpt_session
```

运行依赖：[browser](../browser/README.md)、[core](../core/README.md)。

CLI/子进程入口：`python -m article`。标准输入JSON桥仍使用原请求/响应结构，不混入诊断输出。

从 paper 根目录按需运行：

```sh
PYTHONPATH=infrastructure/bootstrap:.:../chatgpt_playwright infrastructure/environments/test/bin/python infrastructure/maintenance/test_runner.py --project article
make check
```

可用支持PEP 517/660的安装器按本目录 `pyproject.toml` 独立安装。宿主负责安装接口依赖和提供 `PAPER_WORKSPACE_ROOT`；当前运行环境沿用现有虚拟环境，避免目录整理触发依赖重装或服务重启。

## 内部全部实现与功能

以下清单列出本项目每份实现及其顶层函数、类和类方法；测试、说明与配置在下节单列。辅助内部函数不是跨项目授权出口。

| 文件 | 功能 | 内部函数 / 类方法 | 保留原因 |
| --- | --- | --- | --- |
| [tool-dependencies.json](tool-dependencies.json) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [open_gpt.command](open_gpt.command) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [api.py](api.py) | 公开接口入口，延迟返回唯一实现对象 | `open_browser` | 当前公开接口或生产链使用；避免复制实现 |
| [AGENTS.md](AGENTS.md) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [__main__.py](__main__.py) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [src/web_gpt_adapter.py](src/web_gpt_adapter.py) | 外部网页工具调用与项目级锁 | `import_root`、`check_browser`、`gpt_session` | 当前公开接口或生产链使用；避免复制实现 |

## 测试、说明及配置清单

- [pyproject.toml](pyproject.toml)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [interface.json](interface.json)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [tests/__init__.py](tests/__init__.py)：离线/隔离回归，验证当前合同。
- [tests/test_web_provider_adapter.py](tests/test_web_provider_adapter.py)：离线/隔离回归，验证当前合同。

## 数据、并发和权限边界

显式会话调用涉及外发和网页操作；检查/启动请求各有保护，本轮不执行。 原文、卡片、冻结输入、回执与人工决定保留原存储位置。暂停、原文/版本身份、真实领取、未知提交不重发及科学验收要求不变。接口导入、测试或文档阅读不构成启动/外发授权。

当前配置入口是 [config](../config/README.md)，共享状态合同见 [data](../data/README.md)。共用Catalog通过core API持有事务；不复制数据库、锁或共享浏览器所有者。

## 已删除与保留的证据

旧独立模型实验、旧Streamlit/旧article应用、重复符号链接、旧平铺测试和旧一次性迁移脚本已删除；本项目测试已使用正式包名。逐文件删除原因与指纹见 [清理审查](../../reports/physical-isolation-cleanup.json)。历史评审和原授权用于追溯原请求，保留不表示可恢复旧任务。
