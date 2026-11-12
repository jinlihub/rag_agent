# -*- coding: utf-8 -*-
"""生成《产品设计与技术架构.pptx》(17页, 16:9)。part1: 框架与辅助函数。"""
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn
from lxml import etree

NAVY = RGBColor(0x1F, 0x4E, 0x79)
BLUE = RGBColor(0x2E, 0x75, 0xB6)
SKY = RGBColor(0x9D, 0xC3, 0xE6)
LIGHT = RGBColor(0xDE, 0xEB, 0xF7)
PALE = RGBColor(0xF4, 0xF8, 0xFC)
GRAY = RGBColor(0x59, 0x59, 0x59)
MUTE = RGBColor(0x8A, 0x8A, 0x8A)
DARK = RGBColor(0x26, 0x26, 0x26)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
ORANGE = RGBColor(0xED, 0x7D, 0x31)
LORANGE = RGBColor(0xFD, 0xE9, 0xD9)
LGRAY = RGBColor(0xEC, 0xEC, 0xEC)
RED = RGBColor(0xC0, 0x50, 0x4D)
LRED = RGBColor(0xFD, 0xEC, 0xEA)
GREEN = RGBColor(0x53, 0x81, 0x35)
FONT = '微软雅黑'
SW, SH = 13.333, 7.5
C, L, R = PP_ALIGN.CENTER, PP_ALIGN.LEFT, PP_ALIGN.RIGHT
MID = MSO_ANCHOR.MIDDLE


def _font(run, size=12, bold=False, color=DARK):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = FONT
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn('a:ea'))
    if ea is None:
        ea = etree.SubElement(rPr, qn('a:ea'))
    ea.set('typeface', FONT)


def _paras(tf, paras, align=C):
    """paras item: str | dict(t,s,b,c,a,sa,sb) | dict(runs=[(t,s,b,c)], sa)"""
    for i, item in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        if isinstance(item, str):
            item = {'t': item}
        p.alignment = item.get('a', align)
        p.space_after = Pt(item.get('sa', 2))
        p.space_before = Pt(item.get('sb', 0))
        if 'runs' in item:
            for (t, s, b, c) in item['runs']:
                r = p.add_run()
                r.text = t
                _font(r, s, b, c)
        else:
            r = p.add_run()
            r.text = item.get('t', '')
            _font(r, item.get('s', 12), item.get('b', False), item.get('c', DARK))


def text(slide, x, y, w, h, paras, align=L, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    _paras(tf, paras, align)
    return tb


def box(slide, x, y, w, h, paras, fill=LIGHT, line=None, radius=None,
        align=C, anchor=MID, lw=1.0):
    shape_t = MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE
    shp = slide.shapes.add_shape(shape_t, Inches(x), Inches(y), Inches(w), Inches(h))
    if radius:
        try:
            shp.adjustments[0] = radius
        except Exception:
            pass
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(lw)
    shp.shadow.inherit = False
    tf = shp.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.06)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    _paras(tf, paras, align)
    return shp


def bar(slide, x, y, w, h, fill, line=None):
    return box(slide, x, y, w, h, [], fill=fill, line=line)


def arrow(slide, x, y, w, h, fill=BLUE, direction='r'):
    shp_t = MSO_SHAPE.RIGHT_ARROW if direction == 'r' else (
        MSO_SHAPE.DOWN_ARROW if direction == 'd' else MSO_SHAPE.LEFT_ARROW)
    shp = slide.shapes.add_shape(shp_t, Inches(x), Inches(y), Inches(w), Inches(h))
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def note(slide, txt):
    slide.notes_slide.notes_text_frame.text = '讲稿：' + txt


def deck(prs, section, title, page, hint):
    """内容页统一版式，返回 slide。"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bar(slide, 0, 0, SW, 0.10, NAVY)
    text(slide, 0.62, 0.28, 7.5, 0.3, [{'t': section, 's': 12, 'b': True, 'c': BLUE}])
    text(slide, 0.60, 0.56, 10.4, 0.66, [{'t': title, 's': 25, 'b': True, 'c': NAVY}])
    bar(slide, 0.63, 1.28, 1.5, 0.045, BLUE)
    text(slide, 9.55, 0.34, 3.15, 0.3,
         [{'t': '招投标智能问答机器人', 's': 10, 'c': MUTE, 'a': R}])
    bar(slide, 0.62, 7.00, 12.09, 0.012, LGRAY)
    text(slide, 0.62, 7.07, 9.9, 0.3, [{'t': '图示建议：' + hint, 's': 9, 'c': MUTE}])
    text(slide, 12.30, 7.04, 0.55, 0.32,
         [{'t': '%02d' % page, 's': 11, 'b': True, 'c': BLUE, 'a': R}])
    return slide


def chip(slide, x, y, w, h, txt, fill=NAVY, color=WHITE, size=12.5):
    return box(slide, x, y, w, h, [{'t': txt, 's': size, 'b': True, 'c': color}],
               fill=fill, radius=0.5)


def bullets(slide, x, y, w, h, items, size=11.5, sa=9, lead_color=NAVY):
    """items: [(加粗引导, 说明)]"""
    paras = []
    for lead, desc in items:
        paras.append({'runs': [(lead, size, True, lead_color),
                               (desc, size, False, DARK)], 'sa': sa})
    return text(slide, x, y, w, h, paras)


def set_cell(cell, txt, size=10.5, bold=False, color=DARK, fill=None,
             align=C):
    if fill is not None:
        cell.fill.solid()
        cell.fill.fore_color.rgb = fill
    cell.margin_left = Inches(0.06)
    cell.margin_right = Inches(0.04)
    cell.margin_top = Inches(0.02)
    cell.margin_bottom = Inches(0.02)
    cell.vertical_anchor = MID
    tf = cell.text_frame
    tf.word_wrap = True
    _paras(tf, [{'t': txt, 's': size, 'b': bold, 'c': color, 'a': align}], align)
