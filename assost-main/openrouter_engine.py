"""openrouter_engine.py — بديل مباشر لـ EnhancedGeminiAPI عبر OpenRouter
نفس الواجهة: make_precision_request / translate_text / cleanup
الموديل الافتراضي: stealth/ox-alpha — قابل للتغيير عبر ASOST_OR_MODEL
"""
import os, json, time, random, logging, asyncio
from typing import List, Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get('ASOST_OR_MODEL', 'stealth/ox-alpha')
BASE_URL = 'https://openrouter.ai/api/v1/chat/completions'

# أخطاء قاتلة: لا تُعاد أبداً (طلب/توكن مرفوض لن ينجح بإعادة المحاولة)
FATAL_STATUSES = {400, 401, 403}
RETRYABLE_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}
BASE_BACKOFF_S = [5, 15, 30, 60]  # backoff تصاعدي، مع jitter ±20% عند التطبيق


def _jittered_delay(base: float) -> float:
    """backoff تصاعدي + jitter عشوائي ±20%."""
    return base * random.uniform(0.8, 1.2)


class EnhancedOpenRouterAPI:
    """يقلّد واجهة EnhancedGeminiAPI لكن يضرب OpenRouter."""

    # نفس ثوابت الأصلي المستخدمة في المسار الحالي
    SAFE_CHUNK_WORDS = 1200

    def __init__(self, api_keys: Optional[List[str]] = None):
        raw = os.environ.get('OPENROUTER_API_KEY', '')
        if not raw:
            env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
            if os.path.exists(env_file):
                for line in open(env_file):
                    if line.startswith('OPENROUTER_API_KEY='):
                        raw = line.split('=', 1)[1].strip()
                        break
        self.api_keys = [k.strip() for k in (api_keys or ([raw] if raw else [])) if k.strip()]
        self._key_idx = 0
        self.model = DEFAULT_MODEL
        self.base_url = BASE_URL
        self.max_retries = 4
        self.retry_delays = [5, 15, 30, 60]
        self.session = None
        self.connector = None
        logger.info(f'OpenRouter API initialized with {len(self.api_keys)} key(s), model={self.model}')

    async def _ensure_session(self):
        import aiohttp
        if not self.session or self.session.closed:
            self.connector = aiohttp.TCPConnector(limit=10)
            timeout = aiohttp.ClientTimeout(total=600)
            self.session = aiohttp.ClientSession(connector=self.connector, timeout=timeout)

    def _next_key(self) -> str:
        k = self.api_keys[self._key_idx % len(self.api_keys)]
        self._key_idx += 1
        return k

    async def make_precision_request(self, prompt: str, system_instruction: str = '',
                                     temperature: float = 0.3, max_tokens: int = 16000,
                                     request_type: str = 'translation'
                                     ) -> Tuple[Optional[str], float, Optional[str]]:
        """نفس توقيع الأصلي: يعيد (text, response_time, key_used)."""
        await self._ensure_session()
        payload = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': system_instruction or
                 'You are a professional literary Arabic translator. Output ONLY the Arabic translation.'},
                {'role': 'user', 'content': prompt},
            ],
            'temperature': temperature,
            'max_tokens': max_tokens,
        }
        last_err = None
        for attempt in range(self.max_retries):
            key_idx = self._key_idx % len(self.api_keys) if self.api_keys else -1
            headers = {'Authorization': f'Bearer {self._next_key()}',
                       'Content-Type': 'application/json'}
            t0 = time.time()
            try:
                async with self.session.post(BASE_URL, json=payload, headers=headers) as resp:
                    d = await resp.json()
                    dt = time.time() - t0
                    if resp.status == 200 and 'choices' in d:
                        msg = d['choices'][0]['message']
                        text = (msg.get('content') or '').strip()
                        return (text or None), dt, 'openrouter'
                    last_err = f'{resp.status}: {json.dumps(d)[:200]}'
                    logger.warning(f'[OpenRouter] attempt {attempt+1} '
                                   f'(key index={key_idx}) failed: {last_err}')
                    if resp.status in FATAL_STATUSES:
                        # قاتل: فشل فوري بلا إعادة (سجل رقم المفتاح الفاشل فقط)
                        logger.error(f'[OpenRouter] fatal status {resp.status} '
                                     f'with key index={key_idx} — aborting retries')
                        raise RuntimeError(
                            f'OpenRouter fatal error ({resp.status}) with key '
                            f'index={key_idx}: {last_err}')
                    if resp.status not in RETRYABLE_STATUSES:
                        # حالة غير معروفة: عاملها كمؤقتة وأعد المحاولة
                        logger.warning(f'[OpenRouter] unexpected status '
                                       f'{resp.status}, treating as retryable')
            except RuntimeError:
                raise
            except Exception as e:
                dt = time.time() - t0
                last_err = str(e)[:200]
                logger.warning(f'[OpenRouter] attempt {attempt+1} '
                               f'(key index={key_idx}) exception: {last_err}')
            if attempt < self.max_retries - 1:
                base = BASE_BACKOFF_S[min(attempt, len(BASE_BACKOFF_S) - 1)]
                delay = _jittered_delay(base)
                logger.info(f'[OpenRouter] retrying in {delay:.1f}s '
                            f'(backoff base={base}s ±20% jitter)')
                await asyncio.sleep(delay)
        raise RuntimeError(f'OpenRouter failed after {self.max_retries} attempts: {last_err}')

    # توافق مع المسارات التي تستدعي هذه الأسماء
    async def translate_text(self, text: str, context: str = '') -> Optional[str]:
        out, _, _ = await self.make_precision_request(text, request_type='translation')
        return out

    async def cleanup(self):
        if self.session and not self.session.closed:
            await self.session.close()

    # ---- stubs للسمات التي يلمسها PF.py الخارجي دون تأثير ----
    class _StubStats:
        pass

    rate_limiters: Dict[Any, Any] = {}
    key_stats: Dict[Any, Any] = {}


class CompleteTranslationEngine:
    """نسخة موافقة لـ PF.CompleteTranslationEngine لكن بمحرك OpenRouter.
    تعيد (translation, response_time, key_used)."""

    SAFE_CHUNK_WORDS = 1200

    def __init__(self, api: Optional[EnhancedOpenRouterAPI] = None):
        self.api = api or EnhancedOpenRouterAPI()

    @staticmethod
    def detect_text_genre_and_tone(text: str) -> Dict[str, str]:
        return {'genre': 'novel', 'tone': 'literary'}

    async def translate_with_completion_guarantee(
            self, text: str, context: str = '') -> Tuple[Optional[str], float, Optional[str]]:
        prompt = text if not context else f'{context}\n\n---\n\n{text}'
        sys_inst = (
            'You are a professional literary Arabic novel translator.\n'
            '- Translate the FINAL user message from English to literary but readable Arabic.\n'
            '- If a context block is provided, use it ONLY for continuity; do NOT translate it.\n'
            '- Preserve every detail, dialogue style, paragraph breaks. Output ONLY the Arabic translation.'
        )
        return await self.api.make_precision_request(prompt, system_instruction=sys_inst)

    async def cleanup(self):
        await self.api.cleanup()
