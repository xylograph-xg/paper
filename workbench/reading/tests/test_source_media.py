import io
import json
import tarfile
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import pymupdf
from reading.source_media import unpack_source, index_source, prepare_source
from reading.media_evidence import match_caption, validate_latex, vision_transcriber, render_dual
from reading.reading_bridge import filter_equation_candidates

class SourceMedia(unittest.TestCase):
    def archive(self,name,data=b'hi',link=False):
        out=io.BytesIO()
        with tarfile.open(fileobj=out,mode='w:gz') as tar:
            m=tarfile.TarInfo(name)
            if link:m.type=tarfile.SYMTYPE;m.linkname='/tmp/outside';tar.addfile(m)
            else:m.size=len(data);tar.addfile(m,io.BytesIO(data))
        return out.getvalue()
    def test_archive_rejects_escape_and_links(self):
        with tempfile.TemporaryDirectory() as td:
            for name,link in [('../escape',False),('/absolute',False),('link',True)]:
                with self.assertRaises(ValueError):unpack_source(self.archive(name,link=link),td)
            self.assertEqual(list(Path(td).iterdir()),[])
    def test_tex_inputs_nested_captions_graphics_macro_and_multiline_equations(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'images').mkdir();(root/'images/f.pdf').write_bytes(b'original')
            (root/'main.tex').write_text(r'''\documentclass{article}
\newcommand{\myop}[1]{\mathbf{#1}}
\begin{document}\input{results}\end{document}''')
            (root/'results.tex').write_text(r'''\graphicspath{{images/}}
% \includegraphics{missing}
\begin{figure*}\includegraphics[width=\linewidth]{f}\caption[short]{Long caption with {nested} groups and $E$.}\label{fig:one}\end{figure*}
\begin{align}E &= \myop{x} \\ F &= y\label{eq:a}\end{align}
\[ x^2+y^2 \]''')
            index=index_source(root)
            self.assertEqual(index['figures'][0]['graphics'][0]['path'],'images/f.pdf')
            self.assertIn('{nested}',index['figures'][0]['caption'])
            self.assertTrue(index['figures'][0]['in_main_tree'])
            self.assertEqual(len(index['equations']),2);self.assertEqual(index['equations'][0]['labels'],['eq:a'])
            self.assertIn(r'\newcommand{\myop}[1]{\mathbf{#1}}',index['macros'])
    def test_source_fetch_is_versioned_cached_and_failure_does_not_fail_card(self):
        with tempfile.TemporaryDirectory() as td:
            def fetch(url,path,max_bytes):
                self.assertTrue(url.endswith('/2406.02703v2'));Path(path).write_bytes(self.archive('main.tex',b'\\documentclass{article}\\begin{document}ok\\end{document}'))
            with patch('reading.source_media.pdf_version',return_value='2406.02703v2'):
                self.assertEqual(prepare_source(td,fetch)['state'],'available')
                self.assertEqual(prepare_source(td,lambda *a,**k:self.fail('cache fetched twice'))['state'],'available')
            with patch('reading.source_media.pdf_version',return_value='2406.02703v3'):
                s=prepare_source(td,lambda *a,**k:(_ for _ in ()).throw(ValueError('HTTP failure')))
                self.assertEqual(s['state'],'unavailable');self.assertIn('HTTP failure',s['reason'])
    def test_caption_matching_requires_unique_evidence(self):
        text='Experiment comparing time resolved absorption for two differently prepared molecular thin films under identical excitation conditions.'
        f={'caption':text,'in_main_tree':True}
        self.assertEqual(match_caption('Fig. 3 | '+text,[f]),0)
        self.assertIsNone(match_caption(text,[f,f]));self.assertIsNone(match_caption('Short',[f]))
    def test_latex_syntax_is_not_semantic_verification(self):
        self.assertTrue(validate_latex(r'\begin{bmatrix}x_1 & y^2\\ 0 & 1\end{bmatrix}')[0])
        for s in [r'\frac{a}{b',r'\begin{align}x\end{matrix}',r'\input{/etc/passwd}']:
            self.assertFalse(validate_latex(s)[0])
    def test_vision_reuses_supplied_client_and_keeps_uncertainty(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'eq.png';path.write_bytes(b'image')
            calls=[]
            def chat(prompt,**kw):calls.append(kw);return json.dumps({'latex':r'x_1=y^2'})
            latex,status=vision_transcriber(NS(chat=chat))(path)
            self.assertEqual(latex,r'x_1=y^2');self.assertIn('未人工核验',status);self.assertEqual(calls[0]['images'],[path])
    def test_multiple_groups_same_page_have_unique_screenshots(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);doc=pymupdf.open();doc.new_page();doc.save(root/'source.pdf');doc.close()
            from reading.reading_bridge import parser
            eqs=[parser.Equation(label='unnumbered',number=None,page=0,bbox=[20,20+i*80,200,50+i*80],text='x=y',members=[{'text':'x=y','number':None,'page':1,'index':i,'bbox':[20,20+i*80,200,50+i*80]}],group_label='group') for i in range(2)]
            parsed=NS(equations=eqs,figures=[],warnings=[],pdf_path=str(root/'source.pdf'))
            filter_equation_candidates(parsed);render_dual(parsed,root,150,300,parser.render_figures)
            self.assertNotEqual(eqs[0].image_path,eqs[1].image_path)
            self.assertTrue(all(Path(e.image_path).exists() for e in eqs))
    def test_group_members_do_not_become_duplicate_cards(self):
        head=NS(page=0,members=[{'text':'x=y','number':None,'page':1,'index':0},{'text':'a=b','number':None,'page':1,'index':1}])
        parsed=NS(equations=[head,NS(members=[])],figures=[],warnings=[])
        filter_equation_candidates(parsed);self.assertEqual(parsed.equations,[head])
    def test_vector_panel_above_bad_crop_is_preserved(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);doc=pymupdf.open();page=doc.new_page(width=400,height=500)
            page.draw_rect([80,80,160,140],fill=(1,0,0),color=(1,0,0))
            page.draw_rect([80,230,160,290],fill=(0,0,1),color=(0,0,1))
            page.insert_text((30,380),'Fig. 1 | Example full figure.',fontsize=7);doc.save(root/'source.pdf');doc.close()
            f=NS(label='Fig. 1',crop_bbox=[30,200,190,375],caption_bbox=[30,372,190,382],crop_page=0,caption_page=0,crop_note='')
            parsed=NS(pdf_path=str(root/'source.pdf'),figures=[f],equations=[],warnings=[],extraction_audit={})
            def render(p,out,dpi,eq_dpi):
                with pymupdf.open(p.pdf_path) as d:d[0].get_pixmap(clip=pymupdf.Rect(f.crop_bbox)).save(root/'crop.png')
            render_dual(parsed,root,72,300,render)
            with Image.open(root/'crop.png') as im:
                self.assertTrue(any(r>200 and g<50 and b<50 for r,g,b in im.convert('RGB').get_flattened_data()))
                self.assertTrue(any(b>200 and r<50 and g<50 for r,g,b in im.convert('RGB').get_flattened_data()))
    def test_caption_continuation_kept_without_same_height_body_prose(self):
        from reading.media_evidence import complete_column_captions
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);d=pymupdf.open();p=d.new_page(width=500,height=500)
            p.insert_text((30,340),'Fig. 1 | Caption begins',fontsize=7)
            p.insert_text((240,340),'and continues in the other column.',fontsize=7)
            p.insert_text((240,350),'Body prose must not be appended.',fontsize=10)
            d.save(root/'source.pdf');d.close()
            with pymupdf.open(root/'source.pdf') as d:
                box=next(line['bbox'] for b in d[0].get_text('dict')['blocks'] if b.get('type')==0 for line in b['lines'] if line['spans'][0]['text'].startswith('Fig.'))
            f=NS(caption_bbox=list(box),caption_page=0,caption='Fig. 1 | Caption begins')
            complete_column_captions(NS(pdf_path=str(root/'source.pdf'),figures=[f]))
            self.assertIn('continues',f.caption);self.assertNotIn('Body prose',f.caption)
