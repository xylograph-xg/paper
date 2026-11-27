# 种子任务状态与全量参与澄清（2026-10-25）

本轮只读核对活动 Catalog、原回执、原追踪与磁盘卡片，再通过公开控制关闭手选独占。不启动网页后台、不解除用户暂停、不新建 CDP 连接或模型请求。准确采样时间与文件指纹见[证据](20261025-seed-status-evidence.json)。

## 当前范围与运行状态

- Catalog种子971篇，其中原文available 970篇；唯一未有制卡任务者为缺原文的Erratum，不绕过来源/范围保护。其余970篇都有原制卡任务。
- 当前原制卡任务：completed 685、queued 118、needs_inspection 139、failed 28。completed只是生成处理完成，旧卡与后继重做并存，不能据此算科学成品。
- 制卡、核验、修正分别在上海时间10:38:12、10:38:06、10:37:16持久暂停；原所有者state=stopped，launchctl未见网页所有者/watcher PID。拉取控制未暂停、keeper进程在，但原手选独占曾叠加阻止新发现/拉取。
- 手选独占原enabled=true只放行5篇manual_seed_roots。按本次澄清关闭，实查971篇种子均allowed=true，965篇非手选种子已有任务，手选种子第一顺位保留。没有新建队列、重排FIFO或恢复暂停。

## 精读库展示与严格成品追踪是两个口径

按当前Catalog.page精读库的原SQL条件只读复算，符合展示条件的全库157篇，其中种子97篇、手选根种子0篇；97篇种子均未读。157篇的磁盘卡片hash、当前原文hash及路径均与派生索引一致。由此不能把“手选区0篇”解释为“全部种子没有可读成果”。精读库要求当前版本修正链、同原文、完整科学通过，**不检查production_contract_complete**。手选/普通归属按manual_seed_roots及lineage划分，不等同于当前seed标志。

下面的0仅指追踪器要求的“科学与生产合同都完成”，并非精读库展示数量：

种子965篇登记card_path，965份经公开旧路径解析器读取正常（其中2份为旧路径）；965份中186份meta.scientific_verified=true，但production_contract_complete=true为0，两者同时通过为0。186是磁盘元数据计数，未逐篇重做原文科学审计，也不以历史passed行数替代当前版本验收。

存在确定的生产合同衔接缺口：review/card_review_queue.py在科学通过的元数据发布中仍固定写production_contract_complete=False；当前cards/review/correction链没有将其验收为True的生产写入出口，而seed_focus.monitor明确要求科学及生产合同都为True才结束追踪。这使追踪中的严格成品标准不能仅靠现有科学通过分支达成；该缺口不是精读库157/97条展示记录的过滤条件。当前卡片/报告不据此批量改True，不能把结构通过代替生产合同验收。本轮定位这一缺口，未新增生产合同定义或验收器。

五篇手选根种子仍没有三版择优成品：

| 文献 | 原证据所示阻塞 |
| --- | --- |
| Confinement of Long-Lived Triplet Excitons | 当前制卡needs_inspection，原请求未完整收取；旧修正后核验又有提交回执/正式URL未确认。 |
| Physics-informed machine learning for spectrum prediction in phosphorescent OLEDs | 原请求缺完整收取证据，禁止据换页或时间重发。 |
| Machine-Learning Predictions of Photoluminescence ... | 服务中断后原请求未收齐，尚未进入新独立轮次。 |
| Invariant Risk Minimization | 后续原请求未完整收取；追踪最后实质进展在10月23日，不是持续生成数日。 |
| Multiagent Data Mining ... | 已有一版候选核验93.55，但verdict=revise且major=1，不符合科学通过；当前第2轮queued，最后技术错误为导航超时。旧核验87.65同样含major，不是成品。 |

原追踪5篇全部超过3小时无实质进展，心跳/重启不刷新进展。本轮没有实时网页观测，陈旧run.state=generating不能当作当前实际生成。

## 本轮修改与保护

唯一运行控制修改为seed-focus-control.enabled=false，保留手选全环节排序。10份暂停、标签及通道控制文件前后SHA-256相同。更新根AGENTS对应条目与[本轮授权](../infrastructure/docs/authorizations/20261025-all-seeds-manual-priority.md)，全部种子参与不扩大原五篇三版实验。

用户今天的制卡/核验/修正暂停仍有效。本轮没有发送请求、强杀/重启服务、改写卡片/科学报告或解锁未知回执。

## 验证

公开API实查全部种子准入、手选排序及10份受保护控制字节不变通过。make check通过（15组件、262源码、376公开出口），全局update与check_links通过。

make test执行2764次、2553个独立用例：0 failure、1 error，仅reports.test_all_registered_bytes，原因是本轮给reports/README.md新增两份报告链接后，README本身的登记SHA未同步。业务及准入相关测试没有失败；保留[完整日志](../infrastructure/data/seed-status-tests-20261025.log)。本轮报告定稿后同步两份新增报告及本轮明确修改的README登记SHA，不刷新任何历史科学报告指纹；受影响的reports项目5项复跑结果见[报告回归日志](../infrastructure/data/seed-status-reports-tests-20261025.log)。不将该全量首次结果冒称全通过，也不将软件检查冒称恢复运行或新增成品。
