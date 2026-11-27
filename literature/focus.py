"""Core-label selection: general evidence rules, never paper-specific exceptions."""
import re

POLICY_VERSION = 'core-directions-v2'
CONTRIBUTION = re.compile(r'\b(?:investigat\w*|reveal\w*|demonstrat\w*|design\w*|develop\w*|propos\w*|elucidat\w*|confirm\w*|attribute\w*|suppress\w*|reduc\w*|enhanc\w*|improv\w*|originat\w*|govern\w*)\b', re.I)
METHOD_CONTRIBUTION = re.compile(r'\b(?:develop\w*|propos\w*|introduc\w*|novel|new approach|first|unveil\w*|solve\w*)\b', re.I)
PRIOR = re.compile(r'\b(?:previous(?:ly)?|prior|in the literature|et al\.|future|might|could potentially)\b', re.I)
CORE_SECTIONS = {'results', 'discussion', 'results and discussion', 'conclusion'}
SIDE_EXPLANATION = re.compile(r'\b(?:probably|possibly|perhaps|likely|speculat\w*|hypothesi[sz]\w*)\b', re.I)
GENERAL_ALTERNATIVE = re.compile(r'\bgenerally\b[^.;!?]*\b(?:can|may|could)\b', re.I)
STUDY_OWNER = re.compile(r'\b(?:we|our|herein|this (?:work|study))\b', re.I)
STUDY_ACTION = re.compile(r'\b(?:investigat\w*|stud(?:y|ied)|examin\w*|test\w*|propos\w*|elucidat\w*|prob(?:e|ed)|demonstrat\w*|reveal\w*|confirm\w*)\b[^.;!?]{0,100}$', re.I)
METADATA_HISTORY = re.compile(r'\b(?:previous(?:ly)?|prior|in the literature|et al\.)\b', re.I)
SIDE_CAUSE = re.compile(r'\b(?:probably|possibly|perhaps|likely)\s+(?:by|because|via|due to)\b|\b(?:attribut\w*|ascrib\w*|explain\w*)\b', re.I)
POST_UNCERTAINTY = re.compile(r'^\s+(?:(?:rate|process|mechanism)\s+)?(?:(?:is|are|was|were|seems?|appears?)\s+)?(?:probably|possibly|perhaps|likely)\b', re.I)
METHOD_SUBJECT = re.compile(r'^\s*(?:(?:our|the|these|those)\s+)?$',re.I)
METHOD_ATTRIBUTION = re.compile(r'^\s+(?:(?:experiments?|measurements?|calculations?|analys(?:is|es)|results?|data)\s+)?(?:(?:directly|clearly|quantitatively)\s+)?links?\s+(?P<outcome>[^.;!?]{1,180}?)\s+to\s+(?P<process>[^.;!?]{1,240})',re.I)
METHOD_ATTRIBUTION_PAST = re.compile(METHOD_ATTRIBUTION.pattern.replace('links?', 'linked'),re.I)
ATTRIBUTION_UNCERTAINTY = re.compile(r"\b(?:not|never|no|without|cannot|[a-z]+n['’]t|may|might|could|would|can|possibly|probably|perhaps|likely|if|whether|future|previous\w*|earlier|prior|hypothesi\w*|speculat\w*)\b",re.I)
SCIENTIFIC_OUTCOME = re.compile(r'\b(?:performance|efficien\w*|EQEs?|PLQY|PLQE|yields?|lifetimes?|emission|quenching|loss(?:es)?|stability|roll[- ]off|decay)\b',re.I)
PHYSICAL_PROCESS = re.compile(r'\b(?:(?:energy|electron|charge|triplet|exciton|spin)[- ](?:transfer|trapping|recombination|transport|annihilation|conversion)|RISC|ISC|TTA|FRET|Dexter|(?:reverse )?intersystem crossing|non[- ]radiative(?: decay| loss(?:es)?| process(?:es)?)?)\b',re.I)
QUESTION_BACKGROUND = re.compile(r'\b(?:in (?:many|most|some|several) (?:cases|reports|studies)|in general|generally|(?:many|most|several|some) (?:previous |prior )?(?:studies|reports|publications))\b',re.I)
QUESTION_CURRENT = re.compile(r'\b(?:we|our|herein|this (?:work|study|paper|device|result)|these (?:devices|measurements|results)|the present (?:work|study))\b',re.I)
QUESTION_CLAUSE_BREAK = re.compile(r'[.;!?]|\b(?:but|however|whereas|while|by contrast|in contrast)\b',re.I)


