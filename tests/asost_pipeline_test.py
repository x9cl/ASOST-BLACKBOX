"""asost_pipeline_test.py — الاختبار الحي الإجباري لطبقة وكلاء ASOST.

دورة كاملة عبر ASOSTOrchestrator.translate_page:
ترجمة فعلية → درجة فعلية من الناقد السريع → قرار قبول/رفض مطبوع.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "asost"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/tests")

from agent_runner import ensure_hermes_home  # noqa: E402

ensure_hermes_home()

from model_compare import SRC  # noqa: E402
from orchestrator import ASOSTOrchestrator  # noqa: E402


async def main():
    print("=" * 70)
    print("ASOST PIPELINE LIVE TEST — page 7")
    print("=" * 70)
    orch = ASOSTOrchestrator()

    result = orch.translate_page(page_num=7, src_text=SRC)

    print("\n" + "=" * 70)
    print("STAGE 1 — TRANSLATION (first 800 chars):")
    print(result["translation"][:800])
    print("\nSTAGE 2 — CRITIC LIGHT:")
    print(f"  score={result.get('light_score')} json={result['light']}")
    if "deep" in result:
        print("STAGE 3 — CRITIC DEEP:")
        print(f"  {result['deep']}")
    print("\nDECISION:", result["decision"])
    print("=" * 70)

    # معايير القبول
    ok_trans = bool(result["translation"].strip()) and any(
        "\u0600" <= c <= "\u06ff" for c in result["translation"])
    ok_score = isinstance(result.get("light_score"), int) or \
        isinstance(result.get("deep_score"), int)
    ok_decision = result["decision"] in ("accepted", "rejected", "deep_reviewed")
    print(f"\nVERDICTS: translation_arabic={ok_trans} real_score={ok_score} "
          f"decision_printed={ok_decision}")
    assert ok_trans and ok_score and ok_decision, "PIPELINE TEST FAILED"
    print("ASOST PIPELINE TEST PASSED ✅")


asyncio.run(main())
