"""Deterministic, evidence-backed two-stage directions. No model/network calls."""
from importlib.resources import files
import json
import re
import unicodedata

from .store import fingerprint
from .focus import select_core,method_causal_attribution

RULE_VERSION = 'directions-rules-1.4.33'
TAXONOMY = json.loads(files('literature').joinpath('taxonomy.json').read_text())
LABELS = TAXONOMY['labels']
BY_ID = {r['id']:r for r in LABELS}


def canonical(text):
    """Normalize typography while retaining an offset map into exact original text."""
    chars=[]; offsets=[]
    for i,char in enumerate(text):
        for c in unicodedata.normalize('NFKC',char).lower():
            chars.append('-' if c in '‐‑‒–—−' else (' ' if c.isspace() else c)); offsets.append(i)
    # PDF line-break hyphenation only: preserve semantic intra-line hyphens.
    joined=''.join(chars)
    for match in reversed(list(re.finditer(r'(?<=[a-z])- +(?=[a-z])',joined))):
        original=text[offsets[match.start()]:offsets[match.end()]]
        if '\n' in original:
            a,b=match.span();chars[a:b]=[];offsets[a:b]=[]
    return ''.join(chars),offsets


PATTERNS = {r['id']:re.compile(r'(?<![a-z0-9])(?:'+'|'.join(r['patterns'])+r')(?![a-z0-9])',re.I) for r in LABELS}
FOCUS=re.compile(r'\b(?:we|herein|here we|this (?:work|study|paper|report)|our|in this|present|report|demonstrat\w*|investigat\w*|design\w*|synthesi\w*|develop\w*|achiev\w*|reveal\w*|propos\w*|review\w*|(?:is|are|was|were) (?:studied|fabricated|examined|characterized|synthesized))\b',re.I)
# Scope this lexical guard to metadata abstracts and their antecedents; the
# original fulltext admission policy remains an independent rule.
ABSTRACT_FOCUS=re.compile(FOCUS.pattern.replace(r'develop\w*',r'develop(?:s|ed|ing)?'),FOCUS.flags)
PRIOR=re.compile(r'(?:\b(?:previous(?:ly)?|prior work|has been reported|have been reported|reported by|in the literature|are known to|is known to)\b|\bet al\.)',re.I)
NEGATION=re.compile(r'(?:\b(?:without|absence of|no evidence (?:for|of)|does not (?:show|exhibit)|not observed|non[- ]))[^.;!?]{0,35}$',re.I)
METHOD_USE=re.compile(r'\b(?:measur(?:e|es|ed|ing|ements?)|record(?:s|ed|ing|ings)?|perform(?:s|ed|ing)?|calculat(?:e|es|ed|ing|ions?)|determin(?:e|es|ed|ing|ations?)|obtain(?:s|ed|ing)?|conduct(?:s|ed|ing)?|carried out|using|used|fabricat(?:e|es|ed|ing|ions?)|deposit(?:s|ed|ing|ions?)?|spin[- ]coat(?:s|ed|ing|ings)?|shown|figure|fig\.|supporting information|experimental)\b',re.I)
MAIN_SECTIONS={'results','discussion','results and discussion','methods','conclusion'}
PROCEDURE_REFERENCE=re.compile(r'\bas\s+(?:(?:previously|earlier)\s+(?:described|reported|detailed)|(?:described|reported|detailed)\s+(?:previously|earlier))\b',re.I)
CURRENT_METHOD_ACTION=re.compile(r'\b(?:(?:was|were|is|are)\s+(?:measured|recorded|performed|determined|calculated|obtained|conducted|fabricated)|we\s+(?:measured|recorded|performed|determined|calculated|obtained|conducted|fabricated|used))\b',re.I)
CHROMATOGRAPHY=re.compile(r'\b(?:HPLC|GPC|chromatograph\w*|(?:LC|GC)[- ]MS)\b',re.I)
DEGRADATION_PRODUCTS=re.compile(r'\bdegradation products\b',re.I)
RESULT_SUBJECT=re.compile(r'^\s*(?:these|this|those|such)\s+([a-z][a-z -]{0,70}?)\s+(?:emits?|exhibits?|shows?|displays?|produces?|enables?)\b',re.I)
NONCURRENT_RESULT=re.compile(r'\b(?:previous\w*|prior|earlier|historical|review\w*|known|other|another|may|might|could|would|if|had been|used to|in (?:19|20)\d{2})\b',re.I)
RESULT_CONNECTOR=re.compile(r'^\s*(?:more importantly|consequently|as a result|therefore|thus)\b',re.I)
CAUSAL_ACTION=re.compile(r'\b(?:induces?|causes?|leads? to|results? in|hinders?|promotes?|suppresses?)\b',re.I)
RESULT_DENIAL=re.compile(r"\b(?:no|not|never|without|cannot|[a-z]+n['’]t|fail(?:s|ed)? to|unable to|lack\w*)\b",re.I)
CURRENT_ANCHOR=re.compile(r'\b(?:herein|here[, ]+we|this work|this study|we (?:report|present|investigate|demonstrate|develop|reveal|prepare))\b',re.I)
LINK_STOP=set('these this those such that which their them with from into have been were while when where here herein more importantly therefore result results system systems work study material materials emitter emitters molecule molecules device devices present report reveal demonstrate develop prepare induce cause lead hinder promote suppress'.split())
METHOD_VERB = r'(?:measur\w*|record\w*|perform\w*|conduct\w*|us(?:e|ed|ing)|appl\w*|employ\w*|calculat\w*|determin\w*|obtain\w*|collect\w*|carr(?:y|ied) out|fabricat\w*|deposit\w*|spin[- ]coat\w*)'
METHOD_FINITE_ACTION = r'(?:measured|recorded|performed|conducted|used|applied|employed|calculated|determined|obtained|collected|fabricated|deposited)'
METHOD_CLAUSE_BREAK = re.compile(r'[;!?]|\b(?:but|however|whereas|while|instead)\b|(?:,|\band\b|\bor\b)\s*(?=(?:we|they|it|this study|our group)\b|'+METHOD_FINITE_ACTION+r'\b)',re.I)
METHOD_NEGATION_MODIFIERS = r'(?:(?:\w+ly|yet|ever|be|been|being|have|further)\s+){0,4}'
METHOD_DENIAL = re.compile(r"\b(?:not|never|no longer|cannot|[a-z]+n['’]t)\s+"+METHOD_NEGATION_MODIFIERS+METHOD_VERB+r'\b',re.I)
METHOD_PASSIVE_DENIAL = re.compile(r'^\s*(?:(?:spectra|spectroscopy|measurements?|calculations?|experiments?|analysis|technique|method)\s+)*(?:(?:was|were|is|are|has|have|had|been|can|could|did|do|does)\s+)*(?:not|never|no longer)\s+'+METHOD_NEGATION_MODIFIERS+METHOD_VERB+r'\b',re.I)
CITED_AUTHOR = re.compile(r'\bet al\.|\breported by\b',re.I)
EXPLICIT_OWN = re.compile(r'\b(?:we|our|herein|this (?:work|study|paper|report|review))\b',re.I)
PASSIVE_CONTINUATION = re.compile(r'\b(?:was|were|is|are|has been|have been)\s+(?:\w+ly\s+)?(?:conducted|performed|measured|recorded|investigated|studied|examined|characterized|synthesized|determined|calculated|obtained)\b',re.I)
TITLE_COMPARISON = re.compile(r'\bbeyond(?:\s+(?:conventional|traditional|standard|established))?\s+$',re.I)
BIBLIOGRAPHY_MARKER = re.compile(r'(?m)^[ \t]*(?:\(\d{1,4}\)|\[\d{1,4}\]|\d{1,4}\.)[ \t]+')
BIBLIOGRAPHY_AUTHOR = re.compile(r"[\w’'−-]+(?:[ \t]+[\w’'−-]+){0,3},\s*(?:[A-Z]\.[ \t]*){1,4}")
ABSTRACT_NOVEL_PASSIVE = re.compile(r'\b(?:is|are|was|were)\s+for\s+the\s+first\s+time\s+(?:studied|fabricated|examined|characterized|synthesized)\b',re.I)
ABSTRACT_PASSIVE_BOUNDARY = re.compile(r'[;!?]|\b(?:but|however|whereas|while|although|unlike|instead)\b',re.I)


