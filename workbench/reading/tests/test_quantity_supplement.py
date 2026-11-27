import unittest,json
from types import SimpleNamespace as NS
from reading.quantity_supplement import supplement_quantities, parse_supplement

class Client:
    calls=[]
    system='original'
    def chat(self,prompt,images=None,retries=0):
        self.calls.append((prompt,images))
        return json.dumps({'items':[{'line_index':2,'explanation':'通常表示速率系数，本文具体约定须确认。'}]},ensure_ascii=False)

class QuantitySupplement(unittest.TestCase):
    def run_case(self,text):
        Client.calls=[]
        eq=NS(label='Eq',quantities=text,error=None,image_path='formula.png',equation_text='x=y')
        card=NS(title='Paper',equations=[eq],meta={},warnings=[])
        audit=supplement_quantities(card,None,Client(),lambda p,e:'Original surrounding definitions')
        return eq,card,audit
    def test_exact_one_third_context_and_known_lines(self):
        eq,card,audit=self.run_case('- x：位置\n- y：时间\n- k：正文未说明')
        self.assertEqual(len(Client.calls),1)
        self.assertIn('Original surrounding definitions',Client.calls[0][0])
        self.assertEqual(Client.calls[0][1],['formula.png'])
        self.assertEqual(eq.quantities.splitlines()[:2],['- x：位置','- y：时间'])
        self.assertIn('通用知识补充，本文定义未确认',eq.quantities)
        self.assertEqual(audit[0]['supplemented'],1)
    def test_latex_invalid_json_escape_preserves_content(self):
        raw=r'{"items":[{"line_index":0,"explanation":"$\hat{H}$ 常见的算符"}]}'
        parsed=parse_supplement(raw)
        self.assertEqual(parsed['items'][0]['explanation'],r'$\hat{H}$ 常见的算符')
        with self.assertRaises(json.JSONDecodeError):parse_supplement('{invalid}')
    def test_below_threshold_does_not_call_model(self):
        self.run_case('- x：位置\n- y：时间\n- k：正文未说明\n- z：长度')
        self.assertEqual(Client.calls,[])
    def test_invalid_index_preserves_original(self):
        eq,card,audit=self.run_case('- k：正文未说明')
        self.assertEqual(eq.quantities,'- k：正文未说明')
        self.assertEqual(audit[0]['status'],'failed')

if __name__=='__main__':unittest.main()
