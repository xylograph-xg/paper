# 拉取第三方依赖

固定版本fetchpdf源码、许可证与原依赖元数据。

## 为什么保留、为什么这样选择

当前回退下载适配调用 `fetch/dependencies/fetchpdf/`，运行环境为 `fetch/environments/fetchpdf/`，故保留唯一依赖源码和版权声明；业务策略与网站限速在 fetch/core 接口中，第三方代码不拥有主队列或浏览器。

## 接口与内容

接口声明见 [interface.json](interface.json)。正式调用入口是 `fetch.api`；文件型接口保持原JSON/哈希合同。

- [fetchpdf/](fetchpdf/)：actual current fallback implementation and license。

## 边界

不修改第三方业务代码，不将其独立数据库或模板当成主目录运行状态。

源码当前接口与删除理由见 [项目地图](../../WORKFLOWS.md)。