def host_device_role(text, start, end):
    """Guard only the explicit host-for-OLED alias, preserving legacy aliases.

    The named alias already requires a device object and controlled adjectives.
    Local history, denied/hypothetical roles and nonmaterial host meanings do
    not acquire affirmative evidence merely because a title mentions OLEDs.
    This is lexical role evidence, not proof of actual device performance.
    """
    hit=PATTERNS['object.host'].fullmatch(canonical(text[start:end])[0])
    if not hit or not hit.groupdict().get('host_device_role'):return None
    a,b=sentence_span(text,start,end);sentence=canonical(text[a:b])[0]
    masked=re.sub(r'\bnot\s+only\b',lambda m:' '*len(m.group()),sentence,flags=re.I)
    noncurrent=bool(PRIOR.search(sentence) or RESULT_DENIAL.search(masked) or
        re.search(r'\b(?:earlier|historical|may|might|could|would|if|will|future|hypothetical|potential)\b',sentence,re.I))
    prefix=canonical(text[a:start])[0]
    # A contrast or punctuation ends a nonmaterial modifier's local scope.
    local=re.split(r'[:,;!?]|\b(?:but|however|whereas|while)\b',prefix)[-1]
    nonmaterial=bool(re.search(r'\b(?:biological|viral|bacterial|institutional|computer|network|server|conference|workshop)\b',local,re.I) or
        re.match(r'\s+(?:workshops?|conferences?|symposia|seminars?|meetings?|research|labs?|teams?)\b',canonical(text[end:b])[0],re.I))
    comparison=bool(TITLE_COMPARISON.search(prefix))
    return {'kind':'host_device_material_role','text':text[a:b],'start':a,'end':b,
            'hit_start':start,'hit_end':end,'eligible':not (noncurrent or nonmaterial or comparison),
            'noncurrent':noncurrent,'nonmaterial':nonmaterial,'comparison':comparison}


