import sys
sys.path.insert(0, '/opt/data/projects/assost/assost-main')
import PF
info = PF.ProfessionalDocumentProcessor.extract_pdf_with_precision('/opt/data/projects/assost/book.pdf')
for i, c in enumerate(info['chapters']):
    print(i, 'pages:', c.get('start_page'), '-', c.get('end_page'), '| imgs:', len(c.get('images_map', {})))
