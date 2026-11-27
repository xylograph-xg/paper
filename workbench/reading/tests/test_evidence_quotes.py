import unittest
from read.app.evidence_quotes import verify_quotes

SOURCE='The first measurement was recorded at room temperature. A second experiment used a different preparation. These results depend on the sample conditions.'


class LiteralQuotes(unittest.TestCase):
    def test_continuous_quote_and_presentation_wrappers(self):
        first=SOURCE.split('. ')[0]+'.'
        for raw in (first,'"'+first+'"','- "'+first+'"','1. “'+first+'”'):
            self.assertTrue(verify_quotes(raw,SOURCE,SOURCE)[1],raw)

    def test_every_list_item_must_match_source_and_actual_input(self):
        first='The first measurement was recorded at room temperature.'
        second='A second experiment used a different preparation.'
        raw='- "'+first+'"\n- "'+second+'"'
        quotes,ok=verify_quotes(raw,SOURCE,SOURCE)
        self.assertTrue(ok);self.assertEqual(quotes,[first,second])
        self.assertFalse(verify_quotes(raw,SOURCE,first)[1])
        self.assertFalse(verify_quotes(raw+'\n- "An invented third experiment was successful."',SOURCE,SOURCE)[1])

    def test_shortened_latex_or_ellipsized_quotes_are_not_accepted(self):
        for raw in ('At room temperature the first measurement was recorded.',
                    'The first measurement...room temperature.',
                    r'\text{The first measurement was recorded at room temperature.}',
                    'room temp', ''):
            self.assertFalse(verify_quotes(raw,SOURCE,SOURCE)[1],raw)

    def test_line_wrapping_and_typography_preserve_existing_rules(self):
        raw='"The first measurement was recorded\nat room temperature."'
        self.assertTrue(verify_quotes(raw,SOURCE,SOURCE)[1])
        self.assertFalse(verify_quotes('“The first measurement was recorded at 77 K.”',SOURCE,SOURCE)[1])


class ReaderIntegration(unittest.TestCase):
    def test_list_validation_preserves_required_parts_and_sent_scope(self):
        from reading.reading_bridge import analyzer
        first='The first measurement was recorded at room temperature.'
        second='A second experiment used a different preparation.'
        raw='- "'+first+'"\n- "'+second+'"'
        parts={k:'synthetic content' for k in ('图面信息','正文总结','详细解释','结果','一句话结果')}
        parts['原文依据']=raw
        self.assertEqual(analyzer.validate_parts(parts,SOURCE,'图面信息'),raw)
        self.assertTrue(analyzer.check_parts(parts,SOURCE,'图面信息',provided=SOURCE)[1])
        self.assertFalse(analyzer.check_parts(parts,SOURCE,'图面信息',provided=first)[1])
        parts['结果']=''
        with self.assertRaises(ValueError):analyzer.check_parts(parts,SOURCE,'图面信息')
