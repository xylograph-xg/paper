# OLED 公式裁图与代码转换 · 2026-11-25

在当前登记库中按标题或摘要匹配 OLED、相关 OLED 缩写、organic light emitting diode/device/display、organic electroluminescent device 等明确写法。取消标题建模词、公式数和页数门槛，扫描冻结清单上的所有合格 PDF。仅在正文提及 OLED、或仅使用发光机制名称的文章可能落在此清单之外。命中也包括应用背景中提及 OLED 的文章、学位论文和显示器件研究。

| 覆盖 | 数量 |
|---|---:|
| 匹配登记记录 | 16,195 |
| 无已登记可用 PDF | 13,092 |
| 身份、版本或范围保护 | 23 |
| 原件与登记 SHA-256 不一致 | 2 |
| 实际扫描 PDF / 页 | 3,078 / 83,752 |
| 按登记原件处理 / 疑似补充材料 / 补充材料首页 | 2,969 / 90 / 19 |
| PyMuPDF 文本、版式和弱视觉候选区（含同式不同裁法与稀疏整页） | 361,144 |
| 按文献、PDF 页、疑似印刷式号合并后的候选位置 | 17,752，涉及 1,229 篇 |
| Poppler 再渲染的稀疏或告警页 / 附加像素候选区 | 2,307 / 5,368 |
| 对照原图转录并通过数值测试的代码示例 | 3 |

## 数据入口

[跨论文 SQLite 索引](/Volumes/ssd-1t-1/paper-library/oled-formulas-20261125/formulas.sqlite3) · [全套裁图和索引目录](/Volumes/ssd-1t-1/paper-library/oled-formulas-20261125) · [代码与原图示例](examples/formulas.json)

- `papers` 保留论文 ID、标题、源文件、源哈希和处理状态。补充材料来源独立标记。首页与次页标题词覆盖度用于提示可能错配；有 8 份低于 0.65。覆盖度不能确定科学身份。合订文件内的正文与附录尚未逐页划界。
- `regions` 保存页码、候选类型、PDF 坐标、裁图坐标、比例、可读取的原始文字、压缩包相对路径和 PNG 文件名。PDF 文本可能丢失根号、分数线或上下标。各个 `papers/*.zip`、`layout/*.zip` 可独立解压浏览。页码从 1 开始。
- `printed_labels` 方便按文献、页和式号定位，`numbered_candidates` 保留相应裁图。图中序号、晶面指数和参考文献序号也可能命中；同一页上的相同标签可能对应多处位置。`regions` 仍保留这些不同位置。
- `raster_pages` 和 `raster_bands` 定位备用渲染整页和成对横线候选。1,492 页文字稀疏，818 页有解码提示，两组并集 2,307 页。4 页来自同一个交叉引用表损坏的 PDF，第二次使用临时修复副本成功渲染，原件哈希与第一次报错留在记录中。
- `code_examples` 将转录的 LaTeX、生成的 Python、变量别名、输入域和测试值绑定到原始裁图。机器候选和示例分别存储。经 ZIP CRC 检查全部归档，检查索引完整性、页码和图片引用；这些检查只验证存储与定位。
- 区域抽查看到衍射图的 (004)、器件图的 (2)、段落中的近似数值和嵌入插图。扫描件及轮廓字仍可能漏式。试测所得前十篇命中率针对论文排序，本次宽口径裁图的准确率尚未测量。

读取一个示例原图只需标准库。其他候选可以按论文标题或 `regions.kind` 查询相同字段。

```python
import sqlite3
import zipfile
from pathlib import Path

root = Path("/Volumes/ssd-1t-1/paper-library/oled-formulas-20261125")
with sqlite3.connect((root / "formulas.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
    archive, image = db.execute("""
        SELECT r.archive, r.image FROM regions r
        JOIN code_examples e USING (paper_id, region_id)
        WHERE e.paper_id = ?
    """, ("74b923ba-153f-461f-ac46-d3d1967cea43",)).fetchone()
with zipfile.ZipFile(root / archive) as z:
    png_bytes = z.read(image)
```

## 把裁图转成可执行代码

| 输入情况 | 转换手段 | 需要核对的内容 |
|---|---|---|
| 有同版本 TeX、JATS 或结构化 MathML | 直接取作者表达式，处理宏和符号映射，再解析到 SymPy | 与同页公式编号、版本、正文定义相符；Presentation MathML 往往只表达排版 |
| 数字 PDF 且数学字形可读 | 用字符坐标与基线重建分子、分母、上下标生成 LaTeX 或表达式树 | 单个文本块可含多式或跨栏；普通复制文本会丢分数线 |
| 仅有位图或轮廓字 | 用公式专用 OCR，例如 pix2tex，生成 LaTeX，再回渲染对照 | 符号、分数线范围、根号范围、上下标和矩阵维度；本次未启用 OCR 模型或外部服务 |
| 要求输入条件、单位或多行推导 | 结合裁图和原文符号定义转录为 SymPy，按用途生成 Python、NumPy 或 C | 区分定义、近似、隐式方程和可求值函数。积分还需要积分域或离散化方案 |

本次实际跑通“原图核对转录 → LaTeX 右侧与显式变量映射 → SymPy → 标量 Python / 向量 NumPy”。三个例子分别覆盖分式、嵌套幂、根式指数。每式 3 个输入点，分别核对标量和向量结果，属于转录与生成代码的数值一致性试验。其他候选仅保留证据，后续可换识别器重用原图。[转换脚本](examples/convert.py) · [可运行函数](examples/formula_functions.py) · [原图及对应关系](examples/formulas.json)
