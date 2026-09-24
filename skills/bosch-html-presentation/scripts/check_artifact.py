#!/usr/bin/env python3
"""Static offline/asset checks. Browser review remains required for visibility and behavior."""
import base64
from html.parser import HTMLParser
from pathlib import Path
import re
import sys

ASSET = Path(__file__).resolve().parents[1] / 'assets' / 'bosch-logo.svg'
VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}

class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes=[]
        self.stack=[]
        self.embedded=[]
        self.styles=[]
    def handle_starttag(self, tag, attrs):
        node={'tag':tag,'attrs':dict(attrs),'parents':list(self.stack)}
        self.nodes.append(node)
        if tag not in VOID:self.stack.append(node)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i]['tag']==tag:
                del self.stack[i:]
                break
    def handle_data(self,data):
        if self.stack and self.stack[-1]['tag']=='style':
            self.embedded.append(data);self.styles.append(data)
        elif self.stack and self.stack[-1]['tag']=='script':self.embedded.append(data)

def check(path):
    errors=[]
    text=path.read_text(encoding='utf-8')
    doc=Document();doc.feed(text)
    expected=ASSET.read_bytes()
    logos=[]
    for node in doc.nodes:
        tag,a=node['tag'],node['attrs']
        if a.get('data-brand-asset') is not None:
            if tag!='img' or a.get('data-brand-asset')!='assets/bosch-logo.svg':
                errors.append('logo must be an img marked with the canonical asset path');continue
            try:
                prefix,data=a.get('src','').split(',',1)
                if prefix!='data:image/svg+xml;base64' or base64.b64decode(data,validate=True)!=expected:
                    raise ValueError()
                logos.append(node)
            except (ValueError,TypeError):errors.append('embedded logo bytes differ from assets/bosch-logo.svg')
            if not a.get('alt','').strip():errors.append('logo requires accessible alt text')
        for attr in ('src','poster','srcset','data'):
            if attr=='data' and tag!='object':continue
            value=a.get(attr,'')
            if value and not value.startswith(('data:','#')):errors.append(f'non-embedded resource: {tag}[{attr}]')
        if tag=='link' and a.get('href') and not a['href'].startswith('data:'):
            errors.append('external/local link resource is not embedded')
        if tag in {'use','image'}:
            for attr in ('href','xlink:href'):
                if a.get(attr) and not a[attr].startswith(('#','data:')):errors.append('non-embedded SVG resource')
        if tag in {'iframe','object','embed','base'}:errors.append(f'unsupported embedded document/base: {tag}')
    code='\n'.join(doc.embedded)+'\n'+'\n'.join(n['attrs'].get('style','') for n in doc.nodes)
    css='\n'.join(doc.styles)+'\n'+'\n'.join(n['attrs'].get('style','') for n in doc.nodes)
    for value in re.findall(r'url\(\s*[\'"]?([^\)\'\"]+)',css,re.I):
        if not value.strip().startswith(('data:','#')):errors.append('non-embedded CSS resource')
    if re.search(r'@import\b|\bfetch\s*\(|XMLHttpRequest|WebSocket|EventSource|sendBeacon\s*\(|\bimport\s*\(',code):
        errors.append('runtime import/network API requires removal or manual redesign')
    if not logos:errors.append('missing canonical Bosch logo')
    for tag in ('html','title'):
        if not any(n['tag']==tag for n in doc.nodes):errors.append(f'missing {tag}')
    if not any(n['tag']=='meta' and n['attrs'].get('name')=='viewport' for n in doc.nodes):errors.append('missing viewport')
    for marker in ('@media print','prefers-reduced-motion'):
        if marker=='@media print': found=bool(re.search(r'@media\s+print',text))
        else:found=marker in text
        if not found:errors.append(f'missing {marker}')
    def cls(n,c):return c in n['attrs'].get('class','').split()
    def contains(parent,child):return any(p is parent for p in child['parents'])
    mode=next((n['attrs'].get('data-artifact-mode') for n in doc.nodes if n['tag']=='html'),None)
    if mode=='slide-deck':
        slides=[n for n in doc.nodes if cls(n,'slide')]
        if not slides:errors.append('no slides')
        for i,slide in enumerate(slides,1):
            if not any(contains(slide,logo) for logo in logos):errors.append(f'slide {i} lacks canonical logo')
        if not all(k in code for k in ('ArrowRight','ArrowLeft','Home','End')):errors.append('missing deck keyboard bindings')
    elif mode=='scroll-sidebar':
        for name in ('sidebar','print-brand'):
            if not any(cls(n,name) and any(contains(n,l) for l in logos) for n in doc.nodes):errors.append(f'{name} lacks canonical logo')
        sections=[n for n in doc.nodes if cls(n,'chapter')]
        ids=[n['attrs'].get('id') for n in sections]
        links=[n['attrs'].get('href') for n in doc.nodes if n['tag']=='a' and any(cls(p,'toc') for p in n['parents'])]
        if not ids or None in ids or len(ids)!=len(set(ids)):errors.append('chapter IDs missing or duplicated')
        elif links!=['#'+id for id in ids]:errors.append('TOC links must match chapter IDs in order')
        if 'aria-current' not in code or 'scroll' not in code:errors.append('missing scrollspy behavior')
        if not any(n['attrs'].get('id')=='edit-toggle' for n in doc.nodes):errors.append('missing direct-edit mode control')
        if not any(n['attrs'].get('id')=='save-copy' for n in doc.nodes):errors.append('missing edited-copy download control')
        if not any('data-editable' in n['attrs'] for n in doc.nodes):errors.append('no text is marked as editable')
        if 'contenteditable' not in code or 'URL.createObjectURL' not in code or 'plaintext-only' not in code:errors.append('missing inline editing or edited-copy export behavior')
        for logo in logos:
            if 'contenteditable' in logo['attrs']:errors.append('Bosch logo must remain outside editable content')
    else:errors.append('missing/unknown data-artifact-mode')
    return list(dict.fromkeys(errors))

def main():
    if len(sys.argv)!=2:
        print('usage: check_artifact.py <artifact.html>');return 2
    try:errors=check(Path(sys.argv[1]))
    except (OSError,UnicodeError) as exc:print(f'FAIL: {exc}');return 2
    print('FAIL' if errors else 'PASS (static checks; verify appearance and behavior in a browser)')
    for error in errors:print('  ERROR:',error)
    return bool(errors)
if __name__=='__main__':sys.exit(main())
