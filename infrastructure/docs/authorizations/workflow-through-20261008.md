# 常驻文献工作流（2026-10-07）

主目录文献拉取和网页版制卡常驻，退出任务面板不停止服务；登录 macOS 后由两个 LaunchAgent 启动，异常退出自动恢复。全部本地模型仍保持用户暂停，旧三轮循环及其自动检查已停用，历史材料保留。

每分钟根据可读取、身份与范围有效的下载原文重新计算约30%累计目标。按主题词、已有可信相关性评估、期刊优先级、引用和年份排序，元数据精选不等于科学新颖性认证。已有卡片、人工决定与待核对身份不覆盖；新下载文章随目标增长补充入队。

每篇仅使用净化原文PDF、220dpi完整页面视觉PDF、全文文字层/空白字段结构/通用制卡规则。先GPT网页；附件或使用额度限制、站点断网时改用Qwen国际站Qwen3.8-Max＋原生思考。GPT与Qwen各最多20页，计入其他项目的相同网站页面；上传、设置和剪贴板共用全局锁，回答等待并行。原账户实际额度仍以网站为准。

额度提示含明确时间时保存真实恢复时间，到时重新探测GPT；无时间仅定时探测，不冒充网站刷新时间。两个站点都不可用时等待冷却。只有实时证明未发送的原文才可跨站重试；提交不确定的任务保存URL和诊断待核对，不重复发送。

完整网页回答先保存原始正文、材料哈希、真实设置和唯一会话URL再关页；错误页先保存诊断再关闭，只操作本任务创建页。结构不合格标failed，不伪造科学验收，不无限重试。已提交但网络丢失的页面同样归档关闭，保留原URL待核对。关页失败记录异常，不因此重发。

结构完整卡片保存至data/deep_read/<paper-id>/card.json，同目录保存source.pdf及pages视觉原图，工作台通过实际card_path展示，包含表格证据，不再依赖旧read/app/workspace路径。科学核验与生产合同均标未完成；没有自动评分、三轮循环或85分验收声明。

共享任务面板只读读取paper拉取/网页制卡、question研究生成及配置中的项目状态，常驻服务无任务时仍显示。运行入口按实际项目扫描；隐藏面板自启动、旧资料卡/模型/评审入口与归档副本，open_gpt固定最后。资料卡统一使用“启动文献工作台.command”；配置见config/task_panel_projects.json。

管理：python -m pipeline.resident install/status --config config/first_round.json。网页版暂停：.venv-web-feedback/bin/python -m pipeline.web_card_service stop；永久停用请同时设置web_cards.enabled=false。拉取暂停沿用fetch-control.json，两个服务均尊重持久暂停。

验证：40项共享接口隔离回归、22项队列/切换/关页/面板/暂停回归、9项工作台访问回归、Swift类型检查和网页脚本语法检查已通过。真实运行状态见data/resident_workflow/20261007/activation.json及各服务状态文件；科学生成质量尚未验收。

新增local.paper.web-tab-watch常驻服务：每60秒读取专用CDP全部标签页，分别统计GPT/Qwen（含其他项目）并显示在共享面板。超过20页显示异常，不按数量盲目关页。仅补清理拥有target_id、URL唯一且已落盘的完整回答页（再次核对哈希、实时正文与停止状态），或有明确归档错误的本任务页；正在生成、未知提交、他人页面保留。检查记录为data/web-tab-check.json。

访问验证属于需要用户操作的通道暂停，不当作普通网络或额度失败：web-channel-control.json持久manual_verification_required；保留验证页、停止该通道新提交，无冷却自动重试或验证码自动操作。用户完成验证后实机核对再恢复，未确认提交仍不得重发。

用户最新选择DeepSeek网页版。data/web-provider-selection.json记录当前选择及真实就绪状态；目前专用Chrome仍在/sign_in，state=login_required。未登录前暂停新的网页制卡提交，拉取/只读网页数量检查继续；Qwen手动验证暂停保留，不暗中换用其他模型，不重发已有不确定任务。DeepSeek模型、视觉附件和完整收取未验收，不声称已完成接入；用户完成登录后按同净化原文、动态字段和科学未核验标准继续适配与实测。

## 固定 Qwen 单窗口备用（最新）

用户授权持续生成，GPT做不了就用Qwen。当前 GPT 优先；已明确的附件配额或网络不可用时，复用 data/qwen-window.json 的固定target_id，原生新建会话，不新开Qwen页。每次1篇，Qwen3.7-Plus/思考。上一会话URL、落盘回答哈希、实时正文和停止状态一致才允许下一篇；正式原始回答保存后保留窗口，定时清理跳过复用页。验证码、双回答或异常归属保留核对，可能已发送不跨通道重发。两次单窗口合成测试（第二次含PDF/JSON/PNG）通过，不等于真实科学质量已验收。原约30%精选、人工保护、本地模型暂停、DeepSeek暂停规则继续有效。

## 总页数20与后台操作（最新）

