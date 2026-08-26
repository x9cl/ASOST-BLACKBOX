"""تحقق نهائي: هل الصورة عند حدود فقرة كاملة (لا تقسيم فكرة)?"""
import fitz

d = fitz.open('/opt/data/projects/assost/tests/fullbook/full_book.pdf')
# find ill24 page
for i, p in enumerate(d):
    if p.get_image_info() and i > 15:
        prev_t = d[i - 1].get_text().strip()
        next_t = d[i + 1].get_text().strip()
        print(f'IMAGE on p{i+1}')
        print('PREV ends:', repr(prev_t[-120:]))
        print('NEXT starts:', repr(next_t[:120]))
        # check: does prev end with sentence-final punctuation?
        print('prev ends cleanly:', prev_t[-1] in '.!؟"»…' or prev_t.splitlines()[-2][-1] in '.!؟' if len(prev_t.splitlines()) > 1 else False)
        break
