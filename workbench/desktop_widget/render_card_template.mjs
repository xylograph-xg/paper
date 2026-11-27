// Render the readable template with the same local Markdown parser as the workbench.
import {readFileSync, writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {marked} from '../pipeline/vendor/marked.esm.js';

const source = new URL('../docs/文献卡片模板.md', import.meta.url);
const destination = new URL('../docs/文献卡片模板.html', import.meta.url);
const markdown = readFileSync(source, 'utf8');
const hash = createHash('sha256').update(markdown).digest('hex');
const body = marked.parse(markdown);
const html = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>文献卡片模板</title>
<!-- Generated from 文献卡片模板.md; source-sha256: ${hash} -->
<style>
:root{color-scheme:light dark;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;color:#26323c;background:#f5f7f9}
body{margin:0;padding:28px 24px 48px;line-height:1.85;font-size:15px}
main{max-width:860px;margin:auto;padding:28px 32px;background:#fff;border:1px solid #dce3e8;border-radius:12px}
h1{font-size:28px;margin:0 0 16px}h2{font-size:21px;margin:32px 0 14px;padding-bottom:8px;border-bottom:1px solid #e2e8ec}h3{font-size:18px;margin-top:26px}
p,ul,ol{margin:12px 0}li{margin:7px 0}table{width:100%;border-collapse:collapse;margin:18px 0;table-layout:fixed;overflow-wrap:anywhere}
th,td{padding:10px 12px;border:1px solid #dce3e8;text-align:left;vertical-align:top}th{background:#edf3f7;font-weight:600}
code{font-family:ui-monospace,SFMono-Regular,monospace;font-size:.9em;background:#eef2f5;border-radius:4px;padding:2px 4px;overflow-wrap:anywhere}a{color:#21669a}
@media(prefers-color-scheme:dark){:root{color:#e3e9ee;background:#171c22}main{background:#20262d;border-color:#3a4652}h2,th,td{border-color:#3a4652}th{background:#2c3743}code{background:#303a44}a{color:#8ac4ef}}
@media(max-width:600px){body{padding:12px}main{padding:20px 16px}th,td{padding:8px}table{font-size:13px}}
@media print{body,main{padding:0;background:#fff;color:#000;border:0}h2,h3{break-after:avoid}tr{break-inside:avoid}}
</style></head><body><main>${body}</main></body></html>
`;
writeFileSync(destination, html, 'utf8');
process.stdout.write('已生成文献卡片模板.html\n');