def abstract_passive_subject(text, start, end):
    """A bounded first-time passive may own its same-clause abstract subject.

    This supplements metadata admission only. Existing focus routes, adjacent
    result ownership and all fulltext rules remain independent and unchanged.
    """
    left=0;right=len(text)
    for boundary in ABSTRACT_PASSIVE_BOUNDARY.finditer(text):
        if boundary.end()<=start:left=boundary.end()
        elif boundary.start()>=end:right=boundary.start();break
    clause=text[left:right]
    if (PRIOR.search(clause) or NONCURRENT_RESULT.search(clause) or RESULT_DENIAL.search(clause)
            or re.search(r'\b(?:according to|literature|future|will|shall)\b',clause,re.I)):
        return False
    for passive in ABSTRACT_NOVEL_PASSIVE.finditer(clause):
        auxiliary=left+passive.start()
        if not left<=start<end<=auxiliary or auxiliary-end>120:continue
        # A second subject or finite predication cannot borrow this passive.
        if re.search(r'\b(?:and|or|is|are|was|were|has|have|remains?|shows?|exhibits?)\b',text[end:auxiliary],re.I):continue
        return True
    return False


def bibliography_entry(text, start, end):
    """Recognize only a numbered, line-initial multi-author bibliography entry.

    A wrong section name cannot make a cited article title our experiment.
    Two consecutive surname/initial author records are required. Scope ends
    at the next numbered entry or blank paragraph, never another chunk. This
    intentionally leaves unnumbered/truncated references unresolved.
    """
    markers=list(BIBLIOGRAPHY_MARKER.finditer(text))
    for i,marker in enumerate(markers):
        a=marker.start();b=markers[i+1].start() if i+1<len(markers) else len(text)
        paragraph=re.search(r'\n[ \t]*\n',text[marker.end():b])
        if paragraph:b=marker.end()+paragraph.start()
        if not a<=start<end<=b:continue
        cursor=marker.end();authors=0
        while cursor<b:
            author=BIBLIOGRAPHY_AUTHOR.match(text,cursor,b)
            if not author:break
            authors+=1;cursor=author.end()
            separator=re.match(r'\s*;\s*',text[cursor:b])
            if not separator:break
            cursor+=separator.end()
        if authors>=2:
            return {'text':text[a:b],'start':a,'end':b,'author_count':authors}
    return None


def title_comparison_hit(text, start, end):
    """A directly governed title hit is a comparison, not an affirmative claim.

    Only the local `beyond [qualifier] <matched topic>` is recognized. Another
    title hit or independent abstract evidence can still establish that topic.
    The exact original span is retained; no label-wide veto is inferred.
    """
    normalized,mapping=canonical(text)
    hit_start=len(canonical(text[:start])[0])
    marker=TITLE_COMPARISON.search(normalized[:hit_start])
    if not marker:return None
    a=mapping[marker.start()]
    return {'text':text[a:end],'start':a,'end':end,'hit_start':start,'hit_end':end}


def journal_soc_abbreviation(text, start, end):
    """Identify a local Society journal abbreviation, never a casing-only veto.

    Both a journal abbreviation immediately before Soc. and a publication
    year immediately after it are required. Keep original positions/case;
    another SOC hit or the full physical term remains independent.
    """
    if text[start:end].casefold()!='soc':return None
    left=max(0,start-64)
    prefix=re.search(r'\b(?:chem|phys|electrochem|biochem|mater|r)\.\s*$',text[left:start],re.I)
    suffix=re.match(r'\.\s*(?:[a-z]{2,5}\.\s*)?(?:19|20)\d{2}\b',text[end:],re.I)
    if not prefix or not suffix:return None
    a=left+prefix.start();b=end+suffix.end()
    return {'kind':'journal_soc_abbreviation','text':text[a:b],'start':a,'end':b,'hit_start':start,'hit_end':end}


def cited_passive_antecedent(text, start, end):
    """One same-chunk passive sentence may continue an explicit cited owner.

    This deliberately does not propagate across paragraphs, chunks, sources,
    or multiple sentences. Explicit first-person/current-work language resets
    ownership. The earlier sentence is retained as an exact rejection trace.
    """
    decision=canonical(text[start:end])[0]
    if EXPLICIT_OWN.search(decision) or not PASSIVE_CONTINUATION.search(decision):return None
    previous_end=start
    while previous_end and text[previous_end-1].isspace():previous_end-=1
    if previous_end<2 or '\n\n' in text[previous_end:start]:return None
    if text[previous_end-1] not in '.!?':return None
    a,b=sentence_span(text,previous_end-2,previous_end-1)
    previous=text[a:b];normalized=canonical(previous)[0]
    if not CITED_AUTHOR.search(normalized) or EXPLICIT_OWN.search(normalized):return None
    return {'text':previous,'start':a,'end':b}


def method_use_negated(text, start, end):
    """Bounded lexical method polarity, never whole-sentence negation inheritance.

    Coordinated method noun lists share a predicate; contrast clauses and an
    explicit new subject/action reset its scope. Not-only is additive, not a
    denied use. Original evidence and offsets are never rewritten.
    """
    masked=re.sub(r'\bnot\s+only\b',lambda m:' '*len(m.group()),text,flags=re.I)
    left=0;right=len(masked)
    for boundary in METHOD_CLAUSE_BREAK.finditer(masked):
        if boundary.end()<=start:left=boundary.end()
        elif boundary.start()>=end:right=boundary.start();break
    prefix=masked[left:start];suffix=masked[end:right]
    return bool(NEGATION.search(prefix) or METHOD_DENIAL.search(prefix) or
                re.search(r'\b(?:not|neither|nor|no|no need for)\s*$',prefix,re.I) or
                METHOD_PASSIVE_DENIAL.search(suffix))


