# 页面吞吐与收取链修复授权（2026-10-22）

用户要求：“那时间也都比较差，对于这些问题全都深入查询他们的问题再修复”。范围为现有20槽的任务接续、队首材料准备、回执保存、空闲页复用、终态空回答、历史完成记录及当前故障日志；沿原唯一CDP所有者和原三个常驻入口，不增加浏览器连接或模型实验。

- 核验生产者的全库发现/恢复与已分配材料准备分离：复用原线程池，仅一个发现future；发现失败或耗时不挡已保存回答处理及队首准备，完成后60秒再扫描。停止信号在文献循环之间检查，不恢复暂停；固定分组、手选种子优先、真实评分和FIFO保持。
- 上传回调安排前由原所有者持久登记原PID/token SHA和target占用，结束后才释放。两类恢复扫描均跳过活跃回调，旧not_sent记录不授权回收新回调；未知结束继续保留。
- 原请求提交确认只合并同target/材料身份及唯一会话；若原回答已完整收取，不降级为busy/submitted，不覆盖新任务。收取异常不覆盖已保存回执。
- 原页面用户、材料标识、完整提示SHA、正式唯一URL全部核对，网页明确终态但无任何回答正文时，原已提交超过3600秒并两次相隔30秒同指纹实查后，可完整归档并在原槽补页。原发送账本保持，不标科学失败、不冒称回答已收取、不重发原文献。
- 原核验当前账本缺失但完整材料包、实际提示、原文/卡片版本及独立保存回答仍存在时，唯一材料ID/正式会话/完整实时正文逐字匹配、稳定实查、原任务失败且无其他页面领取、人工和版本保护均通过后，由原所有者完整归档并保存明确标注的“观察恢复回执”。原发送时间、发送者和实际模型未知，不补造sender PID、send_click_started或原发送时间；created明确为恢复观测时间。旧状态、原回答和冻结材料保留，科学核验及生产合同独立。
- 旧窗口故障计划缺nonce且原窗口已被登记启动窗口替代时，只取消归档旧计划；不重新创建未知页。

已发送但仍生成、实际上传、登录/验证/额度、用户新草稿和无法绑定的未知请求继续保留。源码需通过全量测试、接口及全局链接检查后正常交接原owner；不强杀后台或Chrome，不重发未知请求。

## Retired HTTP-side TTL writers

The investigation found that the old HTTP watcher moved live attempt files, cleared claimed bindings and requeued submitted reviews based only on age. These actions violate the active original-receipt and sole-owner rules. The user requested a full repair. The original watcher was stopped normally; these legacy writers now only delegate maintenance to the registered owner. Original script bytes and hashes are retained in this task report.

A displaced original review receipt may be restored by the sole owner only when target, unique formal URL, complete prompt, frozen packet files, source/card versions, archived bytes and stable full DOM answer all match. A claimed or submitted replacement blocks restoration. The old receipt is copied byte-for-byte, the original job folder is restored transactionally, and only unclaimed duplicate preparation bindings are removed. Auto folders remain archived. No request is resent, no sender/time/model is invented, and no scientific score or FIFO arrival is rewritten.

2026-10-23：核验媒体目录新增物理准备文件夹指纹，防止同一核验ID的重排候选覆盖原冻结PDF。已发送旧材料仅可从原ZIP按每文件及整体指纹恢复到独立verified-inputs视图；旧损坏字节、原packet、实际提示和回执均保留，不生成新输入或重发。

2026-10-23现场交接暴露另一项阻塞：原主循环在queue.select全库补选时发生database is locked，并在进入页面巡检前退出本轮。补选迁至现有MaterialProducer第0工作线程，完成后60秒节流，单独记录状态/错误；浏览器主循环只读其上一完整结果，不新建线程或连接，扫描失败不跳过原页面观察/收取。
