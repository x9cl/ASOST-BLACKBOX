import sys
sys.path.insert(0, '/opt/data/projects/assost/assost-main')
import PF

info = PF.ProfessionalDocumentProcessor.extract_pdf_with_precision('/opt/data/projects/assost/book.pdf')
ils = info.get('illustrations', [])
print('chapters:', len(info['chapters']))
print('illustrations found:', len(ils))
for il in ils[:8]:
    print('ILLUS', il['page'], il['class'], il['name'])
mapped = sum(1 for c in info['chapters'] if c.get('images_map'))
print('chapters with images_map:', mapped)