用户要求所有页总数20，操作不切换屏幕和光标。专用浏览器创建前共享锁内统计全部页面，总上限20；GPT并发20、Qwen固定窗口串行。paper消费端GPT直接DOM fill、文本一致核对、单次点击与回执检查，不调用系统剪贴板或bring_to_front；Qwen复用也不调用前台切换。后续创建使用CDP background=true。普通DOM操作不会移动真实鼠标；网站真人验证和操作系统文件/权限确认仍需人工处理，程序暂停不模拟绕过。服务重载时确认已发送的原target单独继续收取，不重发；其他归属不确定历史仍保留。

## 保持Chrome隐藏的实测修正

Chrome普通Target.createTarget(background=true)实际仍取消应用隐藏；hidden=true目标为other且当前Playwright不能正常接管。现改background_no_create=true：只复用gpt-window-pool.json中本任务已核对的页面，收取后保留并原页导航新会话，不创建新标签；页池忙时排队，总数仍最多20，实际并发由现存页池决定。专用浏览器零页面时等待人工打开，不自动恢复可见窗口。实测真实复用导航/上传期间Chrome hidden=true、active=false。GPT临时local-chatgpt URL转正式URL，仅在原target及含唯一材料标识的完整原提示一致时补收；不因URL变化盲重发。

## 页面池执行链路修复验收

后台页面池现在由pipeline.web_card_pool单一常驻CDP连接协调，连接使用no_defaults=True，不重复修改用户浏览器配置。以原target、唯一材料标识、完整提示及正式URL识别当前轮；原始回答稳定完成后保存hash，科学结构发布与页面释放分开，JSON非法反斜线仅另存语法规范化副本。页面池空白不能证明原请求结束：未出现当前用户消息或已有submitted/submission_started记录时保留待核对，不释放或重发。GPT后台设置菜单显式DOM点击/Escape关闭，输入与发送DOM操作，不占剪贴板/真实鼠标。模型身份核验保持。实机从3份正式卡片补收至11份并在原页生成下一篇，scientific_verified和production_contract_complete仍false；历史失败/未知请求不作为成功。Qwen原固定页缺失，备用仍不可用，不擅自新开。后台菜单13项、消费端28项回归通过；全局联动检查另见tools最新结果。

2026-10-07队列耗尽核对：服务未被用户暂停；209个入选任务含失败/待核对，queued=0导致空闲，不等于209篇完成。恢复87个旧传输故障任务，所有已有provider attempt均明确not_sent/deferred；保留已发送、submission_started、归属不确定及确定性结构失败，不自动重发。恢复证据data/unsent-transport-recovery-20261007.json。当前未扩大选择范围。
随机五篇真实卡片浏览器图片加载检查见data/random-card-image-audit-20261007.json；检查在独立headless浏览器及临时只读工作台进行，不启动模型或拉取。图片加载通过不等于科学图式关联核验通过；网页卡片保留整页证据图，不声称完成单图裁切。

旧卡片迁移图片修复：工作台/api/card使用card_image_asset解析当前卡片目录内的真实文件；原绝对路径已迁移时，仅允许按完全相同卡片目录名保留的相对后缀解析，拒绝目录外路径、无匹配路径及缺失文件。不改旧card.json和科学内容。用户指定的Confinement of Long-Lived Triplet Excitons卡片独立无界面浏览验证见data/relocated-card-image-audit-20261007.json。

卡片空白布局修复：网页卡片pages/Pxxx.png整页证据默认折叠、同页仅出现一次，其余图式提供同页图像链接；旧独立裁图仍直接显示。图片采用自适应宽高的块布局。保留原始图片及科学内容，不通过裁剪掩盖证据。真实新旧卡片验证见data/compact-card-layout-audit-20261007.json。

用户最新授权：检查当前卡片库，所有非GPT网页版卡片重做。20261007T210920清点53篇，43篇已有ChatGPT网页正式会话来源、10篇非GPT（9本地/1Qwen），无未登记卡片。10篇原文与全部旧图式/卡片已备份至data/gpt_card_reworks/20261007T210920/manifest.json，旧科学答案不作为新输入；该10篇显式优先任务不受30%新文献精选限制。已有人工决定的3篇只落盘独立GPT候选包，7篇备份后替换当前库路径/版本；任何旧卡片哈希变化阻断替换。重做仅使用ChatGPT网页，Qwen备用不用于本组，其他旧模型暂停不变。不会把重做启动宣称为完成或科学验收。

拉取执行时间：fetch_attempt_times按job_id/attempt保存真实领取开始及离开running的结束时间，数据库触发器兼容未重启的旧worker。任务面板常驻文献拉取行显示上一篇结束，活动文献行显示开始，已结束列表及工作台显示最近20次开始/结束，统一上海时间。记录下载/备用下载/导入，不把主题扫描算上一篇下载；历史开始缺失标未记录，不用入队时间伪造。延期、失败与成功均属尝试结束，状态分别显示。并行结束时间按最近实际结束排序。
