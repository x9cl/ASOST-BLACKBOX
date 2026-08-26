"""agent_runner.py — بناء وكلاء ASOST الدائمين فوق نواة Hermes (AIAgent).

build_agent(agent_name) يقرأ identity.yaml من مجلد الوكيل ويبني AIAgent بالهوية
والـ toolsets المحددة، مع HERMES_HOME مضبوط على /opt/data/projects/assost/hermes-home.
لا تعديل على hermes/ إطلاقاً.
"""
import os
import sys

from asost.config import settings

ASOST_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT = str(settings.project_root)
HERMES = os.path.join(PROJECT, "hermes")
HERMES_HOME = str(settings.hermes_home)
AGENTS_DIR = os.path.join(ASOST_ROOT, "agents")

if HERMES not in sys.path:
    sys.path.insert(0, HERMES)

# Toolsets حسب دور الوكيل (افتراضي؛ يمكن تجاوزه من identity.yaml)
ROLE_TOOLSETS = {
    "translator": ["asost_translate", "asost_gemini", "asost_memory"],
    "critic_light": [],
    "critic_deep": ["asost_gemini", "asost_memory"],
    "context_keeper": ["asost_gemini", "asost_memory"],
    "book_adapter": ["asost_gemini", "asost_memory"],
    "reviser": ["asost_translate", "asost_gemini", "asost_memory"],
}


def _load_identity(agent_name):
    """قراءة identity.yaml بدون اعتماديات خارجية (مفتاح: قيمة سطرية أو block scalar)."""
    import re
    path = os.path.join(AGENTS_DIR, agent_name, "identity.yaml")
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    ident = {}
    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        if not val and i + 1 < len(lines) and lines[i + 1].startswith(("  |", "  >")) or \
           (not val and i + 1 < len(lines) and re.match(r"^\s{2,}\S", lines[i + 1])):
            # block scalar — التقط الأسطر البادّة
            body = []
            i += 1
            while i < len(lines) and (not lines[i].strip() or lines[i].startswith(" ")):
                body.append(lines[i][2:] if lines[i].startswith("  ") else lines[i])
                i += 1
            ident[key] = "\n".join(body).strip()
            continue
        # قائمة سطرية [a, b]
        if val.startswith("[") and val.endswith("]"):
            items = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
            ident[key] = items
        else:
            ident[key] = val.strip("'\"")
        i += 1
    return ident


def ensure_hermes_home():
    """ضبط HERMES_HOME قبل أي استيراد لحالة Hermes."""
    os.environ["HERMES_HOME"] = HERMES_HOME
    os.makedirs(HERMES_HOME, exist_ok=True)
    return HERMES_HOME


def get_api_key():
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        envf = os.path.join(PROJECT, "assost-main", ".env")
        try:
            for line in open(envf):
                if line.startswith("OPENROUTER_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break
        except FileNotFoundError:
            pass
    return key


def build_agent(agent_name, model="stealth/ox-alpha"):
    """بناء AIAgent لهوية وكيل ASOST من مجلده.

    - يضبط HERMES_HOME
    - يقرأ identity.yaml → ephemeral_system_prompt
    - enabled_toolsets حسب الدور (أو كما في identity.yaml)
    """
    ensure_hermes_home()
    ident = _load_identity(agent_name)
    role = ident.get("role", agent_name)
    toolsets = ident.get("toolsets")
    if not isinstance(toolsets, list) or not toolsets:
        toolsets = ROLE_TOOLSETS.get(role, [])
    system_prompt = ident.get("system_prompt") or ident.get("description", "")

    from run_agent import AIAgent  # noqa: E402

    agent = AIAgent(
        base_url="https://openrouter.ai/api/v1",
        api_key=get_api_key(),
        model=model,
        provider="openrouter",
        api_mode="chat_completions",
        quiet_mode=True,
        ephemeral_system_prompt=system_prompt,
        enabled_toolsets=list(toolsets),
        skip_context_files=True,
        skip_memory=True,
        platform=ident.get("platform", f"asost-{role}"),
        session_id=f"asost-{agent_name}",
    )
    agent.asost_identity = ident
    return agent


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "translator"
    ident = _load_identity(name)
    print(f"identity OK: {name} → role={ident.get('role')} "
          f"toolsets={ident.get('toolsets') or ROLE_TOOLSETS.get(ident.get('role'))}")
