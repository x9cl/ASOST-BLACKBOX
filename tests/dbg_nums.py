import sys
sys.path.insert(0, '/opt/data/projects/assost/assost-main')
from image_aware_extract import extract_page_flow
import re

f = extract_page_flow('/opt/data/projects/assost/book.pdf', 22, '/opt/data/projects/assost/tests/goal2_images')
flow = f['flow']
img_idx = next(i for i, x in enumerate(flow) if x['type'] == 'image')
before = ' '.join(x['text'] for x in flow[:img_idx] if x['type'] == 'text')[-300:]
print('nums:', re.findall(r'\d+', before))
print(repr(before[-150:]))