def result_terms(text):
    """Conservative shared content words, not semantic entity recognition."""
    words=re.findall(r'\b[a-z][a-z0-9]{3,}\b',canonical(text)[0])
    return {re.sub(r'(?:ing|ed|s)$','',w) for w in words if w not in LINK_STOP}


def emitting_orientation_alias(text, start, end):
    """Exact new optical alias, with existing local measurement-denial scope.

    This does not change legacy question phrases, general source ownership,
    method-use rules or core ranking. Metadata never supplies body evidence.
    """
    hit=PATTERNS['question.emitter_orientation'].fullmatch(canonical(text[start:end])[0])
    if not hit or not hit.groupdict().get('emitting_orientation'):return None
    a,b=sentence_span(text,start,end);sentence=canonical(text[a:b])[0]
    left=len(canonical(text[a:start])[0]);right=left+len(canonical(text[start:end])[0])
    return {'kind':'explicit_emitting_dipole_orientation','text':text[a:b],'start':a,'end':b,
            'hit_start':start,'hit_end':end,'negated':method_use_negated(sentence,left,right)}


def abstract_causal_chain(text, start, end, hit_start):
    """At most two preceding sentences may connect a current causal result.

    Every adjacent pair must share content words, and an explicit current-work
    anchor must be reached. History, hypotheses and comparisons break the chain.
    Exact source sentences are retained independently of the wider hit quote.
    """
    current=text[start:end];decision=canonical(current)[0]
    before=canonical(text[start:hit_start])[0]
    if not RESULT_CONNECTOR.search(decision) or not CAUSAL_ACTION.search(before):return None
    chain=[{'text':current,'start':start,'end':end}];links=[];cursor=start
    for _ in range(3):
        value=canonical(chain[0]['text'])[0]
        if (PRIOR.search(value) or NONCURRENT_RESULT.search(value) or
            RESULT_DENIAL.search(value) or
            re.search(r'\b(?:unlike|whereas|while|compared|than)\b',value)):
            return None
        if len(chain)>1 and CURRENT_ANCHOR.search(value):
            return {'sentences':chain[:-1],'shared_terms':links,'hit_start':hit_start}
        if len(chain)==3:return None
        previous_end=cursor
        while previous_end and text[previous_end-1].isspace():previous_end-=1
        if previous_end<2 or '\n\n' in text[previous_end:cursor]:return None
        a,b=sentence_span(text,previous_end-2,previous_end-1)
        previous=text[a:b];shared=sorted(result_terms(previous)&result_terms(chain[0]['text']))
        if not shared:return None
        chain.insert(0,{'text':previous,'start':a,'end':b});links.insert(0,shared);cursor=a
    return None


def abstract_result_antecedent(text, start, end, hit_start, hit_end):
    """One adjacent current claim may own a demonstrative result about its noun.

    This is a conservative lexical antecedent check, not paragraph-wide focus
    inheritance. A comparison clause cannot borrow the new result's ownership.
    All offsets remain in the original abstract.
    """
    current=text[start:end];normalized=canonical(current)[0]
    subject=RESULT_SUBJECT.search(normalized)
    if not subject or PRIOR.search(normalized) or NONCURRENT_RESULT.search(normalized):return None
    noun=subject.group(1).split()[-1]
    if noun in {'work','study','studies','review','report','results','approach','strategy'}:return None
    prefix=canonical(text[start:hit_start])[0]
    if len(prefix)<subject.end() or re.search(r'\b(?:while|whereas|but|although|unlike)\b',prefix):return None
    previous_end=start
    while previous_end and text[previous_end-1].isspace():previous_end-=1
    if previous_end<2:return None
    a,b=sentence_span(text,previous_end-2,previous_end-1)
    previous=text[a:b];decision=canonical(previous)[0]
    if not ABSTRACT_FOCUS.search(decision) or PRIOR.search(decision) or NONCURRENT_RESULT.search(decision):return None
    if not re.search(r'(?<![a-z])'+re.escape(noun)+r'(?![a-z])',decision):return None
    return {'text':previous,'start':a,'end':b}


def current_method_procedure(text, start, end):
    """A local current-use clause may cite an older procedure, not older results.

    Only the procedure-reference phrase is masked. Any other historical cue
    still blocks, and a neighboring coordinated clause cannot validate the hit.
    Offsets refer to the normalized matched sentence; source quotes stay intact.
    """
    masked=PROCEDURE_REFERENCE.sub(lambda m:' '*len(m.group()),text)
    if masked==text or PRIOR.search(masked):return False
    if re.search(r'\b(?:had been|used to|earlier (?:work|stud(?:y|ies))|in (?:19|20)\d{2})\b',masked,re.I):return False
    left=0
    for boundary in [*re.finditer(r'\b(?:and|but|whereas|while)\b|[;!?]',text),None]:
        right=boundary.start() if boundary else len(text)
        if left<=start and end<=right:
            clause=text[left:right]
            return bool(PROCEDURE_REFERENCE.search(clause) and CURRENT_METHOD_ACTION.search(clause))
        left=boundary.end() if boundary else len(text)
    return False


