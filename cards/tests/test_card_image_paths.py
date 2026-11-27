import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from workbench.web import card_image_asset

class CardImagePathTests(unittest.TestCase):
    def test_relocated_images_resolve_without_modifying_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'paper_card';image=root/'Fig_1/figure.png';image.parent.mkdir(parents=True);image.write_bytes(b'fixture')
            self.assertEqual(card_image_asset(root,'/old/Desktop/paper_card/Fig_1/figure.png'),'Fig_1/figure.png')
            self.assertEqual(card_image_asset(root,str(image)),'Fig_1/figure.png')
            self.assertEqual(card_image_asset(root,'Fig_1/figure.png'),'Fig_1/figure.png')
            self.assertIsNone(card_image_asset(root,'/old/other_card/Fig_1/figure.png'))
            self.assertIsNone(card_image_asset(root,'/old/paper_card/../../outside.png'))
            self.assertIsNone(card_image_asset(root,None))

if __name__=='__main__':unittest.main()
