# Mac Studio 环境配置记录

日期：2026-10-04。

## 配置与适配

- Python 环境目标：`/Users/xiaoyanhao/venv`，Python 3.13，依赖来自 `app/requirements.txt`。
- Ollama 程序：`/Applications/Ollama.app/Contents/Resources/ollama`（当前安装版本 0.34.0）。
- 模型：`gemma4:31b`，模型目录 `/Users/xiaoyanhao/venv/models`。
- 专用本地服务：`127.0.0.1:11435`，由启动脚本显式设置 `OLLAMA_MODELS`；仅本机访问，禁用 Ollama 云功能。
- 项目配置调整：模型 12B → 31B；上下文 8192 → 16384；输出上限 1600 → 4096；原文证据字符上限 6000 → 12000；其余阅读流程与原文数据目录沿用。
- `启动资料卡.command` 改为统一环境入口；新增 `配置阅读环境.command` 供重新安装依赖和续传模型；新增 `scripts/ollama_env.sh` 复用服务配置。
- 本项目没有已登记的公共工具导出或使用方，无需修改现有 tools 工具卡，也没有其他项目的业务适配变更。

## 验证状态

- Python 3.13.16（arm64）；Streamlit 1.65.0、PyMuPDF 1.28.2、requests 2.34.2。pip check 通过；完整安装版本保存于 `app/requirements-mac-studio.lock.txt`，修复脚本优先使用该文件。
- 安装时官方 PyPI 下载速度偏慢，改用清华大学 HTTPS PyPI 镜像成功完成；缓存位于 venv/cache。
- 已在 venv/bin 添加 Ollama 命令入口；激活环境后 `ollama list` / `ollama ps` 自动使用专用服务。pip 源与缓存配置仅保存在 venv/pip.conf。
- Gemma 31B 下载成功并通过 SHA-256 校验；Ollama 模型 ID：17ba34c06c80，模型目录约 19GiB，模型列表显示约 20GB。
- Ollama 识别 Apple M5 Max / Metal，连接检查通过。
- 两篇现有论文的 PDF 解析成功，卡片加载成功；Streamlit AppTest 对两篇文献卡及上传页面验证均无异常。
- 验证过程中发现已有无编号公式重名导致下载按钮 key 重复；只修改页面按钮标识，加入列表序号，修复后验证通过。没有改动已有资料卡。
- 使用项目实际 OllamaClient 完成文本与真实论文图片调用，原始结果保存在 `docs/Mac-Studio-模型验证.json`。读图输出匹配面板 a/b/c、Time (s)、Normalized afterglow intensity (a.u.) 及五个图例，约 3.97 秒。此短提示验证采用 16K 上下文与 512 输出上限，不能作为整篇资料卡耗时或质量基准。
- 文本测试用一段简短论文材料，正确区分 2 s 实测衰减时间与“可能由三线态激子局限引起”的作者推断，约 2.10 秒；ollama ps 显示 100% GPU、16384 上下文。
- `启动资料卡.command` 已实际启动；http://localhost:8501/_stcore/health 返回 ok。
- tools 全局 update 与 check_links 均通过；没有登记工具或其他使用方变更。

历史资料卡继续使用其原有模型记录，切换模型不会自动重新生成旧卡片。未重新生成整篇论文资料卡，未安装可选 pix2tex。

## 待审查

- 用代表性论文评估 31B 的坐标轴、图例、公式变量解释与证据忠实度；在真正运行前不宣称质量优于 12B。
- 全文重新处理仍覆盖已有生成结果；人工标签独立保存。
- pix2tex 为可选功能，本次不额外安装其 Torch 依赖。