def generic_question_background(sentence, start, end):
    """A local general/literature qualifier cannot vote as our core problem.

    Only a qualifier preceding the hit in its clause is recognized. Explicit
    current ownership in that same clause preserves the vote. Contrast and
    punctuation end scope, including a period before numbered PDF citations;
    a later current sentence cannot retrospectively own the generic claim.
    Accepted scientific evidence is retained independently of this core vote.
    """
    left=0;right=len(sentence)
    for boundary in QUESTION_CLAUSE_BREAK.finditer(sentence):
        if boundary.end()<=start:left=boundary.end()
        elif boundary.start()>=end:right=boundary.start();break
    return bool(QUESTION_BACKGROUND.search(sentence[max(left,start-180):start]) and
                not QUESTION_CURRENT.search(sentence[left:right]))


def method_causal_attribution(sentence, start, end):
    """An accepted method explicitly linking an outcome to a physical process.

    The method must be the local grammatical subject, not a nearby technique.
    This bounded lexical result is a core-role cue, not scientific verification.
    Original accepted body evidence remains the sole source of the label.
    """
    if not METHOD_SUBJECT.fullmatch(sentence[:start]) or ATTRIBUTION_UNCERTAINTY.search(sentence):return False
    result=METHOD_ATTRIBUTION.match(sentence[end:]) or METHOD_ATTRIBUTION_PAST.match(sentence[end:])
    return bool(result and SCIENTIFIC_OUTCOME.search(result['outcome']) and PHYSICAL_PROCESS.search(result['process']))


def peripheral_mechanism(sentence, start, end):
    """Local uncertainty or a general alternative cannot borrow an outcome verb."""
    prefix=re.split(r'\b(?:but|however|whereas)\b',sentence[:start])[-1]
    return bool(SIDE_EXPLANATION.search(prefix[-140:]) or GENERAL_ALTERNATIVE.search(prefix) or
                POST_UNCERTAINTY.search(sentence[end:]))


def explicit_mechanism_focus(title, abstract, pattern):
    """Study targets may be hypotheses; metadata never supplies body evidence."""
    if pattern.search(title):return True
    for sentence in re.split(r'(?<=[.!?;])\s+',abstract):
        if METADATA_HISTORY.search(sentence) or not STUDY_OWNER.search(sentence):continue
        for match in pattern.finditer(sentence):
            prefix=sentence[:match.start()]
            action=STUDY_ACTION.search(prefix)
            if action and not GENERAL_ALTERNATIVE.search(prefix) and not SIDE_CAUSE.search(prefix[action.start():]):
                return True
    return False


