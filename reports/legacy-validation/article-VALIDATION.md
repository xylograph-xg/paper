# 第一阶段验证记录

## 人工选择与探索树更新（2026-09-18）

新增 `run.command`（macOS）和 `run.cmd`（Windows）、本地筛选页面、SQLite 轮次快照与选择历史、探索树和离线 HTML/JSON 导出。

- **28 项自动化测试通过**：含原有 19 项，以及选择持久化、取消后保留分支、重复保存/导入、跨项目父节点校验、多窗口版本冲突、导出内容转义与 HTTP 接口验证。
- macOS 启动器执行验证通过，JavaScript 和 Bash 语法检查通过。Windows 启动器未在 Windows 实机验证。
- 浏览器实测：导入现有 100 篇候选，勾选 3 篇并保存；从其中一篇发起真实主题搜索 `OLED triplet exciton annihilation`，成功获取并保存 5 篇候选；再选 2 篇保存，树中显示两轮、5 个兴趣节点、2 次选择记录。
- 刷新页面后，第二轮已选 2 篇和完整选择记录正确恢复。独立 HTML 快照在静态文件服务下正常显示树、候选与历史，不依赖 API；无浏览器 JavaScript 错误。
- 所有浏览器测试选择均使用临时目录数据库。正式数据库仅导入已有候选，初始兴趣节点和选择事件均为 0，没有将测试选择当作用户偏好。

以下保留最初数据发现层的验证记录。

日期：2026-09-18（Asia/Shanghai）  
项目：`/Users/xiaoyanhao/Desktop/article`  
虚拟环境：`/Users/xiaoyanhao/venv/article`  
Python：3.13.3。依赖实际版本见 `requirements.lock.txt`。

## 自动化验证

```bash
/Users/xiaoyanhao/venv/article/bin/python -m unittest discover -s tests -v
```

结果：**19 项测试全部通过**。包含标准化、缺失/异常字段、DOI 与标题去重、跨记录 ID 关联、冲突 DOI、relevance 分页、bulk 分页及数量截取、HTTP 429/503、timeout、连接错误、异常 JSON/响应结构、配置覆盖、原子保存、空结果、部分失败保留及完整处理流程。

`python -m pip check` 通过，无依赖冲突。

## 真实 OLED 搜索

执行：

```bash
cd /Users/xiaoyanhao/Desktop/article
/Users/xiaoyanhao/venv/article/bin/python -m src.main --topic "OLED triplet exciton" --limit 100
```

结果：退出码 **0**，API **HTTP 200**；使用默认 `bulk` 模式，按引用数降序选取候选。没有使用测试夹具或本地模拟数据。

| 指标 | 数值 |
| --- | ---: |
| API 估计匹配总数 | 1,246 |
| API 本页实际返回条目 | 1,000 |
| 本轮设置 limit | 100 |
| 本轮选取并清洗 | 100 |
| 跳过无效记录 | 0 |
| 去重后论文 | 100 |
| 有 abstract | 33 |
| 有 DOI | 100 |
| 有 OA PDF 地址 | 26 |

批量接口不接受每页 limit 参数，因此完整保存其返回的 1,000 条原始数据，本轮只将前 100 条纳入清洗结果。没有把 1,000 条全部当作本轮候选，也没有声称去除了实际不存在的重复项；去重分支另外通过自动化测试验证。

样例记录：

1. *Highly efficient organic light-emitting diodes from delayed fluorescence*（2012），DOI `10.1038/nature11687`。
2. *Highly phosphorescent bis-cyclometalated iridium complexes: synthesis, photophysical characterization, and use in organic light emitting diodes.*（2001），DOI `10.1021/ja003693s`。
3. *Recent Progresses on Materials for Electrophosphorescent Organic Light‐Emitting Devices*（2011），DOI `10.1002/adma.201003128`。

输出证据：

- 原始响应：`data/raw/search_20260917T163645_783001Z.json`
- 标准化论文：`data/processed/papers_20260917T163645_783001Z.json`
- 最新结果：`data/processed/papers_latest.json`
- 成功日志：`logs/run_20260917T163645_783001Z.log`

输出复核：100 条均通过 Pydantic Paper 校验；论文内部 ID、DOI、Semantic Scholar ID 各自无重复；带时间戳处理文件与 latest 内容完全一致。

## 发现的问题与边界

1. **relevance 接口真实限流。** 首次通过 `/paper/search` 请求主题与 100 篇 limit，收到连续三次 429 后按设计退出。失败证据在 `logs/run_20260917T163416_900746Z.log` 和对应原始 JSON 中。随后验证了官方 `/paper/search/bulk` 并将其设为默认模式；relevance 仍可通过 `--search-mode relevance` 使用。两种模式不会在单次运行中静默混用。建议需要相关性排序时配置官方 API key 后再实测。
2. **摘要覆盖有限。** 本批 67 篇缺 abstract，保留为空字符串，没有生成或拼凑摘要。后续引入 AI 摘要前应先评估元数据补全需求。
3. **批量检索的排序偏差。** 当前按引用数排序，可能偏向较早论文；真实样例只是搜索候选，不等于人工确认相关论文。年份参数可收窄时间范围。
4. **去重范围为单轮。** 当前每次搜索独立保存，latest 是最近成功快照。跨轮去重、人工反馈保存与身份映射应在后续数据库阶段加入。
5. **OA PDF 仅为地址。** 26 条表示 API 提供了地址，本阶段没有下载或检查全文可访问性。

## 下一阶段建议

先补充几个实际研究主题与年份范围，检查字段覆盖和检索质量。随后引入 SQLite 做跨轮存储，并实现四类人工筛选状态；再考虑围绕 interested/deep_read 论文扩展。不要在当前基础层中提前混入全文解析、AI 摘要、推荐、Zotero 或 OLED Knowledge Pipeline。