def chromatography_ms_result_use(text, start, end):
    """A coupled analytical subject explicitly reports degradation products.

    This narrow result route supplements actual-use evidence for the existing
    joint workflow only; it does not change general method or core selection.
    The caller retains source, citation, bibliography and polarity guards.
    """
    if not re.fullmatch(r'(?:lc|gc)[- ]ms',text[start:end],re.I):return False
    if not re.fullmatch(r'\s*(?:(?:the|our)\s+)?',text[:start],re.I):return False
    if (PRIOR.search(text) or NONCURRENT_RESULT.search(text) or RESULT_DENIAL.search(text) or
        re.search(r'\b(?:probably|possibly|perhaps|apparently|will|shall|can|should|recommend\w*|planned)\b',text,re.I)):
        return False
    return bool(re.match(r'\s*(?:(?:analysis|analyses|measurements?|results?)\s+)?'
                         r'(?:(?:indeed|directly|clearly)\s+)?'
                         r'(?:revealed|identified|detected|showed)\s+(?:that\s+)?'
                         r'[^.;!?]{0,120}?\bdegradation products\b',text[end:],re.I))


def sentence_span(text, start, end):
    """Find the hit sentence without splitting common abbreviations or decimals."""
    left=0;right=len(text)
    for match in re.finditer(r'[.!?;]\s+',text):
        prefix=text[:match.start()+1]
        if re.search(r'\b(?:al|fig|eq|dr|prof|vs|e\.g|i\.e)\.$',prefix,re.I):continue
        if match.end()<=start:left=match.end()
        elif match.start()>=end:right=match.start()+1;break
    return left,right


def degradation_product_context(document):
    """Find explicit body linkage between degradation products and chromatography."""
    for chunk in document.get('chunks',[]):
        if chunk.get('scope')!='fulltext' or chunk.get('section') in {'references','acknowledgments'}:continue
        normalized,mapping=canonical(chunk['text'])
        for hit in DEGRADATION_PRODUCTS.finditer(normalized):
            hit_start=mapping[hit.start()];hit_end=mapping[hit.end()-1]+1
            if bibliography_entry(chunk['text'],hit_start,hit_end):continue
            a,b=sentence_span(chunk['text'],hit_start,hit_end)
            text=chunk['text'][a:b];decision=canonical(text)[0]
            if not CHROMATOGRAPHY.search(decision) or PRIOR.search(decision):continue
            if re.search(r'\b(?:no|without|not|might|could|potential\w*|future)\b',decision):continue
            return {'scope':'fulltext','page':chunk.get('page'),'chunk_id':chunk['id'],'section':chunk.get('section','unknown'),
                    'quote':text,'start':a,'end':b,'matched_text':chunk['text'][mapping[hit.start()]:mapping[hit.end()-1]+1],
                    'focus_text':text,'focus_start':a,'focus_end':b,'relation':'workflow_context',
                    'basis':'degradation_products_linked_to_chromatography'}
    return None



def repeated_running_headers(document):
    """Identify repeated long lines at proven physical page starts only.

    Pagination digits may move between either end of a header. Actual current
    scientific statements, mid-page chunks and missing page offsets are never
    inferred to be headers. Every original occurrence remains traceable.
    """
    grouped={}
    for chunk in document.get('chunks',[]):
        if (chunk.get('scope')!='fulltext' or type(chunk.get('page_start')) is not int or
            chunk['page_start']!=0 or type(chunk.get('page')) is not int):continue
        lines=[m for m in re.finditer(r'(?m)^.*$',chunk['text']) if m.group().strip()][:2]
        for line in lines:
            normalized=canonical(line.group())[0].strip()
            normalized=re.sub(r'^\d{1,4}\s+','',normalized)
            normalized=re.sub(r'\s+\d{1,4}$','',normalized).strip()
            if not 32<=len(normalized)<=200 or len(re.findall('[a-z]',normalized))<16:continue
            if re.search(r'\b(?:we|our|herein|this (?:work|study)|was|were|is|are|measured|observed|calculated|performed|confirmed|found)\b',normalized):continue
            grouped.setdefault(normalized,[]).append({'chunk_id':chunk['id'],'page':chunk['page'],
                'text':line.group(),'start':line.start(),'end':line.end()})
    result={}
    for normalized,occurrences in grouped.items():
        if len({x['page'] for x in occurrences})<2:continue
        for occurrence in occurrences:
            result.setdefault(occurrence['chunk_id'],[]).append({
                'kind':'repeated_physical_page_header','text':occurrence['text'],
                'start':occurrence['start'],'end':occurrence['end'],
                'normalized':normalized,'occurrences':occurrences})
    return result


def metadata_fingerprint(row):
    return fingerprint({'title':row['title'],'abstract':row.get('metadata',{}).get('abstract') or ''})


