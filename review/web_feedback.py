"""Serial, explicit web_gpt review jobs; never retry an uncertain submission."""
from __future__ import annotations

import argparse
import fcntl
import json
import re
import sys
from datetime import datetime, timezone
from core.api import paths__WorkspacePath as Path

from .card_evaluation import ROOT, assess_feedback, digest


def save_json(path, value):
    from core.api import services__atomic_json as atomic_json
    atomic_json(path,value)


def parse_feedback(answer, kind):
    text = answer.strip()
    text = re.sub(r'^JSON\s*(?=\{)', '', text)
    if text.startswith('```'):
        lines = text.splitlines()
        if lines[-1].strip() != '```':
            raise ValueError('评审代码块未结束')
        text = '\n'.join(lines[1:-1])
    # The visible renderer injects citation tokens with unescaped quotes into
    # otherwise valid JSON strings. Preserve their indices without accepting
    # arbitrary JSON repairs; the unmodified answer remains in feedback-raw.txt.
    text = re.sub(r':chatgpt-content-reference\{index="(\d+)"\}',
                  lambda match: '[citation ' + match.group(1) + ']', text)
    def unique(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('评审 JSON 字段重复：'+key)
            result[key]=value
        return result
    feedback = json.loads(text,object_pairs_hook=unique)
    if not isinstance(feedback, dict):
        raise ValueError('评审必须是 JSON 对象')
    return feedback, assess_feedback(feedback, kind)


def packet_files(run_dir, sample):
    if sample['kind'] not in ('image_heavy','equation_heavy','mixed'):
        raise ValueError('评审类型不合法')
    directory = (run_dir / sample['kind']).resolve()
    if not directory.is_relative_to(run_dir.resolve()):raise ValueError('评审目录越界')
    hashes=sample.get('input_hashes',{})
    if set(hashes)!=set(sample['packet_files'])|{'prompt.txt'}:raise ValueError('缺少完整冻结指纹；旧材料不自动补签')
    for name,h in hashes.items():
        path=(directory/name).resolve()
        if path.parent!=directory or digest(path)!=h:raise ValueError('评审冻结材料变化：'+name)
    paths = []
    for name in sample['packet_files']:
        path = (directory / name).resolve()
        if path.parent != directory or not path.is_file():
            raise ValueError('评审附件缺失或路径越界')
        paths.append(path)
    if not any(p.name == 'paper-review.pdf' for p in paths):
        raise ValueError('缺少已处理下载水印的评审 PDF，禁止上传原始 PDF 替代')
    pdf = directory / 'paper-review.pdf'
    if digest(pdf) != sample['review_pdf_sha256']:
        raise ValueError('评审 PDF 指纹已变化')
    if len(paths) > 10:
        raise ValueError('单轮附件超过 10 个')
    return paths


def parse_or_reformat(gpt,answer,kind,folder,attempt,attempt_path,timeout):
    try:
        return parse_feedback(answer,kind)
    except json.JSONDecodeError:
        # A completed response with broken JSON can be reformatted in-place.
        # No attachments, no new assessment, and only one follow-up.
        score_block=re.search(r'"scores"\s*:\s*(\{[^{}]+\})',answer)
        verdict=re.search(r'"verdict"\s*:\s*"(pass|revise|cannot_evaluate)"',answer)
        if not score_block or not verdict:
            raise ValueError('原评审评分/结论无法可靠读取，禁止自动改写格式')
        original={}
        for field in ('sample_kind','scores','missing_inputs','issues','verdict','strengths','priority_fixes'):
            matches=list(re.finditer(r'"'+field+r'"\s*:\s*',answer))
            if not matches:
                if field in ('strengths','priority_fixes'):continue
                raise ValueError('原评审决定性字段缺失，禁止自动改写格式')
            if len(matches)!=1:raise ValueError('原评审字段重复，禁止自动改写格式')
            try:original[field]=json.JSONDecoder().raw_decode(answer[matches[0].end():])[0]
            except json.JSONDecodeError as exc:raise ValueError('原评审问题或证据无法可靠读取，禁止自动改写格式') from exc
        attempt['format_followup']=True
        attempt['state']='format_followup_started'
        save_json(attempt_path,attempt)
        corrected=gpt.ask('仅修正上一条评审的 JSON 格式，不重新评价，不改变评分、问题、证据与 verdict。'
            '输出一个完整的 json 代码块，字符串内部引号必须转义，来源使用普通页码文字，不使用网页原生引用。',
            answer_timeout=timeout)
        (folder/'feedback-format-retry-raw.txt').write_text(corrected)
        stop=gpt.page.locator('button[data-testid="stop-button"], button[aria-label="停止"], button[aria-label="Stop"]')
        if stop.count() and stop.first.is_visible():
            raise RuntimeError('格式修正仍在生成，禁止接受部分结果')
        result=parse_feedback(corrected,kind)
        if any(result[0].get(key)!=value for key,value in original.items()):
            raise ValueError('格式修正改变了原评分、问题、证据或结论，禁止接受')
        return result


def session_factory(provider="chatgpt", **options):
    from article.api import gpt_session
    return gpt_session(provider=provider, **options)


def require_unique_review_conversation(folder, conversation_url):
    """Never attribute a conversation already claimed by another packet."""
    if not isinstance(conversation_url, str) or not conversation_url.startswith('https://chatgpt.com/c/'):
        raise ValueError('评审缺少正式会话URL，保留回答待核验')
    own=(Path(folder)/'web-attempt.json').resolve()
    for path in (ROOT/'data/quality_reviews').glob('*/*/web-attempt.json'):
        if path.resolve()==own:continue
        previous=json.loads(path.read_text())
        if previous.get('conversation_url')==conversation_url:
            raise ValueError('评审会话已被其他材料占用，禁止接受旧报告或自动重发：'+str(path))


def require_current_legacy_control(config):
    from core.api import control__pause_decision as pause_decision
    decision=pause_decision(config,'card_review',enabled=config.get('legacy_external_review_enabled',False))
    if not decision.allowed:raise PermissionError('历史评审循环保持禁用/暂停：'+decision.reason)


def run_reviews(run_dir, kinds=None, factory=session_factory, timeout=900, manifest_path=None):
    from core.api import catalog__load_config as load_config
    from .review_ledger import authorized,catalog_for
    cfg=load_config();require_current_legacy_control(cfg)
    manifest=Path(manifest_path) if manifest_path else ROOT/'data/quality_reviews/20261005T052045Z/continuous-loop.json'
    loop=json.loads(manifest.read_text()) if manifest.is_file() else {}
    if loop.get("external_submission_blocked") is not False or loop.get("state") not in ("authorized_review","reviewing"):
        raise PermissionError("缺少有效持续外发授权；禁止连接外部评审")
    if not authorized(loop,catalog_for(manifest),manifest):raise PermissionError("持续外发授权凭证不存在或失效")
    ledger=catalog_for(manifest)
    from .review_ledger import reconcile
    reconcile(ledger,ROOT/'data/quality_reviews')
    run_dir = Path(run_dir).resolve()
    if not run_dir.is_relative_to((ROOT / 'data/quality_reviews').resolve()):
        raise ValueError('评审运行目录必须位于 data/quality_reviews')
    with (run_dir / '.review.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run_path = run_dir / 'run.json'
        run = json.loads(run_path.read_text())
        for sample in run['samples']:
            kind = sample['kind']
            if sample.get('paper_id') not in loop.get('samples',{}).values():raise PermissionError('评审样本超出本轮明确授权范围')
            if kinds and kind not in kinds:
                continue
            folder = run_dir / kind
            attempt_path = folder / 'web-attempt.json'
            if attempt_path.exists():
                previous = json.loads(attempt_path.read_text())
                if previous['state'] != 'preflight_failed':
                    # A send may have happened even if ask raised: no blind resend.
                    continue
            files = packet_files(run_dir, sample)
            prompt = (folder / 'prompt.txt').read_text()
            attempt = {
                'transport': 'web_gpt via article.api.gpt_session',
                'started_at': datetime.now(timezone.utc).isoformat(),
                'state': 'preflight',
                'files': [{'name': p.name, 'sha256': digest(p)} for p in files],
                'prompt_sha256': digest(folder / 'prompt.txt'),
            }
            from .review_ledger import reserve, update as ledger_update
            if not reserve(ledger,sample['paper_id'],sample['card_sha256'],run_dir):
                continue
            save_json(attempt_path, attempt)
            try:
                require_current_legacy_control(cfg)
                with factory() as gpt:
                    attempt['settings'] = gpt.verify_settings()
                    attempt['conversation_url'] = gpt.page.url
                    attempt['state'] = 'submission_started'
                    save_json(attempt_path, attempt)
                    ledger_update(ledger,sample['paper_id'],sample['card_sha256'],'submission_started',run_dir)
                    try:
                        require_current_legacy_control(cfg)
                        if not authorized(loop,ledger,manifest):raise PermissionError('外发授权已失效')
                        packet_files(run_dir,sample)
                        answer = gpt.ask(prompt, files=[str(p) for p in files], answer_timeout=timeout)
                        (folder / 'feedback-raw.txt').write_text(answer)
                        attempt['conversation_url'] = gpt.page.url
                        attempt['raw_sha256']=digest(folder/'feedback-raw.txt')
                        require_unique_review_conversation(folder,attempt['conversation_url'])
                        # The tool may return partial text after a timeout. Do not
                        # accept a JSON response while its generation is active.
                        stop = gpt.page.locator('button[data-testid="stop-button"], button[aria-label="停止"], button[aria-label="Stop"]')
                        if stop.count() and stop.first.is_visible():
                            raise RuntimeError('网页仍在生成，保留回答但不接受评审')
                        feedback, assessment = parse_or_reformat(gpt,answer,kind,folder,attempt,attempt_path,timeout)
                        save_json(folder / 'feedback.json', feedback)
                        attempt['feedback_sha256']=digest(folder/'feedback.json')
                        attempt['raw_sha256']=digest(folder/'feedback-raw.txt')
                        if attempt.get('format_followup'):attempt['format_raw_sha256']=digest(folder/'feedback-format-retry-raw.txt')
                        sample['feedback'] = {'file': f'{kind}/feedback.json', **assessment}
                        attempt['state'] = 'feedback_received'
                        attempt['assessment'] = assessment
                    finally:
                        try:attempt['conversation_url'] = gpt.page.url
                        except Exception as exc:attempt['url_capture_error']=type(exc).__name__
                        try:
                            gpt.page.screenshot(path=str(folder / 'web-review.png'), full_page=False)
                        except Exception as exc:
                            attempt['screenshot_error'] = type(exc).__name__
            except Exception as exc:
                # Playwright assertion errors can include a whole sidebar tree.
                # Keep the useful failure without unrelated chat titles.
                error = str(exc).split('Aria snapshot:')[0].strip()
                attempt['error'] = f'{type(exc).__name__}: {error}'
                if attempt.get('state')!='feedback_received':
                    attempt['state'] = ('preflight_failed' if attempt['state'] == 'preflight' else 'needs_inspection')
            ledger_update(ledger,sample['paper_id'],sample['card_sha256'],attempt['state'],run_dir)
            attempt['finished_at'] = datetime.now(timezone.utc).isoformat()
            save_json(attempt_path, attempt)
            run['reviewer'] = 'web_gpt (actual settings recorded per sample)'
            run['state'] = ('reviewed' if all(s.get('feedback') for s in run['samples'])
                            else 'review_incomplete')
            save_json(run_path, run)
            if attempt['state']=='feedback_received' and factory is session_factory:
                from .review_tabs import close_saved_review
                close_saved_review(folder)
            print(f"{kind}: {attempt['state']}", flush=True)
            if attempt['state'] != 'feedback_received':
                print(attempt.get('error', ''), flush=True)
                break
        return run


def main():
    parser = argparse.ArgumentParser(description='用已有 web_gpt 工具发送卡片评审材料并保存反馈')
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--kind', action='append', choices=['image_heavy', 'equation_heavy', 'mixed'])
    parser.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout 必须为正数')
    run = run_reviews(args.run_dir, args.kind, timeout=args.timeout)
    selected = [s for s in run['samples'] if not args.kind or s['kind'] in args.kind]
    if not selected or not all(s.get('feedback') for s in selected):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
