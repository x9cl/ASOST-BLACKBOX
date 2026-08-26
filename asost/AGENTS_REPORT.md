# تقرير طبقة الوكلاء الدائمين — ASOST Agents Layer

التاريخ: 2026-08-26

## ما بُني
طبقة وكلاء دائمين فوق نواة Hermes المنسوخة (AIAgent) بدون أي تعديل على `hermes/`.

### الهيكل
```
asost/
├── agents/
│   ├── translator/identity.yaml    (المترجم ASOST — toolsets: asost_translate + asost_memory)
│   ├── critic_light/identity.yaml  (الناقد السريع — asost_critique، JSON فقط)
│   ├── critic_deep/identity.yaml   (الناقد العميق — asost_critique + asost_memory)
│   ├── context_keeper/identity.yaml(حافظ السياق — asost_memory)
│   ├── book_adapter/identity.yaml  (موائم الكتاب — asost_memory)
│   └── */memory/                   (مجلدات ذاكرة فارغة جاهزة)
├── agent_runner.py   → build_agent(name): يقرأ identity.yaml (parser داخلي بلا اعتماديات)،
│                       يضبط HERMES_HOME=hermes-home، يبني AIAgent بالهوية والـtoolsets حسب الدور
└── orchestrator.py   → ASOSTOrchestrator: translate_page() + save_state/load_state عبر مخزن asost_memory.json
```

## الاختبار الحي (tests/asost_pipeline_test.py) — PASSED ✅
- نص page 7 (SRC من model_compare.py، 1004 حرف) ترجم فعلياً عبر وكيل المترجم (ox-alpha/OpenRouter).
- critic_light أعطى درجة فعلية: score 8.5 → طُبّعت إلى **85** (≥85) → قرار **ACCEPTED**.
- في الجولة الأولى (قبل تحسين الـparsing) صعدت الدورة تلقائياً إلى critic_deep وأعطى overall_score 8.2 → 82 مع ملاحظات نحوية مفصلة — إثبات أن مسار التصعيد يعمل.
- الحالة حُفظت في الذاكرة: مفتاح `page_7_result` في asost_memory.json.

## قرارات تقنية
1. **الدرجات**: أداة `asost_critique_translation` في hermes/ لا تزال placeholder (score=None)، لذا الدرجة تأتي من الناقد نفسه كوكيل LLM — وهذا لا يتطلب تعديل hermes/.
2. **تطبيع الدرجات**: النماذج ترجع أحياناً مقياس 0-10 أو JSON متشعب؛ `_extract_score()` يبحث عن score/overall_score (حتى داخل sub-dicts) ويضرب ≤10 في 10.
3. **Parser داخلي لـ identity.yaml** (بدون PyYAML) يدعم block scalars والقوائم السطرية.

## ملفات
جديد: asost/agents/*/identity.yaml (5) + memory/ (5)، asost/agent_runner.py، asost/orchestrator.py، tests/asost_pipeline_test.py.
معدّل: لا شيء في hermes/.

## مشاكل واجهتها وحُلّت
- مسار sys.path خاطئ في أول تشغيل للاختبار → أُصلح.
- critic_light أعاد JSON غير قياسي في جولة → أضيف مستخرج أقواس متوازنة + fallback regex على النص الخام.