def classify(document):
    """Classifier only sees this exact frozen input; it never opens other files."""
    broad=[];fine=[];mentions=[]
    chunks=[{'id':'title','text':document['title'],'scope':'title','page':None,'section':'title'},
            {'id':'abstract','text':document.get('abstract') or '', 'scope':'abstract','page':None,'section':'abstract'},
            *document.get('chunks',[])]
    product_context=degradation_product_context(document)
    headers=repeated_running_headers(document)
    for rule in LABELS:
        # Domain-qualified themes use metadata only. A body-only device name
        # cannot manufacture a level-1 OLED theme from an unrelated optical hit.
        domains=rule.get('metadata_context_patterns',[])
        if domains and rule['level']==1 and not any(re.search(p,canonical(document['title']+' '+(document.get('abstract') or ''))[0],re.I) for p in domains):
            continue
        accepted=[];uncertain=[]
        rescued_workflow_result=False
        for chunk in chunks:
            if rule['level']==1 and chunk['scope']=='fulltext':continue
            if rule['level']==2 and chunk['scope']!='fulltext':continue
            normalized,mapping=canonical(chunk['text'])
            for hit in list(PATTERNS[rule['id']].finditer(normalized))[:8]:
                left=max(0,hit.start()-220);right=min(len(normalized),hit.end()+240)
                context=normalized[left:right];before=normalized[max(0,hit.start()-70):hit.start()]
                hit_start=mapping[hit.start()];hit_end=mapping[hit.end()-1]+1
                focus_start,focus_end=sentence_span(chunk['text'],hit_start,hit_end)
                focus_text=chunk['text'][focus_start:focus_end]
                decision=canonical(focus_text)[0]
                # A reverse ISC mention does not independently establish forward ISC.
                if rule['id']=='mechanism.isc' and re.search(r'reverse\s*$',before):continue
                is_method=rule['level']==2 and rule['dimension']=='method'
                if (not is_method and NEGATION.search(before)) or normalized[hit.end():hit.end()+6].startswith('-free'):continue
                section=chunk.get('section','unknown')
                own=bool((ABSTRACT_FOCUS if chunk['scope']=='abstract' else FOCUS).search(decision));prior=bool(PRIOR.search(decision))
                decision_start=len(canonical(focus_text[:hit_start-focus_start])[0])
                decision_end=decision_start+len(canonical(chunk['text'][hit_start:hit_end])[0])
                if rule['level']==1 and chunk['scope']=='abstract' and not own:
                    own=abstract_passive_subject(decision,decision_start,decision_end)
                denied=is_method and method_use_negated(decision,decision_start,decision_end)
                workflow_result=(rule.get('evidence_requirement')=='chromatography_ms_degradation_products' and
                                 section in MAIN_SECTIONS and
                                 not BIBLIOGRAPHY_MARKER.search(chunk['text'][:focus_start]) and
                                 chromatography_ms_result_use(decision,decision_start,decision_end))
                # Nominal experimental results can establish use without a
                # spurious operation stem hidden inside a word like performance.
                method_use=is_method and bool(METHOD_USE.search(decision) or
                    method_causal_attribution(decision,decision_start,decision_end) or workflow_result)
                procedure=rule['level']==2 and rule['dimension']=='method' and current_method_procedure(decision,decision_start,decision_end)
                if procedure:prior=False
                citation=cited_passive_antecedent(chunk['text'],focus_start,focus_end) if chunk['scope']!='title' else None
                if citation:prior=True
                comparison=title_comparison_hit(chunk['text'],hit_start,hit_end) if rule['level']==1 and rule['dimension']=='topic' and chunk['scope']=='title' else None
                host_role=host_device_role(chunk['text'],hit_start,hit_end) if rule['id']=='object.host' else None
                orientation_alias=emitting_orientation_alias(chunk['text'],hit_start,hit_end) if rule['id']=='question.emitter_orientation' else None
                bibliography=bibliography_entry(chunk['text'],hit_start,hit_end) if chunk['scope']=='fulltext' else None
                journal=journal_soc_abbreviation(chunk['text'],hit_start,hit_end) if rule['id']=='mechanism.soc' else None
                header=next(({**h,'hit_start':hit_start,'hit_end':hit_end} for h in headers.get(chunk['id'],[]) if h['start']<=hit_start and hit_end<=h['end']),None) if rule['level']==2 and not bibliography and not journal and not (orientation_alias and orientation_alias['negated']) else None
                workup=rule['id']=='question.quenching' and bool(re.search(r'\bquench\w*\s+(?:carefully\s+)?with\s+(?:water|acid|aqueous|ice)',decision))
                basis=None
                antecedent=None
                causal_chain=None
                if rule['level']==1:
                    if chunk['scope']=='title':basis='title'
                    elif own and not prior and not workup:basis='abstract_focus'
                    elif not prior and not workup:
                        antecedent=abstract_result_antecedent(chunk['text'],focus_start,focus_end,hit_start,hit_end)
                        if antecedent:basis='abstract_adjacent_result'
                        elif rule['dimension']=='topic':
                            causal_chain=abstract_causal_chain(chunk['text'],focus_start,focus_end,hit_start)
                            if causal_chain:basis='abstract_linked_causal_result'
                else:
                    if section in {'references','acknowledgments'}:continue
                    if not prior and not workup and (section in MAIN_SECTIONS or own or chunk.get('role')=='caption' or method_use):
                        if not is_method or method_use:basis='main_text_evidence'
                if rule.get('evidence_requirement')=='chromatography_ms_degradation_products':
                    if not (product_context and CHROMATOGRAPHY.search(decision) and
                            (CURRENT_METHOD_ACTION.search(decision) or workflow_result)):
                        basis=None
                    if re.search(r'\b(?:not|never|without|may|might|could|would|if|recommend\w*)\b',decision):basis=None
                if denied:basis=None
                if comparison:basis=None
                if bibliography:basis=None
                if journal:basis=None
                if header:basis=None
                if host_role and not host_role['eligible']:basis=None
                if orientation_alias and orientation_alias['negated']:basis=None
                a=mapping[left];b=mapping[right-1]+1
                evidence={'scope':chunk['scope'],'page':chunk.get('page'),'chunk_id':chunk['id'],'section':section,
                          'quote':chunk['text'][a:b],'start':a,'end':b,'matched_text':chunk['text'][mapping[hit.start()]:mapping[hit.end()-1]+1],
                          'focus_text':focus_text,'focus_start':focus_start,'focus_end':focus_end,
                          'relation':'used' if rule['dimension']=='method' and basis else ('about' if basis else 'mentioned'),
                          'basis':basis or ('host_role_not_affirmed' if host_role and not host_role['eligible'] else ('bibliography_entry_only' if bibliography else ('negated_orientation_use' if orientation_alias and orientation_alias['negated'] else ('journal_abbreviation_only' if journal else ('title_comparison_only' if comparison else ('cited_author_passive_continuation' if citation else ('negated_method_use' if denied else 'background_or_insufficient_context')))))))}
                if header:
                    evidence.update(basis='repeated_running_header',relation='mentioned',running_header=header)
                if host_role:evidence['host_device_role']=host_role
                if orientation_alias:evidence['orientation_alias']=orientation_alias
                if bibliography:evidence['bibliography_entry']=bibliography
                if journal:evidence['acronym_disambiguation']=journal
                if comparison:evidence['title_comparison']=comparison
                if citation and not bibliography:evidence['citation_antecedent']=citation
                if procedure and basis:evidence['procedure_reference']='current_use_citing_prior_procedure'
                if workflow_result and basis and not CURRENT_METHOD_ACTION.search(decision):
                    evidence['method_result']='chromatography_ms_result_use'
                    rescued_workflow_result=True
                if antecedent and basis:evidence['antecedent']=antecedent
                if causal_chain and basis:evidence['causal_chain']=causal_chain
                (accepted if basis else uncertain).append(evidence)
        if accepted:
            if rule.get('evidence_requirement')=='chromatography_ms_degradation_products':accepted=accepted[:2]+[product_context]
            entry={k:rule[k] for k in ('id','level','dimension','name','parent')}
            entry.update(evidence=accepted[:3],status='automatic_evidence_checked')
            (broad if rule['level']==1 else fine).append(entry)
            rejected=[e for e in uncertain if 'title_comparison' in e or 'bibliography_entry' in e or 'acronym_disambiguation' in e or 'host_device_role' in e or 'orientation_alias' in e or 'running_header' in e or rescued_workflow_result]
            if rejected:
                reason=('Unaccepted workflow evidence; independent accepted evidence retained separately' if rescued_workflow_result else
                        'Journal acronym evidence; independent accepted evidence retained separately' if any('acronym_disambiguation' in e for e in rejected) else
                        'Comparison or bibliography evidence; independent accepted evidence retained separately')
                mentions.append({'id':rule['id'],'level':rule['level'],'reason':reason,'evidence':rejected})
        elif uncertain:
            evidence=uncertain[:2]+[e for e in uncertain[2:] if 'bibliography_entry' in e or 'acronym_disambiguation' in e or 'running_header' in e]
            mentions.append({'id':rule['id'],'level':rule['level'],'reason':'Only background, citation, negated or insufficient use evidence','evidence':evidence})
    # Hierarchy is a declared implication; preserve the exact child evidence and record the inference.
    for labels in (broad,fine):
        existing={x['id'] for x in labels}
        for child in list(labels):
            parent=child['parent']
            while parent and parent not in existing:
                rule=BY_ID[parent]
                if rule['level']!=child['level']:break
                entry={k:rule[k] for k in ('id','level','dimension','name','parent')}
                entry.update(evidence=child['evidence'],status='automatic_evidence_checked',hierarchy_basis=child['id'])
                labels.append(entry);existing.add(parent);parent=rule['parent']
    result={'rule_version':RULE_VERSION,'taxonomy_version':TAXONOMY['version'],'paper_id':document['paper_id'],
            'input_fingerprint':fingerprint(document),'metadata_fingerprint':document['metadata_fingerprint'],
            'source_fingerprint':document.get('source_fingerprint'),'level1':sorted(broad,key=lambda x:x['id']),
            'level2':sorted(fine,key=lambda x:x['id']),'mentions':mentions,
            'limitations':document.get('limitations',[]),'scientific_verified':False,
            'level1_state':'completed' if broad else 'unable_to_determine',
            'level2_state':'completed' if fine else ('missing_input' if not document.get('chunks') else 'unable_to_determine')}
    result=select_core(document,result,BY_ID,PATTERNS,canonical)
    validate_evidence(document,result)
    return result


