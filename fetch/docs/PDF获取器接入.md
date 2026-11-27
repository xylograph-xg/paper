# PDF 多来源获取

统一队列先尝试已有 PDF 直链，再调用隔离的 fetchpdf 获取器。新获取器覆盖 Crossref 书目链接与论文网页、Semantic Scholar、OpenAlex、公开仓储和出版商 URL 路由；部分来源需要 API 密钥才会启用。仍然没有取得全文时保留待办和错误原因。

上游： https://github.com/The-Metascience-Observatory/fetchpdf

固定提交：`c4b152b8edfa88ef2af7b5f666fa715179bf334b`，MIT 许可。源码和许可保存于 `fetch/dependencies/fetchpdf/`，不自动升级。运行环境是 `fetch/environments/fetchpdf/`，由 `infrastructure/config/first_round.json` 的 `pdf_retrieval.python` 指向，与本地阅读模型的 Python 环境分开。`UPSTREAM.json` 保存版本来源。

适配文件：`fetch/fetchpdf_bridge.py`、`fetch/acquire_bridge.py` 与 `fetch/fetch_service.py`；`infrastructure/pipeline/` 下同名文件只是兼容适配层。配置 `pdf_retrieval.timeout_seconds` 为 75 秒，快速/后备任务预算分别为 65/110 秒；`services.py` 中的 180 只是未配置时的兜底默认值。超时记录为超时，不声称论文付费或要求认证。下载完成后再次校验 PDF 格式、题名/DOI，复制到 SSD 并校验哈希，自动排队重新筛选。获得原文不会自动覆盖人工选择。

本版强制保留 TLS 证书校验，对 requests 的请求及重定向检查公开地址。关闭机构 Cookie 获取、额外付费搜索和外部 LLM 获取；不读取学生密码。仅安装公开 HTTP 获取依赖，未安装 Playwright 或 browser_cookie3，也未启动浏览器获取。该最小运行配置不会满足上游完整包的可选浏览器能力，属于本项目限定用途的适配。

Unpaywall 需要真实联系邮箱。可设置 `UNPAYWALL_EMAIL` 环境变量，或者在 `infrastructure/config/first_round.json` 的 `pdf_retrieval.contact_email` 配置；未设置时跳过该来源并记录。其他 API 密钥按上游环境变量配置，未配置的来源不会假装已查询。

从源码重建环境：

```sh
~/venv/bin/python -m venv fetch/environments/fetchpdf
fetch/environments/fetchpdf/bin/python -m pip install --no-deps -r infrastructure/config/pdf-retrieval-requirements.lock
```

升级前需重新审查源码，更新来源提交及锁文件，然后用候选 DOI 验证。学校认证与出版商反自动化访问并不是换一个包就能解决；此版本不保证所有待办都能获取。
