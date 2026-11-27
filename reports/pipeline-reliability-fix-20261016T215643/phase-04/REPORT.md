# 本机文件赋值隔离与实机续查

EXEC_RUN_ID：EXEC-20261017-LOCAL-FILE-ASSIGNMENT-PHASE04。

前一版在2026-10-16 23:35完成121项源码/20槽新鲜度/暂停hash交接核对，但随后上传期间集中检查超时仍复现。2026-10-17约01:18复查23个已结束上传14成功、9失败（5附件结算超时、3旧PUT未知保护、1旧意图重复拦截），不能把代码检查通过称为网络全部解决。phase-03/extended-live-cohort.json为固定截面，24次开始含1未结束，全索引后至少9份原回答已完整保存，所有回执均已定位；页面采样错误不是任务失败次数。

源码检查发现：connect_over_cdp下Locator.set_input_files把本机ZIP经Playwright按字节传给浏览器，和状态/窗口核对共用控制通道。该本地大块复制是可移除的瓶颈假设；网络波动及PUT事件体积仍可能影响读取，效果必须由原所有者实机测得。

web_gpt.upload_files_detailed兼容增加仅关键字file_writer=None，默认与原赋值路径相同。paper原所有者显式local_file_paths=true时，核对本机Chrome进程、登记端点、原target、原input，以及两次原ZIP路径/大小/SHA与暂停守卫，在原连接用DOM.setFileInputFiles仅传路径；标记仅临时加于该input并清除。命令前追加持久attachment_write意图，写入回执不确定记unknown，不回退或再次写入。网页原生附件显示/180秒结算、HTTP/1.1原PUT一次持久意图、原最终发送/模型/暂停/人工/未知/科学保护不变。没有新增CDP连接或用户页面操作。

离线针对性250项通过（含9项本机赋值/错误target/ZIP变化/最后暂停/unknown不回退/原生结算合同），接口14组件/233生产文件/340公开出口通过。最终全量2246次执行、2063唯一测试ID、183既有重复导入，0失败/0错误/7既有跳过；结果保存于test-summary.json。镜像1257文件，未复制业务数据；源码及外部core前后原字节gzip和hash保留，R5旧e3b591fc字节缺口不因此消失。50MiB守卫暂不解除，冻结ZIP不改写；20页、最多5上传提交、32MB在途ZIP准入和180秒不变。

维护方/消费方实际同步：chatgpt_playwright/web_gpt/core.py及调用说明.md；tools/registry.json、web_gpt工具卡、CHANGELOG和派生快照；paper正式配置、browser适配/私有实现、review上下文、README/API合同、AGENTS/授权、paper及article依赖声明。实读article和question旧会话入口，不使用新关键字，因此业务代码无需修改；acknowledge只表示静态兼容，未冒称这两项目真实网页验收。全局最终update 0变化、8项目/4工具/70源文件/6链接检查通过。

依据原监督器正常交接；新进程实际源码、20槽、暂停hash及有限自然任务结果分别保存。不手动重发未知/旧PUT，不恢复暂停，不改代理节点，原分钟自动统计继续暂停。此报告为实施验证，非实施方仍须新CHECK_RUN_ID复审。

协议依据：[Chrome官方DOM.setFileInputFiles](https://chromedevtools.github.io/devtools-protocol/tot/DOM/#method-setFileInputFiles)。本机效果以本目录真实回执为准。

实机交接：原PID78970正常退出，新PID33397加载122项完全匹配源码，20槽新鲜且暂停hash不变。有限观察结束于2026-10-17 01:46:04，2次原生上传开始、1次成功、1次未结束。首份3,036,829字节通过local_cdp_path，附件赋值0.694秒，原生完整上传87.818秒并进入生成；仍有页面检查超时，未宣布网络/整个流程通过。进一步只读栈显示同步数据库读取拖延原事件循环，后继修复见phase-05。
