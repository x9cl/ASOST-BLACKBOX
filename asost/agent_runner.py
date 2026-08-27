"""agent_runner.py — بناء وكلاء ASOST الدائمين فوق نواة Hermes (AIAgent).

build_agent(agent_name, book_id, run_id, agent_instance_id) يقرأ identity.yaml
من مجلد الوكيل ويبني AIAgent بهوية تشغيل معزولة
والـ toolsets المحددة، مع HERMES_HOME مضبوط على /opt/data/projects/assost/hermes-home.
لا تعديل على hermes/ إطلاقاً.
"""
import os
import sys

ASOST_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(ASOST_ROOT)
HERMES = os.path.join(PROJECT, "hermes")
HERMES_HOME = os.path.join(PROJECT, "hermes-home")
AGENTS_DIR = os.path.join(ASOST_ROOT, "agents")

if HERMES not in sys.path:
    sys.path.insert(0, HERMES)

# Toolsets حسب دور الوكيل (افتراضي؛ يمكن تجاوزه من identity.yaml)
ROLE_TOOLSETS = {
    "translator": ["asost_translate", "asost_memory"],
    "critic_light": ["asost_critique"],
    "critic_deep": ["asost_critique", "asost_memory"],
    "context_keeper": ["asost_memory"],
    "book_adapter": ["asost_memory"],
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


def build_agent(agent_name, book_id, run_id, agent_instance_id,
                model="stealth/ox-alpha"):
    """بناء AIAgent لهوية وكيل ASOST من مجلده.

    - يضبط HERMES_HOME
    - يقرأ identity.yaml → ephemeral_system_prompt
    - enabled_toolsets حسب الدور (أو كما في identity.yaml)
    """
    ensure_hermes_home()
    raw_identity = {
        "book_id": book_id,
        "run_id": run_id,
        "agent_instance_id": agent_instance_id,
    }
    for field, value in raw_identity.items():
        if value is None or not str(value).strip():
            raise ValueError(f"{field} must not be empty")
    execution_identity = {key: str(value) for key, value in raw_identity.items()}
    ident = _load_identity(agent_name)
    role = ident.get("role", agent_name)
    toolsets = ident.get("toolsets")
    if not isinstance(toolsets, list) or not toolsets:
        toolsets = ROLE_TOOLSETS.get(role, [])
    system_prompt = ident.get("system_prompt") or ident.get("description", "")
    session_id = f"asost:{execution_identity['book_id']}:{execution_identity['run_id']}:{role}"
    system_prompt += (
        "\n\nASOST execution identity (forward unchanged to tools and checkpoints): "
        f"book_id={execution_identity['book_id']}; "
        f"run_id={execution_identity['run_id']}; "
        f"agent_instance_id={execution_identity['agent_instance_id']}; "
        f"session_id={session_id}."
    )

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
        user_id=execution_identity["book_id"],
        chat_id=execution_identity["run_id"],
        thread_id=execution_identity["agent_instance_id"],
        session_id=session_id,
        # Hermes includes this ID in the prompt and propagates it to tool calls.
        pass_session_id=True,
    )
    agent.asost_identity = ident
    agent.asost_execution_identity = {
        **execution_identity,
        "role": role,
        "session_id": session_id,
        "memory_namespace": f"asost:{execution_identity['book_id']}:{execution_identity['run_id']}",
        "checkpoint_namespace": session_id,
    }
    return agent


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "translator"
    ident = _load_identity(name)
    print(f"identity OK: {name} → role={ident.get('role')} "
          f"toolsets={ident.get('toolsets') or ROLE_TOOLSETS.get(ident.get('role'))}")
