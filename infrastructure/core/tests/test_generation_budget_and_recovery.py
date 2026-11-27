# Regression invariants retained from test_audit_1208.py; historical audit reports remain unchanged.
"""General process regressions for the 12:08 audit; no model or outbound review."""
import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from PIL import Image
from read.app.context_budget import estimate_tokens,image_tokens,input_limit,fit_fields
from reading.media_evidence import parse_latex_response
from reading.reading_failures import failure_class, diagnostics, retry_guard
from reading.tests.test_reading_safety import LocalFixture,FakeClient,rb
from read.app.generation_state import generation_complete


class BudgetAndFormats(unittest.TestCase):
    def test_cjk_budget_is_tokens_with_reserved_vision_and_output(self):
        text='中文证据'*1000
        self.assertLess(estimate_tokens(text),len(text.encode()))
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'image.png';Image.new('RGB',(1400,1000)).save(p)
            self.assertEqual(image_tokens([p]),4096)
            options={'num_ctx':16384,'num_predict':4096}
            self.assertEqual(input_limit(options,'', [p]),16384-4096-1024-4096)
            rendered,fields=fit_fields({'source':text*5},lambda v:'固定要求\n'+v['source'],input_limit(options,'',[p]))
            self.assertLessEqual(estimate_tokens(rendered),input_limit(options,'',[p]))
            self.assertEqual(fields,['source']);self.assertIn('不得推断',rendered)

    def test_bare_latex_preserves_commands_and_strict_legacy_json(self):
        latex=r'\hbar\omega=\frac{a}{b}\begin{aligned}x &= y\\z &= w\end{aligned}'
        self.assertEqual(parse_latex_response('<<<LATEX>>>\n'+latex+'\n<<<END>>>')[0],latex)
        self.assertEqual(parse_latex_response(json.dumps({'latex':latex}))[0],latex)
        for value in [r'{"latex":"\hbar"}','<<<LATEX>>>x<<<END>>> extra','<<<LATEX>>>\\input{file}<<<END>>>']:
            with self.assertRaises((ValueError,json.JSONDecodeError)):parse_latex_response(value)

    def test_numbered_appendix_multiline_and_false_panels(self):
        p=rb.parser
        for text in ['(b)No TTA, RF,TPQ = 3 nm','i,j,i̸=j','ˆσ ≡σ/kBT RF,TPQ = 2 nm RF,TPQ = 3 nm']:
            self.assertFalse(p._is_display_equation_text(text),text)
        blocks=[{'text':'x = y','bbox':[20,50,150,65]},
                {'text':'z = w','bbox':[20,72,150,86]},
                {'text':'(A12)','bbox':[170,50,200,65]}]
        eqs=p._find_display_equations([blocks])
        self.assertEqual(eqs[0].number,'A12');self.assertIn('z = w',eqs[0].text)
        self.assertEqual(p._equation_refs('Eq. (A12)'),{'A12'})
        self.assertIn('(A12)',p._group_label(['A11','A12'],0))

    def test_repeated_same_input_unknown_failure_breaks_at_two(self):
        card={'figures':[{'error':'Unsupported synthetic schema'}]}
        first=retry_guard(card,'a')
        second=retry_guard(card,'a',first)
        self.assertFalse(first['automatic_retry_blocked']);self.assertTrue(second['automatic_retry_blocked'])
        self.assertFalse(retry_guard(card,'b',second)['automatic_retry_blocked'])
        transient={'figures':[{'error':'HTTP 503'}]}
        self.assertFalse(retry_guard(transient,'a',retry_guard(transient,'a'))['automatic_retry_blocked'])

    def test_same_size_caps_closing_heading_replaces_early_summary(self):
        p=rb.parser
        paras=[p.Paragraph(i,0,[20,20+i*20,300,40+i*20],
                          'SUMMARY' if i in (0,9) else 'This is a full body paragraph with enough source text.',size=10) for i in range(10)]
        sections=p._detect_sections(paras,10)
        self.assertEqual([s.start for s in sections if s.name=='Conclusion'],[10])

    def test_workflow_failures_block_repeat_and_transient_failures_do_not(self):
        self.assertEqual(failure_class('输入超过上下文预算'),'workflow')
        self.assertEqual(failure_class('HTTP 503'),'transient')
        self.assertTrue(diagnostics({'figures':[{'error':'原文依据不能逐字核对'}]})['automatic_retry_blocked'])
        self.assertFalse(diagnostics({'figures':[{'error':'HTTP 503'}]})['automatic_retry_blocked'])
        self.assertTrue(diagnostics({'equations':[{'latex':''}]})['visual_transcription_incomplete'])


