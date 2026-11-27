"""Bounded offline checks; source truth and semantic entailment remain unverified.

CLI accepts a formal card and its parsed original, writes a separate JSON report.
The reader attaches the report to new cards without changing scientific fields.
"""
from __future__ import annotations
from core.api import paths__workspace_root as _workspace_root

import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from functools import lru_cache
from core.api import paths__WorkspacePath as Path

VERSION = 1
ROOT = _workspace_root()
VERSIONS = {'sympy': '1.14.0', 'antlr4-python3-runtime': '4.11.1', 'mpmath': '1.3.0'}


def runtime_identity():
    """Report the actual dependency versions, including missing installations."""
    target = str(ROOT / '.deps/scientific-verifier')
    if target not in sys.path:
        sys.path.insert(0, target)
    from importlib.metadata import version, PackageNotFoundError
    result = {}
    for name in VERSIONS:
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result


class Unsupported(ValueError):
    pass


def _latex(text):
    text = text.strip().strip('$')
    text = re.sub(r'\\(?:quad|qquad|tag)\s*(?:\{\d+\}|\(\d+\))\s*$', '', text)
    text = re.sub(r'\\(?:left|right)\b', '', text)
    text = re.sub(r'\\(?:,|;|!| )', ' ', text)
    text = re.sub(r'\\(?:mathrm|textrm|operatorname|text)\{([A-Za-z]+)\}', r'\1', text)
    # Keep indices and alphabetic superscripts opaque. ANTLR otherwise parses
    # AA as A*A and TID as T*I*D. No physical meaning is inferred from the name.
    atom = r'(?:\\[A-Za-z]+|[A-Za-z])'
    script = r'(?:_\s*(?:\{[A-Za-z0-9]+\}|[A-Za-z0-9])|\^\s*\{[A-Za-z]+\})'
    def opaque(match):
        token = re.sub(r'\s|[{}]', '', match.group())
        return 'v_{' + str(int(hashlib.sha256(token.encode()).hexdigest()[:12], 16)) + '}'
    text = re.sub(atom + '(?:' + script + ')+', opaque, text)
    commands = set(re.findall(r'\\([A-Za-z]+)', text))
    allowed = {'frac', 'dfrac', 'sqrt', 'alpha', 'beta', 'gamma', 'delta', 'epsilon',
               'varepsilon', 'zeta', 'eta', 'theta', 'vartheta', 'iota', 'kappa',
               'lambda', 'mu', 'nu', 'xi', 'pi', 'rho', 'sigma', 'tau', 'upsilon',
               'phi', 'varphi', 'chi', 'psi', 'omega', 'Delta', 'Gamma', 'Omega',
               'Theta', 'Lambda', 'Sigma', 'Phi', 'Psi', 'cdot', 'times'}
    if commands - allowed or re.search(r'[^\x20-\x7e]', text):
        raise Unsupported('超出已支持的标量代数范围')
    if not text or len(text) > 600 or text.count('{') > 40 or text.count('=') > 1:
        raise Unsupported('表达式为空、过长或不是单一等式')
    # Superscript numbers attached to indexed variables can be state labels,
    # not powers. Refuse to guess their meaning (e.g. E_i^1).
    if re.search(r'v_\{\d+\}\s*\^\s*(?:\{\s*[01]\s*\}|[01])', text):
        raise Unsupported('数值上标可能是状态指标，不能当作幂自动解释')
    return text.replace('\\dfrac', '\\frac')


@lru_cache(maxsize=512)
def parse_math(text):
    if runtime_identity() != VERSIONS:
        raise Unsupported('核验依赖缺失或版本不一致')
    from sympy.parsing.latex import parse_latex
    from sympy.parsing.latex.errors import LaTeXParsingError
    from sympy import preorder_traversal, Pow
    try:
        expression = parse_latex(_latex(text), strict=True)
    except (ImportError, ValueError, TypeError, LaTeXParsingError) as exc:
        raise Unsupported(str(exc)[:160]) from exc
    nodes = list(preorder_traversal(expression))
    if len(nodes) > 120:
        raise Unsupported('代数树超过核验预算')
    for node in nodes:
        if isinstance(node, Pow) and (not node.exp.is_Rational or abs(node.exp) > 12):
            raise Unsupported('不支持未定义符号幂或高次幂')
        if node.is_Function:
            raise Unsupported('函数、积分及非标量结构需另行核验')
    return expression


