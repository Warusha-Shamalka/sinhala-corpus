"""Static HTML main-content extraction; never execute scripts or fetch assets."""
from html.parser import HTMLParser
import re

BLOCKS = {'p', 'div', 'section', 'article', 'main', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'ul', 'ol', 'blockquote', 'pre', 'table', 'tr'}
SKIP = {'script', 'style', 'nav', 'footer', 'header', 'form', 'button', 'noscript', 'aside', 'iframe', 'svg'}
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []
        self.parent = None


class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node(); self.stack = [self.root]; self.nodes = []

    def handle_starttag(self, tag, attrs):
        if len(self.nodes) >= 100000 or len(self.stack) >= 128:
            raise ValueError('HTML structure limit')
        node = Node(tag, attrs); node.parent = self.stack[-1]
        self.stack[-1].children.append(node); self.nodes.append(node)
        if tag not in VOID: self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID: self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]; break

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def extract(content, charset='utf-8', main_id=None, max_bytes=2097152):
    if len(content) > max_bytes:
        raise ValueError('HTML exceeds extraction byte limit')
    # Strict decoding avoids silently replacing Sinhala characters. UTF-8 BOM supported.
    encoding = charset or 'utf-8'
    if encoding.lower() in {'utf-8', 'utf8'}: encoding = 'utf-8-sig'
    parser = Parser(); parser.feed(content.decode(encoding, errors='strict')); parser.close()
    def visible(node):
        while node is not None:
            if node.tag in SKIP or 'hidden' in node.attrs or node.attrs.get('aria-hidden') == 'true': return False
            node = node.parent
        return True
    if main_id:
        selected = [n for n in parser.nodes if n.attrs.get('id') == main_id and visible(n)]
    else:
        selected = [n for n in parser.nodes if n.tag == 'main' and visible(n)]
        if not selected: selected = [n for n in parser.nodes if n.tag == 'article' and visible(n)]
    if len(selected) != 1:
        raise ValueError('Expected one main/article region; configure html_main_id for this source')
    assets = []
    def visit(node):
        if isinstance(node, str): return re.sub(r'\s+', ' ', node)
        if node.tag in SKIP or 'hidden' in node.attrs or node.attrs.get('aria-hidden') == 'true': return ''
        if node.tag == 'img':
            assets.append({'src': node.attrs.get('src', ''), 'alt': node.attrs.get('alt', '')}); return ''
        if node.tag == 'br': return '\n'
        if node.tag == 'math':
            assets.append({'kind': 'mathml', 'note': 'Compare source HTML equation rendering'})
        if node.tag in {'table', 'sup', 'sub'}:
            assets.append({'kind': node.tag, 'note': 'Compare source structure; flattened text needs review'})
        text = ''.join(visit(child) for child in node.children)
        if node.tag in {'td', 'th'}: return text.strip() + '\t'
        return '\n' + text + '\n' if node.tag in BLOCKS else text
    text = visit(selected[0])
    text = '\n'.join(line.strip() for line in text.splitlines() if line.strip())
    if not text: raise ValueError('Main content has no text; JavaScript-only pages are unsupported')
    return {'text': text, 'assets': assets, 'assets_status': 'references_only',
            'quality_flags': ['visual_assets_need_review'] if assets else [], 'selection': {'main_id': main_id, 'tag': selected[0].tag}}