class Recovery(LocalFixture):
    def hooks(self,client):
        return (patch.object(rb.analyzer,'OllamaClient',return_value=client),
                patch.object(rb,'render_review_prompt',side_effect=lambda name,*a,**k:name),
                patch.object(rb,'supplement_quantities',return_value=[]))

    def test_quote_failure_preserves_generation_without_acceptance(self):
        paper=self.parsed();paper.figures=[rb.parser.Figure(1,'Fig. 1',None,'Different supplied caption',0,[40,620,200,640],crop_bbox=[40,580,200,615])]
        with patch.object(rb.analyzer,'_render_prompt',side_effect=lambda name,*a,**k:name):
            card=rb.analyzer.analyze_paper(paper,out_dir=self.root,client=FakeClient())
        item=card.figures[0]
        self.assertEqual(item.status,'needs_review');self.assertEqual(item.evidence_status,'needs_review')
        self.assertTrue(item.summary and item.detail and item.result and item.raw_response)
        self.assertFalse(generation_complete(card.to_dict()))

    def test_interrupted_generation_resumes_checkpoint_even_with_force(self):
        self.pdf();client=FakeClient()
        original=client.chat
        def interrupt(prompt,**kw):
            if prompt=='figure':raise KeyboardInterrupt('synthetic cancellation')
            return original(prompt,**kw)
        client.chat=interrupt
        request={'out_dir':str(self.root),'model':self.config['model'],'force':True}
        a,b,c=self.hooks(client)
        with a,b,c,self.assertRaises(KeyboardInterrupt):rb.process(request)
        checkpoint=json.loads((self.root/'generation-checkpoint.json').read_text())
        self.assertTrue(checkpoint['card']['meta']['metadata_generation_ok'])
        self.assertFalse((self.root/'card.json').exists())
        resumed=FakeClient();a,b,c=self.hooks(resumed);request['resume']=True
        with a,b,c:rb.process(request)
        self.assertEqual(resumed.calls,['figure'])
        self.assertTrue(generation_complete(json.loads((self.root/'card.json').read_text())))

    def test_schedule_cancellation_keeps_checkpoint_and_propagates(self):
        from core.model_schedule import ModelWindowClosed
        paper=self.parsed();client=FakeClient()
        original=client.chat
        def cancel(prompt,**kw):
            if prompt=='introduction':raise ModelWindowClosed('closed')
            return original(prompt,**kw)
        client.chat=cancel;states=[]
        with patch.object(rb.analyzer,'_render_prompt',side_effect=lambda name,*a,**kw:name),self.assertRaises(ModelWindowClosed):
            rb.analyzer.analyze_paper(paper,out_dir=self.root,client=client,checkpoint=lambda card:states.append(card.to_dict()))
        self.assertEqual(states[-1]['meta']['generation']['stages']['paper_info']['state'],'ok')
        self.assertNotIn('conclusion',client.calls)

    def test_resume_retries_incomplete_transcription_without_redoing_explanation(self):
        paper=self.parsed()
        eq=rb.parser.Equation('Eq. (1)',1,0,[40,500,250,530],'x = y',group_label='Eq. (1)',group_numbers=[1],
            group_bbox=[40,500,250,530],members=[{'label':'Eq. (1)','number':1,'page':1,'source_note':'synthetic','confidence':'high','text':'x = y','bbox':[40,500,250,530]}])
        paper.equations=[eq]
        client=FakeClient()
        with patch.object(rb.analyzer,'_render_prompt',side_effect=lambda name,*a,**kw:name):
            card=rb.analyzer.analyze_paper(paper,config={**rb.analyzer.load_config(),'enable_equations':False},out_dir=self.root,client=client)
            item=card.equations[0];item.status='ok';item.evidence_status='verified';item.summary='previous explanation';item.latex_status='HTTP 503';client.calls.clear()
            with patch.object(rb.analyzer,'latex_from_image',return_value=(r'x=y','synthetic successful transcription')) as transcribe:
                resumed=rb.analyzer.analyze_paper(paper,out_dir=self.root,client=client,base_card=card,only_figures=[])
        self.assertEqual(transcribe.call_count,1);self.assertEqual(client.calls,[])
        self.assertEqual(resumed.equations[0].summary,'previous explanation');self.assertEqual(resumed.equations[0].latex,r'x=y')

    def test_output_length_failure_is_recorded_and_not_retried(self):
        client=rb.analyzer.OllamaClient({**rb.analyzer.load_config(),'schedule_config':self.config})
        answer={'done_reason':'length','message':{'content':'partial'},'prompt_eval_count':500,'eval_count':4096}
        with patch('read.app.ollama_transport.chat',return_value=answer) as request:
            with self.assertRaisesRegex(ValueError,'长度上限'):client.chat('test')
        self.assertEqual(request.call_count,1);self.assertEqual(client.telemetry[0]['prompt_eval_count'],500)


class SourceCorpus(unittest.TestCase):
    def test_prb_appendix_caption_and_number_holes_are_exposed(self):
        # Test-only sample fixture: production behavior never branches on its ID.
        source=rb.ROOT/'data/deep_read/61a4a6d8-6c61-4027-ae4c-cf133a05be38/source.pdf'
        if not source.is_file():self.skipTest('Private source-corpus integration fixture is not present')
        self.assertTrue(source.is_file())
        parsed=rb.parser.parse_pdf(source,{**rb.analyzer.load_config(),'max_equation_groups':200,'max_figures':200})
        rb.repair_sections(parsed,rb.parser);rb.recover_split_figures(parsed,rb.parser)
        rb.recover_caption_text(parsed,rb.parser);rb.complete_column_captions(parsed)
        rb.recover_numbered_equations(parsed,rb.parser);rb.filter_equation_candidates(parsed)
        numbers={n for e in parsed.equations for n in e.group_numbers}
        self.assertTrue({f'A{i}' for i in range(1,13)}<=numbers)
        self.assertNotIn('FIG. 6.',next(f.caption for f in parsed.figures if f.number==4))
        self.assertGreater(len(rb.analyzer.closing_text(parsed)),1000)
        with __import__('pymupdf').open(source) as document:
            for number,prefix in [(1,'dT'),(6,'dP')]:
                eq=next(e for e in parsed.equations if number in e.group_numbers)
                crop_text=document[eq.page].get_textbox(__import__('pymupdf').Rect(eq.group_bbox or eq.bbox))
                self.assertIn(prefix,crop_text,'Derivative numerator lost outside the equation crop')
        gaps=rb.equation_gaps(parsed)
        for number in (22,23):self.assertTrue(number in numbers or str(number) in gaps.get('',[]))
        for eq in parsed.equations:
            if not eq.group_numbers:
                self.assertNotIn('(b)No TTA',eq.text);self.assertNotEqual(eq.text,'i,j,i̸=j')
