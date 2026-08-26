"""first_agent_test.py — أول اختبار حي: وكيل ASOST دائم فوق جسم Hermes
يترجم مقطعاً من كتاب Anas عبر AIAgent كاملة + OpenRouter
"""
import sys, os, asyncio

HERMES = '/opt/data/projects/assost/hermes'
sys.path.insert(0, HERMES)
import logging
logging.disable(logging.WARNING)

from run_agent import AIAgent  # noqa

if not os.environ.get('OPENROUTER_API_KEY'):
    for line in open('/opt/data/projects/assost/assost-main/.env'):
        if line.startswith('OPENROUTER_API_KEY='):
            os.environ['OPENROUTER_API_KEY'] = line.split('=', 1)[1].strip()
            break


async def main():
    agent = AIAgent(
        base_url='https://openrouter.ai/api/v1',
        api_key=os.environ['OPENROUTER_API_KEY'],
        model='stealth/ox-alpha',
        provider='openrouter',
        api_mode='chat_completions',
        quiet_mode=True,
        ephemeral_system_prompt=(
            'You are ASOST Translator (المترجم), the permanent literary translator '
            'agent of the ASOST system. Translate English novel text to literary '
            'but readable Arabic. Output ONLY the Arabic translation.'
        ),
        enabled_toolsets=[],
        skip_context_files=True,
        skip_memory=True,
        platform='asost-translator',
    )
    text = ("Have you ever watched a meteorite rip through the heavens toward "
            "the surface? Have you seen it tear the sky to pieces with a "
            "thunderous roar, crashing into the ground with a terrifying impact?")
    print('ASOST Translator translating...')
    result = agent.chat(f'Translate to literary Arabic:\n\n{text}')
    out = result if isinstance(result, str) else str(result)
    print('--- RESULT ---')
    print(out[:600])


asyncio.run(main())
