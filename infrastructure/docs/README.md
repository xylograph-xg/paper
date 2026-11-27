# 模板与冻结授权凭据

当前卡片模板Markdown/HTML、历史授权原文及保护边界。

## 为什么保留、为什么这样选择

原生面板当前读取固定模板文件，限定恢复账本按授权文件原字节hash核对。将其保留为唯一只读证据/模板接口，避免目录整理改变原回执判定。旧流程指南已归属各项目，旧审查报告集中reports。

## 接口与内容

接口声明见 [interface.json](interface.json)。正式调用入口是 `docs.api`；文件型接口保持原JSON/哈希合同。

- [文献卡片模板.md](文献卡片模板.md)：current displayed template。
- [文献卡片模板.html](文献卡片模板.html)：native panel stable file interface。
- [authorizations/](authorizations/)：immutable authorization bytes; past authority is not current run approval。

## 边界

授权档案只证明当时范围，不能恢复暂停或扩大旧实验；模板展示与科学生成合同独立。

源码当前接口与删除理由见 [项目地图](../../WORKFLOWS.md)。

- [authorizations/20261014-missing-slot-new-epoch.md](authorizations/20261014-missing-slot-new-epoch.md)：第05槽一次新创建epoch的具体用户授权；保存旧未知操作，不重发旧文献。
