# 手动打开GPT后的页面池恢复

2026-10-07：专用Chrome退出后重新打开仅有新target_id的空白GPT主页，旧页面池仍保留旧ID，原服务无法获得实际ready页。

用户点击article/open_gpt.command后，现在由pipeline.web_pool_open读取现有浏览器，不创建任何页面。仅唯一已打开空白GPT主页、无用户消息/回答/草稿通过初核，写入本机gpt-page-adoption.json请求。常驻池再次实机核对，排除已提交/不确定的本target账本及busy/needs_inspection池记录，才登记ready_blank。旧ID和未收取请求不释放、不删除、不重发。多空白页或有草稿/历史则保留待核对，不盲目选择。

页面池实时ready/busy数量只统计当前浏览器存在的target_id，并包括ready_blank，消除旧ID虚报可用页。显式打开入口原本可以由用户启动Chrome，这项修复没有给常驻任务新建或补开Chrome的能力；后台DOM与no_defaults、既有模型/High身份守卫保持。

共享web_gpt代码与公开接口不变；只修改paper消费端和article本项目打开入口。7项离线回归验证空白主页、历史/草稿/其他通道拒绝、已发送/未知账本及busy条目保护。实机登记与原任务发送情况见data/interface_changes/gpt-page-reopen-20261007.json。
