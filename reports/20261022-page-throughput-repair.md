# 页面长间隔、回执与队首准备修复

用户要求对全部长间隔/完成记录缺失槽位深入检查并修复。原始快照保存在[验证目录](20261022-page-throughput-validation/)，全部记录上海时间，不把完成间隔当成故障时长。

## 核实原因

- 01及其他预留页：存在queued队首和后续ready材料；原核验生产者在同一个准备循环里同步执行全库发现、失败循环及恢复扫描，扫描未返回时不领取已分配队首，也不处理刚保存回答。原FIFO必须保持，修复准备吞吐而不让后项越过前项。
- 08：原回答完整保存，但提交确认与收取可交错；旧确认按整个旧池快照写回导致PoolConflict，且队列确认可能把已完成状态降回submitted。
- 19：派发与队列重组交错导致head_binding_changed。该拒绝本身是安全守卫，不解除；补充回调生命周期的持久领取，使旧未发送记录不能释放仍活跃的新回调，结束后再允许恢复扫描处理。
- 10和20：调查中10在22:16完成新回答，20在22:09提交并继续生成；不能据上次完成间隔将它们当作持续阻塞。
- 16：18:29原请求已提交，网页终态、唯一用户消息存在但回答正文为零。旧健康分类先按entry=busy返回，导致终态空回答无限保留。新增原提示/材料/target/正式唯一URL绑定、原请求超过一小时及两轮相隔30秒实查后归档换页；不重发原请求，不标科学失败。
- 04：当前target账本缺失，实际完整回答、独立response-raw、原packet及实际提示仍在；唯一材料ID定位到原失败核验任务。新增严格版本/输入/实时正文/提示/唯一URL及稳定性核对、完整页面归档后恢复观察回执。明确原sender、send time及actual model未知；不补造原发送字段、不改旧回答和评分。
- 03/05/07/11/13：原历史回答并未丢失；统计只按新target而未并入槽位历史会产生“暂无记录”。其中多页处于新任务提交或准备，按槽位历史和当前请求分别解释，不伪造新页完成。13在本轮只读检查中已正常生成。
- 一个旧窗口修复计划缺nonce：原窗口已替换且原页不在时，读取nonce前缺少检查；只允许取消已被原登记启动窗口取代的旧计划，不重复未知创建。

## 边界

只有原注册后台连接操作浏览器。没有新增CDP或常驻，没有导航/关闭用户其他窗口，没有恢复暂停或重发未知请求。冻结输入、旧科学卡、回答、评分和原回执保护。模型未知会显式保留，独立科学/生产合同不因技术恢复自动改判。

## 验证与现场

离线回归、完整测试、接口与全局链接、确切源码指纹和正常交接证据见[验证目录](20261022-page-throughput-validation/)。现场结果在完成交接后追加，不以测试成功冒称实际修复成功。

## Direct root cause confirmed

The old HTTP watcher invoked TTL writers every ten minutes. They moved live attempt files, cleared claimed bindings, rewrote pool entries as blank, and rerouted submitted reviews into new auto folders after thirty minutes, without checking real DOM activity. This directly explains displaced original receipts and pool ownership conflicts. Original code and SHA256 are preserved. The watcher was stopped normally; these writers are now owner-request-only adapters. The original request on slot 13 was found in claim-lease-release, and its unsubmitted duplicate preparation was held pending exact original-owner restoration.

2026-10-23：核验媒体目录新增物理准备文件夹指纹，防止同一核验ID的重排候选覆盖原冻结PDF。已发送旧材料仅可从原ZIP按每文件及整体指纹恢复到独立verified-inputs视图；旧损坏字节、原packet、实际提示和回执均保留，不生成新输入或重发。

2026-10-23现场交接暴露另一项阻塞：原主循环在queue.select全库补选时发生database is locked，并在进入页面巡检前退出本轮。补选迁至现有MaterialProducer第0工作线程，完成后60秒节流，单独记录状态/错误；浏览器主循环只读其上一完整结果，不新建线程或连接，扫描失败不跳过原页面观察/收取。

## 最终代码验证与保护中的现场

- 全量测试2729项执行，2518个独立测试，0失败/错误；make check、全局update及链接检查通过。验收源码、原监督器正常停启及原后台正常交接均有独立回执。
- 04页已有回答完成恢复收取并进入原修正流程；16页旧请求终态无正文，已完整归档、原槽补页，旧请求未重发。
- 13页原ZIP和原回执均已找到；原所有者已创建逐文件哈希一致的独立材料视图及完整页面证据。但重复准备在12页存在claimed登记，恢复守卫保留该冲突，未将其宣称恢复完成，也未强制删除领取或重发。
- 浏览器仍有网站加载失败等实时外部问题；最终现场快照分别记录实际页面、可用数及未解决原因，不以代码测试通过代替真实网页恢复。
- 旧HTTP按超时改写账本的逻辑已退役；完整原脚本/指纹保留。新监督器仅请求原所有者维护，后台扫描不再抢占浏览器观察和收取主循环。

## 最终实查（上海时间2026-10-23 00:38）

原旧PID78544正常退出，原注册入口启动PID84375；精确源码匹配最终验收，监督状态healthy。20个登记槽位均有12秒内新鲜观测，20页输入框均可见；服务29秒内核对的实际并行为核验1、制卡0、修正0，服务与最新健康检查无错误。四项暂停控制文件哈希均未改变。详见验证目录live-final-owner.json。

13页的原完整回答已从原所有者换页前的完整归档中逐项核对归档SHA、原target/唯一URL、终态和原完整提示，独立提取12490字节，见13-original-review-response.txt及13-original-response-recovery.json。原发送时间与实际模型设置来自原回执，未补造；原数据库与12页重复claimed仍保留，尚未将其计为正常入账或科学通过。13槽现为已归档替换的新页。本轮技术修复已经实际接管，原回答的正常入账仍受该领取冲突保护，不能宣称全部业务问题完成。