def compare_assignment(reference, candidate):
    """Compare same-target explicit assignments, never scale equation residuals.

    Different forms prompt review: conditions/assumptions may justify them.
    This is internal consistency, not confirmation against the original PDF.
    """
    if runtime_identity() != VERSIONS:
        return 'unsupported'
    from sympy import Equality, Symbol, cancel
    try:
        ref, pred = parse_math(reference), parse_math(candidate)
        if not isinstance(ref, Equality) or not isinstance(pred, Equality):
            return 'not_assignment'
        if not isinstance(ref.lhs, Symbol) or ref.lhs != pred.lhs:
            return 'different_target'
        difference = cancel(ref.rhs - pred.rhs)
        if difference == 0:
            return 'equivalent'
        if difference.is_zero is True:
            return 'equivalent'
        return 'different_forms'
    except (Unsupported, ValueError, TypeError, NotImplementedError) as exc:
        return 'unsupported'


def check_dimensions(formula, definitions):
    """Definitions map literal symbols to explicit SI base-dimension powers.

    Caller must verify source quotes before supplying definitions. No guessing
    from symbol names, no model-produced unit is accepted as source evidence.
    """
    if runtime_identity() != VERSIONS:
        return {'state': 'unknown', 'reason': '核验依赖缺失或版本不一致'}
    from sympy import Equality, Symbol, Mul, Add, Pow
    from sympy.physics.units import Dimension
    from sympy.physics.units.systems.si import dimsys_SI
    try:
        expr = parse_math(formula)
        dims = {}
        bases = {'time', 'length', 'mass', 'current', 'temperature',
                 'amount_of_substance', 'luminous_intensity'}
        for name, powers in definitions.items():
            symbol = parse_math(name)
            if not isinstance(symbol, Symbol) or not isinstance(powers, dict) or set(powers) - bases:
                raise Unsupported('量纲声明不完整或存在未知基本量')
            value = Dimension(1)
            for base, power in powers.items():
                if not isinstance(power, int) or isinstance(power, bool) or abs(power) > 12:
                    raise Unsupported('量纲指数不合法')
                value *= Dimension(base) ** power
            dims[symbol] = value
        def walk(node):
            if node.is_Number:
                return Dimension(1)
            if isinstance(node, Symbol):
                if node not in dims:
                    raise Unsupported('缺少原文量纲声明：' + str(node))
                return dims[node]
            if isinstance(node, Mul):
                result = Dimension(1)
                for child in node.args:
                    result *= walk(child)
                return result
            if isinstance(node, Pow):
                return walk(node.base) ** node.exp
            if isinstance(node, Add):
                values = [walk(child) for child in node.args]
                if not all(dimsys_SI.equivalent_dims(values[0], v) for v in values[1:]):
                    raise ValueError('加减项量纲不同')
                return values[0]
            raise Unsupported('量纲结构未支持')
        if not isinstance(expr, Equality):
            raise Unsupported('需要显式等式')
        return {'state': 'consistent' if dimsys_SI.equivalent_dims(walk(expr.lhs), walk(expr.rhs)) else 'inconsistent'}
    except Unsupported as exc:
        return {'state': 'unknown', 'reason': str(exc)}
    except (ValueError, TypeError) as exc:
        return {'state': 'inconsistent', 'reason': str(exc)}


def math_spans(text):
    pattern = r'\$\$(.*?)\$\$|(?<!\\)\$(?!\$)(.*?)(?<!\\)\$|\\\((.*?)\\\)|\\\[(.*?)\\\]'
    return [next(v for v in match.groups() if v is not None) for match in re.finditer(pattern, str(text), re.S)]


