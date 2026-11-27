"""Three source-checked transcriptions. Run with the paper test environment."""
import json
import math
from pathlib import Path

import numpy as np
import sympy as sp
from sympy.parsing.latex import parse_latex

HERE = Path(__file__).resolve().parent
# Single-letter parser aliases have an explicit one-to-one map to code variables.
cases = [
    dict(name='quantum_yield', paper='74b923ba-153f-461f-ac46-d3d1967cea43', region='p0001-000004',
         equation=1, image='yield.png', latex=r'\Phi=\frac{\kappa_r}{\kappa_r+\kappa_{nr}}',
         rhs=r'\frac{a}{a+b}', variables={'a':'k_r','b':'k_nr'},
         domain='Two nonnegative rates in the same units, with positive sum.',
         tests=[([1,3],.25),([2,0],1),([0,1],0)]),
    dict(name='stretched_luminance', paper='23116e45-48dc-471e-b93f-24fe3ed31ec0', region='p0001-000003',
         equation=1, image='lifetime.png', latex=r'L(t)=L_0\exp\left[-\left(\frac{t}{\tau}\right)^{\beta}\right]',
         rhs=r'a\exp{\left(-\left(\frac{t}{b}\right)^{c}\right)}',
         variables={'a':'L0','t':'t','b':'tau','c':'beta'},
         domain='Nonnegative time and initial luminance, positive tau and beta. Time and tau use the same units.',
         tests=[([5,0,2,.7],5),([5,2,2,.7],5/math.e),([5,8,2,.5],5*math.exp(-2))]),
    dict(name='field_mobility', paper='b6d1a18f-e061-47b4-92d6-b1d439bf664f', region='p0004-000019',
         equation=2, image='mobility.png', latex=r'\mu_p=\mu_{E=0}\exp\left(\sqrt{\frac{E}{E_0}}\right)',
         rhs=r'a\exp{\left(\sqrt{\frac{b}{c}}\right)}', variables={'a':'mu_zero','b':'field','c':'field_scale'},
         domain='Nonnegative field magnitude and positive field scale in the same units. Output has mobility units.',
         tests=[([2,0,3],2),([2,3,3],2*math.e),([2,12,3],2*math.exp(2))])
]

def main():
    module=['"""Generated scalar functions. Input domains are documented per function."""','import math','']
    records=[]
    for case in cases:
        aliases=case['variables']
        expr=parse_latex(case['rhs'],strict=True)
        assert {s.name for s in expr.free_symbols}==set(aliases)
        expr=expr.xreplace({sp.Symbol(k):sp.Symbol(v) for k,v in aliases.items()})
        arguments=','.join(aliases.values())
        module.extend(['',f"def {case['name']}({arguments}):",f'    """{case["domain"]}"""',f'    return {sp.pycode(expr)}',''])
        vec=sp.lambdify(list(map(sp.Symbol,aliases.values())),expr,'numpy')
        inputs,expected=zip(*case['tests'])
        np.testing.assert_allclose(vec(*np.asarray(inputs).T),expected,rtol=1e-12)
        records.append(dict(case,sympy=str(expr),mathml=sp.printing.mathml(expr),python_rhs=sp.pycode(expr)))
    target=HERE/'formula_functions.py'
    target.write_text('\n'.join(module)+'\n')
    import importlib.util
    spec=importlib.util.spec_from_file_location('checked_formulas',target)
    functions=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(functions)
    for case in cases:
        for args,value in case['tests']:
            assert math.isclose(getattr(functions,case['name'])(*args),value,rel_tol=1e-12,abs_tol=1e-14)
    (HERE/'formulas.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
    print('3 verified transcriptions; 9 scalar and 9 vector elements passed')
if __name__=='__main__':
    main()
