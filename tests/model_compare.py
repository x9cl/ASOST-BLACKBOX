"""model_compare.py — الدورة المقارنة: ox-alpha + الموديلات المجانية vs Gemini الأصلي
نفس صفحات ASOST القياسية (7-8) لكل موديل، حفظ النتائج للمقارنة العمياء.
"""
import os, sys, json, time
import urllib.request

OR_KEY = os.environ.get('OR_KEY', 'sk-or-v9')
BASE = '/opt/data/projects/assost'
sys.path.insert(0, f'{BASE}/assost-main')

SYS = """You are a professional literary Arabic translator for novels.
Rules:
- Output ONLY the Arabic translation, no notes, no reasoning, no English.
- Preserve the narrative voice, dialogue style, and all details exactly.
- Keep character names transliterated naturally in Arabic.
- Use literary but readable Modern Standard Arabic (فصحى مبسطة).
"""

SRC = """PROLOGUE DEATH MARCH TO DISASTER

Stars streak across the sky.

Dozens and dozens of them.

Have you ever seen a shooting star?

I'm sure many people have. Maybe you've been captivated by their fleeting beauty or made a wish on one as it fell through the night sky.

But have you ever watched a meteorite rip through the heavens toward the surface? Have you seen it tear the sky to pieces with a thunderous roar, crashing into the ground with a terrifying impact?

Maybe some of you have seen something like it on TV or on the Internet somewhere. But even then, I'm sure nobody ever thought they wanted to see a meteor shower up close, hurtling down all around them.

And yet, at this very moment, I'm watching more than a hundred falling rocks pour down right before my eyes, one after the other.

No—I shouldn't say it so passively, as if it's someone else's problem. Because I'm the one responsible for this disaster in the first place.

Because of a choice I thoughtlessly made just ten minutes ago,
"""

MODELS = [
    'stealth/ox-alpha',
    'nvidia/nemotron-3-ultra-550b-a55b:free',
    'nvidia/nemotron-3.5-lightning:free',
    'z-ai/glm-5.2:free',
    'minimax/minimax-m3:free',
    'thinkingmachines/inkling:free',
    'google/gemma-4-31b-it:free',
]


def call_openrouter(model, timeout=180):
    body = json.dumps({
        'model': model,
        'messages': [{'role': 'system', 'content': SYS},
                     {'role': 'user', 'content': SRC}],
        'max_tokens': 2500,
        'temperature': 0.3,
    }).encode()
    req = urllib.request.Request(
        'https://openrouter.ai/api/v1/chat/completions', data=body,
        headers={'Authorization': f'Bearer {OR_KEY}',
                 'Content-Type': 'application/json'})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
        dt = round(time.time() - t0, 1)
        msg = d['choices'][0]['message']
        content = (msg.get('content') or '').strip()
        if not content and msg.get('reasoning'):
            content = '[REASONING ONLY — content null]'
        usage = d.get('usage', {})
        return {'ok': True, 'text': content, 'secs': dt,
                'tokens': usage.get('total_tokens'),
                'reasoning_tokens': usage.get('completion_tokens_details', {}).get('reasoning_tokens')}
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200], 'secs': round(time.time() - t0, 1)}


if __name__ == '__main__':
    out = {}
    for m in MODELS:
        print(f'--- {m} ...')
        r = call_openrouter(m)
        out[m] = r
        if r['ok']:
            print(f"    OK {r['secs']}s | tokens {r['tokens']} (reasoning {r['reasoning_tokens']}) | {len(r['text'])} chars")
        else:
            print(f"    FAIL {r['secs']}s: {r['error']}")
        time.sleep(3)
    json.dump(out, open(f'{BASE}/tests/model_compare_results.json', 'w'), ensure_ascii=False, indent=1)
    print('\nsaved -> tests/model_compare_results.json')
