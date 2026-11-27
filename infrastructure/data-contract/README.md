# 正式运行存储接口

本机运行目录为 `~/process/paper/data/`，旧运行目录通过符号链接访问；反向索引位于 `~/process/paper/reverse-index.json`。版本管理的说明、接口与审计文件由 `infrastructure/data-contract/` 保存。

本目录属于infrastructure，保存唯一Catalog数据库、持久控制、队列/attempt/固定页账本、原文与卡片索引、冻结材料、原回答、人工决定和选定审计证据。

选择共享事务存储，是为了让拉取、制卡、核验、修正核对同一真实文章及当前版本，避免复制数据库或突破原子领取、暂停和未知请求保护。此次只重命名物理目录，数据库仍是同一文件；旧冻结输入、回执和控制JSON不重写，通过core公开路径接口解释旧绝对路径。

接口见[interface.json](interface.json)，业务使用core.api。完整内容：catalog.sqlite3（身份和原子队列）、*-control.json（持久暂停/授权）、control-events.jsonl（真实操作证据）、shared-gpt-window.json（唯一所有者与固定槽位）、web_cards与card_reviews（冻结输入/请求回执）、quality_reviews（独立核验原报告）、audit_index（不可变指纹清单）、workflow_versions（历史源码合同指纹/源码版本证据）。其余运行日志、缓存和临时材料由相应组件管理。

用户已明确不保留数据备份；backups、recovery-backups、resident-backups副本已删除，数据备份创建禁用。原始业务数据不能当作备份删除。Git只保存选定audit_index、README和interface；数据库、正文、冻结输入和私有控制继续ignore。

[项目地图](../../WORKFLOWS.md)列出完整归属。

`original-put-http1/<epoch>/reservation.json`先登记下一材料，未观察到完整PUT也不改选其他材料；同目录`intent.json`是一次原PUT对照的持久意图和真实响应摘要：独占创建、fsync后才传输，任何已有/未知意图不得重放；含job/target、ZIP/请求hash、主机、大小、耗时/状态，绝不保存URL签名、认证头或正文。它属于运行证据，不能删除它来重新获得名额，也不是原文数据备份。

通过本epoch真实原生结算后，后续新材料意图保存在`original-put-http1/material-<material_key>/`，并非给旧意图换epoch重试；`web-upload-network-history/`保存原owner网络投影，事件保留原时间、owner及历史标签。这些均是技术诊断/防重证据，不是业务数据备份。
