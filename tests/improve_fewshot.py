"""تحسين فعلي #1: رفع جودة system instruction عبر few-shot من أفضل الترجمات المعتمدة.
يضيف أمثلة حقيقية (إنجليزي→عربي معتمد) إلى المعجم ليقلدها النموذج."""
import sys
sys.path.insert(0, '/opt/data/projects/assost/assost-main')
from context_bridge import ContextBridge

cb = ContextBridge()
# few-shot examples مستخرجة من ترجماتنا المعتمدة عالية الجودة
cb.bible['few_shot_examples'] = [
    {
        'en': '"Is this supposed to be a game?" I grunted, trying to trick my limbs into moving.',
        'ar': '«أم المفترض أن تكون هذه لعبة؟» أنينتُ بمرارة، محاولاً خداع أطرافي الواهنة لتتحرك.'
    },
    {
        'en': 'I grasped the sword tight with both shaking hands and desperately tried to set my stance.',
        'ar': 'قبضت على السيف بقوة بكلتا يدي المرتجفتين، وثبّتُّ قدمي على الأرض في محاولة يائسة.'
    },
]
cb.save()
print('few_shot examples registered:', len(cb.bible['few_shot_examples']))
