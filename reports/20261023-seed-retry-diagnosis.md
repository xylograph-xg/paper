# 五篇手选种子停滞与重试核对（2026-10-23）

五篇并非同一种失败。两项明确未发送的技术失败仍受共享网页入口的旧两次上限约束；三项已发送请求未有完整回答落盘，原target已经被历史换页流程替换。持续追踪只保存证据和报警，没有自动补齐这两类恢复出口。

| 种子 | 原记录与真实阻断 |
| --- | --- |
| Triplet Excitons | 当前原attempt为submitted、send_click_started=true。原target已在repair cc9032b67b0e63867a3dae30d330f1ed归档替换；当时health为unknown，requeue_allowed=false，没有完整原回答。 |
| Multiagent | 当前attempt为not_sent、send_click_started=false、lease_preflight失败。分配target仍显示另一篇已保存的旧会话，守卫拒绝在证据不一致时导航。重试扫描随后被external_retries=2拦截。 |
| OLED spectrum | 原attempt为submitted、send_click_started=true。原target在repair 5096b748ae1a19156da4b2c0909a91d0替换；归档中另一个新未发送attempt不能终止该原请求，health仍为unknown，requeue_allowed=false。 |
| Photoluminescence | 原attempt为submitted。repair 416b120f6473f7db1dd92a24669cb79b记录terminal_no_response后换页，原回答不存在，且明确requeue_allowed=false。换页不是重新提交授权。 |
| Invariant Risk Minimization | 当前attempt为not_sent、send_click_started=false；上传诊断write_failed、retryable_upload=true，底层TimeoutError。ZIP约12.6MB，低于50MiB限制；不能据此声称过大或已定位全部网络原因。重试扫描被external_retries=2拦截。 |

## 根因及本轮修复

2026-10-19已授权根种子技术失败不因重试上限退出。旧同步`process_job`存在快车道分支，但正式使用的共享页`web_card_pool`将发送前失败落为failed，再由`web_card_retry.run_once`扫描；该入口仍无条件应用两次上限。这是实现遗漏，不是用户未给技术重试权限。

本轮在唯一重试实现`cards/web_card_retry.py`补上根种子例外：根登记`input_hash`必须等于任务原文hash，当前所有回执都必须明确not_sent/deferred且send_click_started=false，才使用独立technical_retries。外发/结构重试external_retries原值保留；5/15/60分钟退避，后续保持60分钟，不随第几百次失败无限增长。CAS事务内再次核对根身份、原文及人工保护。原材料、历史请求、页面、暂停、额度、归档及seed-tracking守卫不放宽。

另三项没有因本轮改动获得重发许可。已发送、未知及完整回答结构失败不能使用上述例外；原请求收取与科学验收仍分别记录。长期停滞计时代表无实质进展，不代表连续生成了这些小时。

## 验证与现场

验证、原始诊断摘要及正常后台交接记录保存在[20261023-seed-retry-validation](20261023-seed-retry-validation/)。排队、实际重新提交、原回答收取和成品完成分别以实际回执为准。

## 同日继续核对：无附件额度仍未执行

原后台实时submission_channel为ready，20个固定页快照均未见quota。IRM已于上海时间14:07完成原附件上传并提交，后续观察到原会话终态但没有正文回答，原请求保留，不能将提交说成卡片完成。Multiagent在修复重试计数后实际重试两次，仍回到同一个旧会话页，之后进入技术退避。

进一步确认：该页快照记录了站点加载失败（Unable to load site），prepare_home因此拒绝导航；但health的已保存回答分支未将这种站点错误纳入可修复错误，所以始终completed_saved且replace_allowed=false，仍被分配任务。现补齐相同错误识别；必须原完整回答、URL及提示仍一致，稳定实查且没有上传/生成/新草稿/登录/额度保护，才由唯一原所有者按既有完整归档及CAS流程替换，未知请求不新增发送许可。

新的检查与现场证据见[启动核对目录](20261023-seed-page-start-validation/)。原额度/暂停记录不为启动而清空；原重试次数保留。