def select_core(document, result, by_id, patterns, canonical):
    """Typical ranges are advisory. No quotas, padding, or forced truncation.

    Level 1 selection only sees title/abstract, including its decisions to hide
    a generic object. Level 2 always requires accepted fulltext evidence; title
    and abstract can indicate centrality but cannot supply missing body evidence.
    """
    title = canonical(document['title'])[0]
    abstract = canonical(document.get('abstract') or '')[0]
    metadata = title + ' ' + abstract
    core = {1: [], 2: []}
    supporting = []
    for level in (1, 2):
        candidates = result[f'level{level}']
        ids = {x['id'] for x in candidates}
        parents = set()
        for label in candidates:
            parent = label['parent']
            while parent:
                parents.add(parent)
                parent = by_id[parent]['parent']
        has_topic = any(x['dimension'] == 'topic' and x['id'] not in parents for x in candidates)
        for label in candidates:
            # Ancestors are rebuilt from retained core labels, never displayed twice.
            if label['id'] in parents:
                continue
            pattern = patterns[label['id']]
            in_title = bool(pattern.search(title))
            in_abstract = bool(pattern.search(abstract))
            # Composite workflows may be central through their stated scientific
            # purpose; this never supplies their required fulltext use evidence.
            workflow_context = any(re.search(p, metadata, re.I) for p in by_id[label['id']].get('core_context_patterns', []))
            if level == 1:
                keep = not (has_topic and label['id'] in {'object.molecule', 'object.film', 'object.polymer'})
                # An abstract-only object must be the research target in the title.
                if label['dimension'] == 'object' and has_topic and not in_title:
                    keep = False
                reason = 'specific_metadata_direction' if keep else 'generic_or_supporting_object'
            else:
                main_chunks = set()
                contribution = False
                distinct_method = False
                attributed_method = False
                peripheral_hits = 0
                direct_hits = 0
                background_question_hits = 0
                for evidence in label['evidence']:
                    text = canonical(evidence.get('focus_text',evidence['quote']))[0]
                    for sentence in re.split(r'(?<=[.!?;])\s+|\n\s*\n', text):
                        for match in pattern.finditer(sentence):
                            local = sentence[max(0, match.start()-100):match.end()+100]
                            if PRIOR.search(sentence):
                                continue
                            if label['dimension']=='question' and generic_question_background(sentence,match.start(),match.end()):
                                background_question_hits += 1
                                continue
                            if label['dimension']=='method' and evidence.get('section') in CORE_SECTIONS:
                                attributed_method |= method_causal_attribution(sentence,match.start(),match.end())
                            if label['dimension'] == 'mechanism':
                                if peripheral_mechanism(sentence,match.start(),match.end()):
                                    peripheral_hits += 1
                                    continue
                                direct_hits += 1
                            if evidence.get('section') in CORE_SECTIONS:
                                main_chunks.add(evidence['chunk_id'])
                            if CONTRIBUTION.search(local):
                                contribution = True
                            if METHOD_CONTRIBUTION.search(local):
                                distinct_method = True
                if label['dimension'] == 'method':
                    keep = in_title or in_abstract or distinct_method or workflow_context or attributed_method
                    reason = ('method_causal_attribution' if attributed_method else 'central_workflow_purpose' if workflow_context else 'distinctive_method') if keep else 'routine_characterization'
                else:
                    keep = in_title or in_abstract or contribution or len(main_chunks) >= 2
                    reason = 'central_body_direction' if keep else 'supporting_body_observation'
                    if label['dimension']=='question' and background_question_hits and not keep:
                        reason = 'generic_background_question'
                    if label['dimension'] == 'mechanism' and peripheral_hits and not direct_hits:
                        if explicit_mechanism_focus(title,abstract,pattern):
                            keep = True
                            reason = 'explicit_mechanism_study_target'
                        else:
                            keep = False
                            reason = 'speculative_or_general_mechanism'
            value = {**label, 'importance': 'core' if keep else 'supporting', 'selection_basis': reason}
            (core[level] if keep else supporting).append(value)

    inherited = {}
    for labels in core.values():
        for child in labels:
            parent = child['parent']
            while parent:
                rule = by_id[parent]
                inherited.setdefault(parent, {
                    **{k: rule[k] for k in ('id', 'level', 'dimension', 'name', 'parent')},
                    'importance': 'inherited', 'hierarchy_basis': child['id'],
                    'evidence': child['evidence'], 'status': 'automatic_evidence_checked',
                })
                parent = rule['parent']
    result.update(level1=core[1], level2=core[2], supporting_labels=supporting,
                  inherited_labels=sorted(inherited.values(), key=lambda x: x['id']),
                  selection_policy=POLICY_VERSION,
                  count_guidance={'level1': [1, 3], 'level2': [2, 5], 'hard_limit': False})
    for level in (1, 2):
        result[f'level{level}_state'] = ('completed' if core[level] else
            'missing_input' if level == 2 and not document.get('chunks') else 'unable_to_determine')
    return result
