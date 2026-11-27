"""Read-only HEAD connectivity: no CDP, cookies, signature, ZIP or model send."""
import json,subprocess,time
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser.original_upload_http1 import system_proxy,error_evidence
proxy=system_proxy(subprocess.run(['/usr/sbin/scutil','--proxy'],capture_output=True,text=True,check=True).stdout)
results=[]
with sync_playwright() as pw:
 for route in ('direct','original_system_proxy'):
  options={'ignore_https_errors':False}
  if route=='original_system_proxy' and proxy:options['proxy']=proxy
  api=pw.request.new_context(**options)
  for host in ('sdmntprnznorth.oaiusercontent.com','sdmntpraustraliaeast.oaiusercontent.com'):
   started=time.monotonic();row={'route':route,'host':host,'method':'HEAD','proxy_configured':bool(proxy) if route!='direct' else False}
   try:
    response=api.head('https://'+host+'/',timeout=8000,max_retries=0,max_redirects=0,fail_on_status_code=False)
    row.update(status=response.status);response.dispose()
   except Exception as exc:row.update(error_evidence(exc))
   row['elapsed_seconds']=round(time.monotonic()-started,3);results.append(row)
  api.dispose()
Path(__file__).with_name('network-route-probe.json').write_text(json.dumps({'scope':'unsigned HEAD only; no materials or model request','results':results},indent=2)+'\n')
print(json.dumps(results))
