"""Edit a background composer on the owner's connection without OS focus."""


def replace(box, text):
    rich = box.evaluate(
        "el => el.isContentEditable && (!!el.pmViewDesc || el.classList.contains('ProseMirror'))"
    )
    if rich:
        # ProseMirror's DOM observer commits this edit to its document. Use text
        # nodes so literal markup and Unicode stay plain text. No focused input,
        # clipboard event, keystroke, or send action is needed.
        box.evaluate("""(el, text) => {
          const doc = el.ownerDocument;
          const paragraphs = doc.createDocumentFragment();
          for (const line of text.split('\\n')) {
            const paragraph = doc.createElement('p');
            paragraph.append(line ? doc.createTextNode(line) : doc.createElement('br'));
            paragraphs.append(paragraph);
          }
          el.replaceChildren(paragraphs);
        }""", text)
        box.evaluate("() => new Promise(resolve => setTimeout(resolve, 150))")
        model = box.evaluate("""el => {
          const doc = el.pmViewDesc?.node;
          return doc ? doc.textBetween(0, doc.content.size, '\\n') : null;
        }""")
        if model is None or model.split() != text.split():
            raise RuntimeError('后台输入核对失败，未发送：编辑器文档与原提示不一致')
        return

    page = box.page
    session = page.context.new_cdp_session(page)
    try:
        # This changes document focus semantics, never the selected tab/window.
        session.send('Emulation.setFocusEmulationEnabled', {'enabled': True})
        box.fill(text)
        box.evaluate("() => new Promise(resolve => setTimeout(resolve, 150))")
    finally:
        try:
            session.send('Emulation.setFocusEmulationEnabled', {'enabled': False})
        finally:
            session.detach()
