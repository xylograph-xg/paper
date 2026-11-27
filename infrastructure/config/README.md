# 集中配置接口

主配置、控制schema、评分/制卡通用规则、回退及网页依赖锁、核验样本/循环政策、面板多项目配置。

## 为什么保留、为什么这样选择

一个主配置来源避免四任务授权、站点预算与20页窗口规则漂移。保留真实文件供原子写入；不同子项目只读取自己所需字段。静态配置与持久暂停仍独立，配置enabled不表示可恢复任务。

## 接口与内容

接口声明见 [interface.json](interface.json)。正式调用入口是 `core.api`；文件型接口保持原JSON/哈希合同。

- [control.schema.json](control.schema.json)：当前配置或规则；由对应实现校验，不覆盖持久暂停。
- [first_round.json](first_round.json)：当前配置或规则；由对应实现校验，不覆盖持久暂停。
- [journal-levels.json](journal-levels.json)：失败 DOI 清单的期刊相对水平（1–5）与综合排序权重；用户可编辑，不是 JCR/中科院分区官方数据。
- [pdf-retrieval-requirements.lock](pdf-retrieval-requirements.lock)：当前配置或规则；由对应实现校验，不覆盖持久暂停。
- [policy_specification.json](policy_specification.json)：当前配置或规则；由对应实现校验，不覆盖持久暂停。
- [review-cycle-policy.json](review-cycle-policy.json)：当前配置或规则；由对应实现校验，不覆盖持久暂停。
- [review_samples.json](review_samples.json)：当前配置或规则；由对应实现校验，不覆盖持久暂停。
- [task_panel_projects.json](task_panel_projects.json)：当前配置或规则；由对应实现校验，不覆盖持久暂停。
- [web-feedback-requirements.lock](web-feedback-requirements.lock)：当前配置或规则；由对应实现校验，不覆盖持久暂停。
- [web_card_rules.md](web_card_rules.md)：当前配置或规则；由对应实现校验，不覆盖持久暂停。

## 边界

本次不修改first_round.json、control.schema.json的现有值及运行控制。

源码当前接口与删除理由见 [项目地图](../../WORKFLOWS.md)。

2026-10-14：`first_round.json`的`card_correction.priority_passed_first`为布尔值，默认false，本轮用户授权启用true。它仅选择同原文完整通过报告关联的修正优先组及后继核验，不构成外发许可、不解除暂停、不调整固定页数或评分。

2026-10-14：`automatic_issue_handling.owner_supervision.enabled`为布尔值，当前true；`stale_seconds`为不低于300的整数，当前300。它让原HTTP watcher自动监督原网页所有者，仍须准确入口、原PID/令牌、暂停及已验收源码指纹核对；不表示允许启动新服务或恢复用户暂停。

2026-10-15：`web_cards.shared_window.health_repair.failed_upload_recovery_enabled=true`仅对已授权、有同target原PUT终止证据和结束未发送回执的失败上传启用原两轮归档恢复，不取消一般活跃上传保护。`web_cards.original_put_http1`默认缺省关闭；本轮enabled=true、epoch=20261015-system-proxy-one-original-put、max_materials=1，仅下一合法新材料原始PUT一次对照，SDK1.63.0、TLS验证及持久意图强制防重。禁用不删除意图；调大max_materials不扩大名额，新增epoch只允许同一已授权修复中的另一合法新材料，不能重试已有意图。24MB软目标是新整页视觉材料的工程目标，不是网站硬限；60MB硬预算继续有效。详见[授权](../docs/authorizations/20261015-twenty-page-upload-recovery.md)。

`promote_on_native_success=true`要求本epoch真实PUT2xx、fulfill且原生完整结算后才对后续新材料沿用同一已验证原代理传输；每材料独立持久防重，未知旧材料跨epoch不能再外发。细化见[原代理传输](../docs/authorizations/20261015-system-proxy-upload-fix.md)。

`workbench_passwordless` 为文献工作台访问配置，缺省为 false，主配置为 true。它使用本机回环与已登录用户的私有 Tailscale Serve 路由，写请求仍校验请求来源。