def symbol_scripts(text):
    """Lexical positions, including piecewise formulas unsupported by SymPy.

    Only compares the same base and the same script-token multiset: new
    variables, legitimate new powers and different index values are ignored.
    A position change is a review signal, never an automatic correction.
    """
    text = re.sub(r'\\(?:text|mathrm|textrm)\{([^{}]*)\}', r'\1', text)
    pattern = re.compile(r'\\[A-Za-z]+|[A-Za-z]')
    position = 0
    while position < len(text):
        match = pattern.search(text, position)
        if not match:
            break
        start, position = match.start(), match.end()
        base = match.group()
        scripts = {'_':'', '^':''}
        while position < len(text):
            if text[position].isspace():
                position += 1
                continue
            key = text[position]
            if key not in scripts:
                break
            position += 1
            if position >= len(text):
                break
            if text[position] == '{':
                end = text.find('}', position+1)
                if end < 0:
                    break
                scripts[key] = text[position+1:end]
                position = end+1
            else:
                scripts[key] = text[position]
                position += 1
        if any(scripts.values()):
            tokens = tuple(sorted(re.findall(r'[A-Za-z]+|\d+', scripts['_']+' '+scripts['^'])))
            signature = (re.sub(r'\s+', '', scripts['_']), re.sub(r'\s+', '', scripts['^']))
            yield {'base':base,'tokens':tokens,'signature':signature,'literal':text[start:position].strip()}


def _fields(card):
    for key in ('key_findings', 'one_line_summary', 'intro_summary', 'conclusion_summary'):
        yield key, str(card.get(key, ''))
    for kind in ('equations', 'figures'):
        for index, item in enumerate(card.get(kind, [])):
            for key in ('quantities', 'summary', 'detail', 'result', 'one_line'):
                yield f'{kind}[{index}].{key}', str(item.get(key, ''))


def _expansions(text):
    # Only unambiguous English expansions whose initials actually spell the
    # abbreviation. Punctuation boundaries prevent borrowing prior clauses.
    text = re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', text))
    def initials_match(words, acronym):
        from itertools import product
        choices = [(w[0].upper(), ''.join(part[0].upper() for part in w.split('-'))) for w in words]
        return any(''.join(parts) == acronym for parts in product(*choices))
    for match in re.finditer(r'\(([A-Z]{2,8})\)', text):
        prefix = text[max(0, match.start()-130):match.start()]
        suffix = re.search(r'([A-Za-z]+(?:[ -][A-Za-z]+){1,9})\s*$', prefix)
        if not suffix:
            continue
        words = re.findall(r'[A-Za-z]+(?:-[A-Za-z]+)*', suffix.group(1))
        for length in range(2, len(words)+1):
            expansion = words[-length:]
            if initials_match(expansion, match.group(1)):
                yield match.group(1), ' '.join(w.lower().replace('-', ' ') for w in expansion)
                break
    for match in re.finditer(r'\b([A-Z]{2,8})\s*\(([A-Za-z]+(?:[ -][A-Za-z]+){1,9})\)', text):
        words = re.findall(r'[A-Za-z]+(?:-[A-Za-z]+)*', match.group(2))
        if initials_match(words, match.group(1)):
            yield match.group(1), ' '.join(w.lower().replace('-', ' ') for w in words)


