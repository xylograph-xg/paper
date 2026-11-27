"""Generic regressions exposed by the short-paper prompt cycle."""
import unittest
from read.app.analyzer import parse_info, split_marked, check_parts
from reading.prompt_overlays import render_review_prompt
from types import SimpleNamespace

class ShortCyclePrompts(unittest.TestCase):
    def test_heading_free_conclusion_does_not_use_reference_tail(self):
        from read.app.analyzer import closing_text
        source='In conclusion, the experiment distinguishes local behavior from the ensemble measurement.'
        parsed=SimpleNamespace(section_text=lambda name,limit: '',paragraphs=[
            SimpleNamespace(role='body',text=source),SimpleNamespace(role='body',text='[1] Synthetic reference')])
        self.assertEqual(closing_text(parsed),source)

    def test_quote_candidates_exclude_paraphrases_and_keep_exact_source(self):
        from reading.prompt_overlays import literal_quote_candidates
        source='The measured response suggests a possible relation. The boundary condition remains uncertain.'
        parsed=SimpleNamespace(page_texts=[source])
        candidates=literal_quote_candidates(parsed,'The measured response proves the mechanism.\n'+source)
        self.assertNotIn('The measured response proves the mechanism.',candidates)
        self.assertEqual(candidates,['The measured response suggests a possible relation.','The boundary condition remains uncertain.'])

    def test_summary_overlay_does_not_inherit_equation_output_requirements(self):
        result=render_review_prompt('introduction',{'text':'Synthetic original purpose'},None,
            lambda name,values,directory:values['text'],SimpleNamespace())
        self.assertIn('仅输出模板要求的四项',result)
        self.assertNotIn('===原文依据===',result)

    def test_metadata_prose_cannot_override_author_or_add_scientific_keys(self):
        raw='标题：Synthetic evidence\n作者：A. Example, B. Reader\n关键词：spin, measurement\n**作者的解释：** unrelated scientific interpretation\n作者：another duplicate\n变量含义：time\n$t$：time'
        self.assertEqual(parse_info(raw),{'标题':'Synthetic evidence','作者':'A. Example, B. Reader','关键词':'spin, measurement'})

    def test_exact_metadata_aliases_and_bold_display_are_supported(self):
        self.assertEqual(parse_info('**作者：** A. Example\n研究对象：crystal\n主要方法：measurement\nDOI: 10.0000/example'),{'作者':'A. Example','DOI':'10.0000/example','研究对象':'crystal','主要方法':'measurement'})

    def test_markdown_prefix_is_only_presentation_not_new_delimiter(self):
        text='\n'.join('### ==='+name+'===\ncontent' for name in ('图面信息','正文总结','详细解释','结果','一句话结果','原文依据'))
        self.assertEqual(len(split_marked(text)),6)
        with self.assertRaisesRegex(ValueError,'重复'):split_marked(text+'\n===结果===\nother')
        with self.assertRaises(ValueError):split_marked('ordinary prose ===结果=== inline text')

    def test_presentation_compatibility_does_not_accept_paraphrased_evidence(self):
        names=('量清单','正文总结','详细解释','结果','一句话结果','原文依据')
        parts={name:'content' for name in names};parts['原文依据']='The measurement proves every proposed effect.'
        _,verified=check_parts(parts,'The measurement suggests a possible effect.','量清单')
        self.assertFalse(verified)

    def test_wrapped_parameter_definition_keeps_original_numeric_fragment(self):
        from read.app.evidence_preparation import source_definitions
        first='with q1 ≈12 ms (q1/2'
        page=first+'\n1 ≈3 ms) and q2 ≈270 ms.\nThe model is conditional.'
        parsed=SimpleNamespace(paragraphs=[SimpleNamespace(role='body',text=first,page=0,index=0)],page_texts=[page])
        result=source_definitions(parsed,'q1 = a; q2 = b')
        self.assertIn('q2 ≈270 ms',result)
        self.assertIn(page,result)

    def test_fragmented_inline_definition_retrieves_original_meaning(self):
        from read.app.evidence_preparation import source_definitions
        texts=['The local variables are defined below.', 'vAA = (GAA', '0 - GAA', '1)/h, and vBB = (GBB', '0 - GBB', '1)/h are differences between two states in each corresponding configuration.']
        parsed=SimpleNamespace(paragraphs=[SimpleNamespace(role='body',text=t,page=0,index=i) for i,t in enumerate(texts)],page_texts=['\n'.join(texts)])
        result=source_definitions(parsed,'v^{AA} - v^{BB}')
        self.assertIn('vAA = (GAA',result)
        self.assertIn('corresponding configuration',result)

    def test_metadata_overlay_does_not_request_scientific_explanation(self):
        scopes={}
        result=render_review_prompt('paper_info',{'metadata':'{}','first_pages':'Source author area'},None,
            lambda name,values,directory:'Only metadata '+values['first_pages'],SimpleNamespace(),scopes=scopes)
        self.assertIn('关键词行后结束',result)
        self.assertNotIn('物理量解释每项独立',result)
        self.assertNotIn('===原文依据===',result)
        self.assertFalse(scopes['paper_info'][0]['truncated'])

if __name__=='__main__':unittest.main()
