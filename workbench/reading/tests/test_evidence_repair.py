"""Regression checks against the actual externally reviewed source documents."""
import unittest
from reading.reading_bridge import ROOT, parser, analyzer, repair_sections, recover_split_figures, recover_numbered_equations, filter_equation_candidates, include_adjacent_definitions, complete_column_captions, recover_caption_text
from review.card_evaluation import SAMPLES


class ReviewedEvidence(unittest.TestCase):
    def parse(self,kind):
        source=ROOT/'data/deep_read'/SAMPLES[kind]/'source.pdf'
        if not source.exists():
            self.skipTest('Optional reviewed source corpus is not installed')
        p=parser.parse_pdf(source,{**analyzer.load_config(),'max_equation_groups':200})
        repair_sections(p,parser);recover_split_figures(p,parser)
        recover_caption_text(p,parser)
        complete_column_captions(p);recover_numbered_equations(p,parser)
        filter_equation_candidates(p)
        parser._collect_candidates(p,12000)
        parser._attach_equation_context(p,p.equations,12000)
        include_adjacent_definitions(p)
        return p

    def test_review_recovers_all_figures_and_formal_equations(self):
        p=self.parse('equation_heavy')
        self.assertEqual({f.number for f in p.figures},set(range(1,8)))
        self.assertEqual({m['number'] for e in p.equations for m in e.members
                          if m.get('number')},set(range(1,7)))
        self.assertIn('Scholes',p.figures[0].caption)
        self.assertGreater(len(p.section_text('Introduction')),150)
        e=next(e for e in p.equations if e.number==5)
        self.assertGreater(e.group_bbox[3]-e.group_bbox[1],160)
        self.assertIn('Quintet',e.text)

    def test_mixed_covers_28_numbered_equations_and_sections(self):
        p=self.parse('mixed')
        self.assertEqual({m['number'] for e in p.equations for m in e.members
                          if m.get('number')},set(range(1,29)))
        self.assertGreater(len(p.section_text('Introduction')),150)
        self.assertGreater(len(analyzer.closing_text(p)),150)
        self.assertEqual(len(p.figures),8)
        numbered=[min(e.group_numbers) for e in p.equations if e.group_numbers]
        self.assertEqual(numbered,sorted(numbered),'Numbered derivation interleaves PDF columns')
        for number,prose in [(5,'To conclude the discussion'),(8,'We then explore')]:
            self.assertNotIn(prose,next(f.caption for f in p.figures if f.number==number))
        e14=next(e for e in p.equations if e.group_numbers==[14])
        e15=next(e for e in p.equations if 15 in e.group_numbers)
        self.assertLess(e14.group_bbox[3],e15.group_bbox[1], 'Separate displays overlap across explanatory prose')
        self.assertNotIn('two-phonon',e14.text)
        for eq in p.equations:
            self.assertLess(eq.group_bbox[2]-eq.group_bbox[0],p.page_sizes[eq.page][0]*.55,
                            f'{eq.group_label} combined unrelated columns')

    def test_image_paper_definitions_and_column_boundaries(self):
        p=self.parse('image_heavy')
        self.assertEqual([e.number for e in p.equations],[1,2])
        e=p.equations[0]
        self.assertLess(e.group_bbox[2],p.page_sizes[e.page][0]*.52)
        text=' '.join(p.paragraphs[c['index']].text for c in e.context)
        self.assertIn('balance',text.lower())
        self.assertGreater(len(analyzer.closing_text(p)),150)
        self.assertIn('architecture',p.figures[0].caption.lower())


if __name__=='__main__':
    unittest.main()
