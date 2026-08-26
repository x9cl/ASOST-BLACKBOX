"""live_showcase.py — إعادة ترجمة صفحة 7 مع حفظ النص الكامل + المقارنة الجانبية"""
import sys, os, json, time

BASE = '/opt/data/projects/assost'
os.environ.setdefault('HERMES_HOME', f'{BASE}/hermes-home')
sys.path.insert(0, f'{BASE}/asost')
sys.path.insert(0, f'{BASE}/hermes')
sys.path.insert(0, f'{BASE}/assost-main')

import logging
logging.disable(logging.WARNING)

from orchestrator import ASOSTOrchestrator

SRC = """PROLOGUE DEATH MARCH TO DISASTER

Stars streak across the sky.

Dozens and dozens of them.

Have you ever seen a shooting star?

I'm sure many people have. Maybe you've been captivated by their fleeting beauty or made a wish on one as it fell through the night sky.

But have you ever watched a meteorite rip through the heavens toward the surface? Have you seen it tear the sky to pieces with a thunderous roar, crashing into the ground with a terrifying impact?

Maybe some of you have seen something like it on TV or on the Internet somewhere. But even then, I'm sure nobody ever thought they wanted to see a meteor shower up close, hurtling down all around them.

And yet, at this very moment, I'm watching more than a hundred falling rocks pour down right before my eyes, one after the other.

No—I shouldn't say it so passively, as if it's someone else's problem. Because I'm the one responsible for this disaster in the first place.

Because of a choice I thoughtlessly made just ten minutes ago,"""

gemini = json.load(open(f'{BASE}/tests/fullbook/paged_translations.json'))['7']

print('ASOST pipeline live re-run (page 7) — saving FULL text this time...')
t0 = time.time()
orch = ASOSTOrchestrator()
decision = orch.translate_page(7, SRC)
dt = round(time.time() - t0, 1)

out = {
    'page': 7,
    'secs': dt,
    'decision': decision.get('decision'),
    'light_score': decision.get('light_score'),
    'deep_score': decision.get('deep_score'),
    'revision_rounds': decision.get('revision_rounds', 0),
    'asost_translation': decision.get('translation', ''),
    'gemini_translation': gemini,
}
json.dump(out, open(f'{BASE}/asost/showcase_page7.json', 'w'), ensure_ascii=False, indent=1)
print(f'done in {dt}s | saved → asost/showcase_page7.json')
