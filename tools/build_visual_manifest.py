"""Build the frozen v1 manifest from data/fixtures/content_sets.csv.

The output order is protocol-defined; no filesystem traversal or result-driven
selection is used. Font paths are explicit inputs so an open-font replacement
can be regenerated without changing stimulus IDs.
"""
import argparse, csv, hashlib
from pathlib import Path

PROTOCOL_VERSION = 'visual_features_v1.2.0'

WP3={
 'Latn':('latin','font_noto_sans_latn','data/assets/fonts/NotoSans-Regular.ttf','sans'),
 'Hani':('han','font_noto_sans_sc','data/assets/fonts/NotoSansCJKsc-Regular.otf','sans'),
 'Kana':('kana','font_noto_sans_jp','data/assets/fonts/NotoSansCJKjp-Regular.otf','sans'),
 'Hang':('hangul','font_noto_sans_kr','data/assets/fonts/NotoSansKR-static.ttf','sans')}
WP4=[
 ('font_noto_serif_sc','data/assets/fonts/NotoSerifSC-Regular.ttf','serif'),
 ('font_bpmf_iansui','data/assets/fonts/BpmfIansui-Regular.ttf','handwritten'),
 ('font_lxgw_marker_gothic','data/assets/fonts/LXGWMarkerGothic-Regular.ttf','display'),
]
FIELDS=['stimulus_id','writing_system','script_code_iso15924','content_set_id','content','unit_count','language_bcp47','font_id','font_path','style_family','render_profile','research_lines','semantic_status']
def build(source, output):
 rows=list(csv.DictReader(open(source,encoding='utf-8',newline=''))); out=[]; seen=set()
 def add(c, fid, path, style, lines):
  key=(c['script_code_iso15924'],c['content_set_id'],fid)
  for profile in ('bbox_height_matched','ink_area_matched'):
   # Normalization targets are part of the immutable condition.  Include the
   # protocol version so a target revision creates new stimulus IDs rather
   # than silently reusing v1.1.0 identifiers.
   sid='stim_'+hashlib.sha256('|'.join(key+(profile,PROTOCOL_VERSION)).encode()).hexdigest()[:16]
   if sid in seen: continue
   seen.add(sid); out.append(dict(stimulus_id=sid,writing_system=c['writing_system'],script_code_iso15924=c['script_code_iso15924'],content_set_id=c['content_set_id'],content=c['content'],unit_count=c['unit_count'],language_bcp47=c['language_bcp47'],font_id=fid,font_path=path,style_family=style,render_profile=profile,research_lines=lines,semantic_status=c['semantic_status']))
 for script in ('Latn','Hani','Kana','Hang'):
  cs=[c for c in rows if c['script_code_iso15924']==script]; _,fid,path,style=WP3[script]; lines='WP3_cross_script_visual_form'+('|WP4_han_style_evolution' if script=='Hani' else '')
  for c in cs: add(c,fid,path,style,lines)
  if script=='Hani':
   for fid,path,style in WP4:
    for c in cs: add(c,fid,path,style,'WP4_han_style_evolution')
 with open(output,'w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(out)
 print('wrote',len(out),'unique stimuli')
if __name__=='__main__':
 p=argparse.ArgumentParser(); p.add_argument('--source',default='data/fixtures/content_sets.csv'); p.add_argument('--output',required=True); a=p.parse_args(); build(a.source,a.output)