def validate_evidence(document,result):
    headers=repeated_running_headers(document)
    chunks={x['id']:x for x in document.get('chunks',[])}
    chunks.update(title={'text':document['title'],'page':None},abstract={'text':document.get('abstract') or '','page':None})
    for label in result['level1']+result['level2']+result.get('supporting_labels',[])+result.get('inherited_labels',[])+result.get('mentions',[]):
        for e in label['evidence']:
            chunk=chunks[e['chunk_id']]
            if chunk['text'][e['start']:e['end']]!=e['quote'] or chunk.get('page')!=e['page']:
                raise ValueError('证据位置或逐字引文不一致')
            if 'focus_text' in e and chunk['text'][e['focus_start']:e['focus_end']]!=e['focus_text']:
                raise ValueError('判定句与原文位置不一致')
            if 'running_header' in e:
                trace=e['running_header']
                if (label['level']!=2 or e['scope']!='fulltext' or
                    chunk['text'][trace['hit_start']:trace['hit_end']]!=e['matched_text'] or
                    e['relation']!='mentioned' or e['basis']!='repeated_running_header' or
                    not any({**h,'hit_start':trace['hit_start'],'hit_end':trace['hit_end']}==trace
                            for h in headers.get(e['chunk_id'],[])
                            if h['start']<=trace['hit_start'] and trace['hit_end']<=h['end'])):
                    raise ValueError('重复页眉与原文位置或跨页证据不一致')
            if 'orientation_alias' in e:
                trace=e['orientation_alias']
                if (label['id']!='question.emitter_orientation' or label['level']!=2 or e['scope']!='fulltext' or
                    chunk['text'][trace['start']:trace['end']]!=trace['text'] or
                    chunk['text'][trace['hit_start']:trace['hit_end']]!=e['matched_text'] or
                    emitting_orientation_alias(chunk['text'],trace['hit_start'],trace['hit_end'])!=trace or
                    (trace['negated'] and (e['relation']!='mentioned' or e['basis'] not in {'negated_orientation_use','bibliography_entry_only'}))):
                    raise ValueError('发射偶极别名与原文位置或否定判定不一致')
            if 'host_device_role' in e:
                trace=e['host_device_role']
                if (label['id']!='object.host' or label['level']!=1 or e['scope'] not in {'title','abstract'} or
                    chunk['text'][trace['start']:trace['end']]!=trace['text'] or
                    chunk['text'][trace['hit_start']:trace['hit_end']]!=e['matched_text'] or
                    host_device_role(chunk['text'],trace['hit_start'],trace['hit_end'])!=trace or
                    (not trace['eligible'] and (e['relation']!='mentioned' or e['basis']!='host_role_not_affirmed'))):
                    raise ValueError('主体角色与原文位置或判定不一致')
            if 'acronym_disambiguation' in e:
                trace=e['acronym_disambiguation']
                if (label['id']!='mechanism.soc' or e['scope']!='fulltext' or
                    chunk['text'][trace['start']:trace['end']]!=trace['text'] or
                    chunk['text'][trace['hit_start']:trace['hit_end']]!=e['matched_text'] or
                    journal_soc_abbreviation(chunk['text'],trace['hit_start'],trace['hit_end'])!=trace or
                    e['relation']!='mentioned' or e['basis'] not in {'journal_abbreviation_only','bibliography_entry_only'}):
                    raise ValueError('期刊缩写消歧与原文位置或判定不一致')
            if 'bibliography_entry' in e:
                trace=e['bibliography_entry']
                positions=[m.span() for m in re.finditer(re.escape(e['matched_text']),chunk['text'])
                           if e['start']<=m.start()<m.end()<=e['end']]
                if (e['scope']!='fulltext' or label['level']!=2 or
                    chunk['text'][trace['start']:trace['end']]!=trace['text'] or
                    not any(bibliography_entry(chunk['text'],a,b)==trace for a,b in positions) or
                    e['relation']!='mentioned' or e['basis']!='bibliography_entry_only'):
                    raise ValueError('书目条目与原文位置或归属不一致')
            if 'title_comparison' in e:
                trace=e['title_comparison']
                if (e['scope']!='title' or label['level']!=1 or BY_ID[label['id']]['dimension']!='topic' or
                    chunk['text'][trace['start']:trace['end']]!=trace['text'] or
                    chunk['text'][trace['hit_start']:trace['hit_end']]!=e['matched_text'] or
                    not PATTERNS[label['id']].fullmatch(canonical(e['matched_text'])[0]) or
                    title_comparison_hit(chunk['text'],trace['hit_start'],trace['hit_end'])!=trace or
                    e['relation']!='mentioned' or e['basis']!='title_comparison_only'):
                    raise ValueError('标题比较语境与原文位置或判定不一致')
            if 'citation_antecedent' in e:
                a=e['citation_antecedent']
                if (chunk['text'][a['start']:a['end']]!=a['text'] or
                    cited_passive_antecedent(chunk['text'],e['focus_start'],e['focus_end'])!=a or
                    e['relation']!='mentioned' or e['basis']!='cited_author_passive_continuation'):
                    raise ValueError('引用归属前句与原文位置或判定不一致')
            if 'antecedent' in e:
                a=e['antecedent']
                if (e['scope']!='abstract' or label['level']!=1 or
                    chunk['text'][a['start']:a['end']]!=a['text'] or
                    abstract_result_antecedent(chunk['text'],e['focus_start'],e['focus_end'],
                                              e['focus_start']+e['focus_text'].index(e['matched_text']),
                                              e['focus_end'])!=a):
                    raise ValueError('摘要指代前句与原文位置或归属不一致')
            if 'causal_chain' in e:
                hit_start=e['causal_chain']['hit_start']
                if (e['scope']!='abstract' or label['level']!=1 or
                    not e['focus_start']<=hit_start<e['focus_end'] or
                    chunk['text'][hit_start:hit_start+len(e['matched_text'])]!=e['matched_text'] or
                    abstract_causal_chain(chunk['text'],e['focus_start'],e['focus_end'],
                        hit_start)!=e['causal_chain']):
                    raise ValueError('摘要结果链与原文位置或归属不一致')
