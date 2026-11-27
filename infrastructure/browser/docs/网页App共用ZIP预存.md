# 网页版与App共用ZIP预存

2026-10-08，用户授权“web gpt 也走这边”。权威打包器仍为codex_desktop_chat.bundles，本工作区默认 ~/process/app-upload-zips，可用CODEX_CHAT_ZIP_DIR配置。网页版通过web_gpt.zip_uploads源码引用，不复制实现；WEB_GPT_BUNDLE_IMPORT_ROOT配置打包器导入根。

主材料准备预存净化原文、220dpi视觉PDF、空白上下文的ZIP，原packet文件/原文哈希保留。新提交复核冻结材料后只用一个ZIP，attempt记录upload_bundle和实际prompt指纹，附通用解压/缺失输入说明。旧缓存只在允许新提交的保护检查后打包，已发送或未知attempt不改变、不重发。公开ChatGPTWeb/ask_once参数不改，files行为统一成单ZIP，失败不回退散文件；Qwen/DeepSeek不改。

75项paper与ZIP离线回归通过，权威web_gpt模型/输入/收取隔离回归另记录。本轮没有真实上传、没有重启/启动服务、没有恢复额度或暂停。真实ZIP解压、原文与视觉内容读取未验收；新代码供后续合法新提交使用，已运行进程不强制重载。科学及生产合同标志保持false。