def audit_card(card, parsed):
    runtime = runtime_identity()
    if runtime != VERSIONS:
        return {'schema_version':VERSION,'runtime':runtime,'state':'unavailable',
                'blocking':True,'scientific_verified':False,'findings':[],
                'error':'核验依赖缺失或版本不一致，请按 requirements-science.txt 安装隔离依赖'}
    paragraphs = {p.get('index'): p for p in parsed.get('paragraphs', [])}
    findings, citations, math_checks = [], [], []
    def finding(code, path, note, **evidence):
        findings.append(dict(code=code, path=path, state='needs_review', note=note, **evidence))
    equations = card.get('equations', [])
    source_expansions = {}
    for p in paragraphs.values():
        for acronym, expansion in _expansions(p.get('text', '')):
            source_expansions.setdefault(acronym, {}).setdefault(expansion, p)
    fields = list(_fields(card))
    notation_references = {}
    for index, eq in enumerate(equations):
        for token in symbol_scripts(str(eq.get('latex', ''))):
            key = (token['base'], token['tokens'])
            notation_references.setdefault(key, []).append((f'equations[{index}].latex', token))
    for path, text in fields:
        for span in math_spans(text):
            for token in symbol_scripts(span):
                refs = notation_references.get((token['base'], token['tokens']), [])
                if refs and not any(token['signature'] == ref['signature'] for _, ref in refs):
                    finding('script_position_disagreement', path,
                            '相同符号及指标出现在不同上下标位置；须核对原文，不能把下标当作幂',
                            candidate=token['literal'],
                            references=[{'path':p, 'literal':r['literal']} for p,r in refs])
    for path, text in fields:
        for acronym, expansion in _expansions(text):
            originals = source_expansions.get(acronym, {})
            if originals and expansion not in originals:
                finding('abbreviation_disagreement', path, '缩写展开与原文显式定义不同',
                        acronym=acronym, candidate=expansion,
                        originals=[{'expansion': e, 'index': p['index'], 'page': p.get('page'),
                                    'quote': p['text']} for e, p in originals.items()])
    for kind in ('figures', 'equations'):
        for index, item in enumerate(card.get(kind, [])):
            path = f'{kind}[{index}]'
            context = item.get('context', [])
            refs = [paragraphs[r['index']] for r in context if r.get('index') in paragraphs]
            quote = str(item.get('evidence_quote') or '')
            # Literal evidence is checked within the supplied context, never
            # labelled entailment merely because it exists somewhere in PDF.
            matches = [p for p in refs if quote and quote in p.get('text', '')]
            citations.append({'path': path, 'state': 'literal_match' if matches else 'unverified',
                              'quote': quote, 'paragraphs': [{'index': p['index'], 'page': p.get('page'),
                              'sha256': hashlib.sha256(p['text'].encode()).hexdigest()} for p in matches],
                              'entailment': 'not_checked'})
            if item.get('evidence_status') != 'verified':
                finding('unverified_evidence', path, '依赖该条证据的解释不能视为已经核验',
                        affected_fields=[path+'.'+f for f in ('summary','detail','result') if item.get(f)])
            if kind != 'equations':
                continue
            latex = str(item.get('latex') or '')
            raw = str(item.get('equation_text') or '')
            if '=' in latex and '=' not in raw:
                finding('source_relation_incomplete', path+'.equation_text',
                        '转写包含等号而原始公式文本缺少等号；须核对截图，禁止以转写补成原文',
                        source_text=raw, candidate=latex, page=item.get('page'), image_path=item.get('image_path'))
    # Compare summaries with each other as well as with formula transcriptions.
    # Equal target + different RHS is a review candidate, not source truth.
    assignments, unparsed = [], []
    candidates = [(f'equations[{i}].latex', str(eq.get('latex',''))) for i,eq in enumerate(equations)]
    candidates += [(path,span) for path,text in fields for span in math_spans(text) if '=' in span]
    for path,text in candidates[:256]:
        try:
            from sympy import Equality, Symbol
            expr = parse_math(text)
            if isinstance(expr,Equality) and isinstance(expr.lhs,Symbol):
                assignments.append((path,text,expr.lhs))
            else:
                unparsed.append({'path':path,'reason':'不属于单一标量显式赋值'})
        except Unsupported as exc:
            unparsed.append({'path':path,'reason':str(exc)})
    if len(candidates)>256:
        finding('verification_budget_exceeded','meta.science_checks','显式公式候选超出核验预算，不能把部分核验标为完成')
    for index,(path,reference,target) in enumerate(assignments):
        for field,candidate,other_target in assignments[index+1:]:
            if path == field or target != other_target:
                continue
            state = compare_assignment(reference,candidate)
            if state in ('equivalent','different_forms'):
                math_checks.append({'reference_path':path,'candidate_path':field,
                                    'reference':reference,'candidate':candidate,'state':state,
                                    'source_verified':False})
                if state == 'different_forms':
                    finding('cross_field_formula_disagreement',field,
                            '同一目标的显式公式形式不同；条件和指标须回原文核对',
                            reference_path=path,reference=reference,candidate=candidate)
    dimension_checks = []
    declarations = card.get('meta', {}).get('source_dimension_evidence', [])
    definitions = {}
    for row in declarations:
        quote = row.get('source_quote', '')
        p = paragraphs.get(row.get('paragraph_index'), {})
        if quote and quote in p.get('text', '') and row.get('page') == p.get('page'):
            definitions[row['symbol']] = row['dimensions']
    for index, eq in enumerate(equations):
        result = check_dimensions(eq.get('latex', ''), definitions) if definitions else {'state':'unknown','reason':'缺少带原文定位的量纲声明'}
        dimension_checks.append({'path': f'equations[{index}].latex', **result})
        if result['state'] == 'inconsistent':
            finding('dimension_disagreement', f'equations[{index}].latex', '显式原文量纲声明与公式不相容')
    # Repeated mention of the same issue remains one finding per field.
    findings=list({json.dumps(f,sort_keys=True,ensure_ascii=False):f for f in findings}.values())
    return {'schema_version': VERSION, 'runtime': runtime,
            'state': 'unavailable' if runtime != VERSIONS else ('needs_review' if findings else 'checked'),
            'blocking': runtime != VERSIONS or bool(findings), 'scientific_verified': False,
            'findings': findings, 'citations': citations, 'math_checks': math_checks,
            'math_scope':{'supported_assignments':len(assignments),'unparsed':unparsed,
                          'truncated':len(candidates)>256},
            'dimension_checks': dimension_checks,
            'limits': ['非标量/函数/积分及歧义上标未作代数证明', '视觉图例与自然语言蕴含未核验',
                       '模型转写不是原文公式真值；不同条件下的公式差异须人工确认']}


