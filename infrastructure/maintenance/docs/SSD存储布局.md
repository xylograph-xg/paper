# 主文献库SSD存储布局

2026-10-07，用户授权整理：原文、展示图片和资料卡在SSD，数据库和运行状态在电脑内部磁盘。

## 目录

- `/Volumes/ssd-1t-1/paper-library/assets/`：下载原文，沿用原目录。
- `/Volumes/ssd-1t-1/paper-library/cards/`：原data/deep_read正式资料库，含card.json、原文、图像、来源及原库内历史卡片。
- `/Volumes/ssd-1t-1/paper-library/web-inputs/`：上传用PDF、220dpi页面图片、候选卡片及已有大诊断图片。原web_cards中的同名路径保留符号链接。
- 本机data/catalog.sqlite3：主Catalog、文献索引、文件路径与任务队列。
- 本机data/web_cards：packet、context、提示、提交记录、原始回答、URL、输入哈希、历史attempt及轻量链接。
- 本机其他控制JSON、锁、日志：服务控制、队列/通道状态、网页池、运行记录。旧隔离实验保持原状态，不启动或重制。

`data/deep_read`保留目录链接，兼容旧card_path、image_path、历史评审及重做授权路径。不改写已有卡片科学内容或哈希。主配置studio_library_root直接指向SSD正式库，web_cards.media_root指定SSD材料目录；未来准备直接写入SSD，本机只留附件链接与收据。

迁移工具 `python3 -m pipeline.organize_ssd` 逐文件验证哈希后再移除本机副本；仅针对主正式库及主web_cards大附件/候选卡片，不迁移数据库。迁移证据在data/ssd-organization-20261007.json，原卡片哈希清单在data/ssd-card-hashes-before.json。该工具用于本次受控整理，运行前须停止网页写入与维护，不能当作在线维护命令。

网页版池在SSD未挂载时记录waiting_storage，不新提交、不回退本机材料目录。已有保存原始回答保持；非池发布也先验证挂载。用户暂停状态优先，整理没有改动暂停开关、模型选择、科学规则或外发范围。网页访问仍受既有登录、CDP、验证与提交归属守卫约束。

每10分钟保留策略仍只对可证实完成的材料去重与清理视觉PDF；同时删除SSD临时实体及本机链接，保留正式库、输入指纹、原始回答。未完成/不确定任务的大附件继续保留在SSD等待核对。

拔盘会暂时阻止卡片图片/原文读取；重新挂载相同名称后旧路径恢复。移动或更换SSD时须一起迁移cards和web-inputs并更新配置/链接。数据库与SSD材料都需要正常备份。

共享web_gpt接口没有修改；paper内部修改准备参数、消费者路径与挂载保护。验证及待核对事项见data/interface_changes/ssd-storage-20261007.json。
