"""Original candidate terminology; design references are recorded in REFERENCES.md.

No code, dataset, model weights or scientific answers are imported from repositories.
These terms propose a vocabulary, never evidence about an individual paper.
"""
OLED_TERMS = (
    ('topic', '有机发光', 'organic luminescence', ('有机发光材料',)),
    ('topic', '热活化延迟荧光', 'thermally activated delayed fluorescence', ('TADF',)),
    ('topic', '光物理性质', 'photophysical properties', ('光物理',)),
    ('object', '主客体体系', 'host-dopant system', ('host-guest system', '主体掺杂体系')),
    ('object', '纯发光体', 'pure emitter', ('neat emitter',)),
    ('object', '多掺杂体系', 'multi-dopant system', ('multi-dopant blend',)),
    ('object', '多层发光结构', 'multi-layer emission structure', ('多层发光层',)),
    ('question', '分子结构与发光性质关系', 'molecular structure–luminescence relationship', ('structure-property relationship',)),
    ('question', '发光波长预测', 'emission wavelength prediction', ('photoluminescence prediction',)),
    ('mechanism', '反向系间窜越', 'reverse intersystem crossing', ('RISC',)),
    ('method', '光致发光测量', 'photoluminescence measurement', ('PL spectroscopy',)),
    ('method', '图神经网络', 'graph neural network', ('GNN',)),
    ('method', '分子指纹建模', 'molecular fingerprint modeling', ('molecular fingerprint baseline',)),
    ('method', '图表数据提取', 'figure and table data extraction', ('table extraction',)),
    ('application', '有机发光二极管', 'organic light-emitting diode', ('OLED', 'OLEDs')),
    ('learning', '入门综述', 'introductory review', ()),
    ('learning', '方法参考', 'method reference', ()),
    ('learning', '关键案例', 'key case study', ()),
    ('learning', '对照阅读', 'comparative reading', ()),
)