def bounded_audit(card, parsed, timeout=20):
    """One subprocess per card; parser/algebra hangs cannot stall the worker."""
    try:
        payload = json.dumps({'card': card, 'parsed': parsed}, ensure_ascii=False)
        result = subprocess.run([sys.executable, '-m', 'reading.science_verifier', '--worker'],
                                input=payload, capture_output=True, text=True, cwd=ROOT, timeout=timeout)
        if result.returncode:
            raise RuntimeError(result.stderr[-500:])
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, OSError, ValueError, RuntimeError) as exc:
        return {'schema_version': VERSION, 'state': 'unavailable', 'blocking': True,
                'scientific_verified': False, 'findings': [], 'error': str(exc)[:600]}


def main():
    if sys.argv[1:] == ['--worker']:
        payload = json.load(sys.stdin)
        print(json.dumps(audit_card(payload['card'], payload['parsed']), ensure_ascii=False))
        return
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--card', type=Path, required=True)
    parser.add_argument('--parsed', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.resolve() in (args.card.resolve(), args.parsed.resolve()):
        parser.error('输出不能覆盖卡片或原文解析')
    card, parsed = json.loads(args.card.read_text()), json.loads(args.parsed.read_text())
    report = bounded_audit(card, parsed)
    report['card_sha256'] = hashlib.sha256(args.card.read_bytes()).hexdigest()
    report['parsed_sha256'] = hashlib.sha256(args.parsed.read_bytes()).hexdigest()
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'state': report['state'], 'findings': len(report['findings']), 'out': str(args.out)}))


if __name__ == '__main__':
    main()
