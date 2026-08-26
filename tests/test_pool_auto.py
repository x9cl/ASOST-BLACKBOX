# ASOST Hermes copy — test harness script
import sys, os
HERMES = '/opt/data/projects/assost/hermes'
sys.path.insert(0, HERMES)
os.environ['HERMES_HOME'] = '/opt/data/projects/assost/hermes-home'
# Make sure no env key leaks in — the pool must be the only source.
os.environ.pop('OPENROUTER_API_KEY', None)
import logging; logging.disable(logging.WARNING)

# Sanity: pool read resolves our entry with priority 0
from agent.credential_pool import load_pool
pool = load_pool('openrouter')
entries = sorted(pool.entries(), key=lambda e: e.priority)
assert entries and entries[0].priority == 0, 'no priority-0 entry!'
key = entries[0].access_token or ''
print('POOL OK: provider=openrouter entries=%d top_priority=%d key_prefix=%s...%s' % (
    len(entries), entries[0].priority, key[:10], key[-6:] if len(key) > 16 else '?'))
assert key.startswith('sk-or-v1-'), 'entry has no usable access_token'

from run_agent import AIAgent
agent = AIAgent(
    base_url='https://openrouter.ai/api/v1',
    model='stealth/ox-alpha',
    provider='openrouter',
    api_mode='chat_completions',
    enabled_toolsets=[],
    skip_context_files=True,
    skip_memory=True,
    quiet_mode=True,
)
resolved_key = getattr(agent, 'api_key', '') or ''
print('AGENT api_key resolved:', bool(resolved_key), '(prefix %s...)' % (resolved_key[:10] if isinstance(resolved_key, str) else '?'))
result = agent.chat("Reply with exactly one word: ready")
out = result if isinstance(result, str) else str(result)
print('--- CHAT RESULT ---')
print(out[:300])
print('TEST PASSED' if out.strip() else 'EMPTY RESPONSE')
