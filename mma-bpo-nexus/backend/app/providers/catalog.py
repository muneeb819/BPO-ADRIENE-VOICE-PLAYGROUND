"""Curated Deepgram and persona options.

These are catalogue options, not a claim that a particular Deepgram account has
verified access to every entry. Actual synthesis/transcription verifies access.
"""

FLUX_VOICE_DATA = [
    ("hannah", "American", "feminine"), ("kit", "British", "masculine"),
    ("alexis", "American", "feminine"), ("cliff", "American", "masculine"),
    ("sienna", "American", "feminine"), ("cole", "American", "masculine"),
    ("brooke", "American", "feminine"), ("colin", "British", "masculine"),
    ("gemma", "British", "feminine"), ("haley", "American", "feminine"),
    ("heather", "American", "feminine"), ("miles", "American", "masculine"),
    ("sean", "British", "masculine"), ("bree", "American", "feminine"),
    ("brittany", "American", "feminine"), ("bruce", "American", "masculine"),
    ("conor", "British", "masculine"), ("donovan", "American", "masculine"),
    ("drew", "American", "masculine"), ("elise", "American", "feminine"),
    ("jack", "British", "masculine"), ("kai", "Singaporean", "masculine"),
    ("kelsey", "American", "feminine"), ("maeve", "Irish", "feminine"),
    ("marcelo", "Filipino", "masculine"), ("marcus", "American", "masculine"),
    ("meena", "Indian", "feminine"), ("meghan", "American", "feminine"),
    ("naveen", "Indian", "masculine"), ("paige", "American", "feminine"),
    ("priya", "Indian", "feminine"), ("rufus", "British", "masculine"),
    ("sharon", "Australian", "feminine"), ("tanner", "British", "masculine"),
    ("wade", "American", "masculine"), ("wes", "American", "masculine"),
]

AURA_VOICE_DATA = [
    ("asteria", "American", "feminine"),
    ("luna", "American", "feminine"),
    ("stella", "American", "feminine"),
    ("orion", "American", "masculine"),
    ("arcas", "American", "masculine"),
]

TTS_VOICES = [
    {
        "id": f"flux-{name}-en",
        "name": name.capitalize(),
        "family": "Flux",
        "accent": accent,
        "gender": gender,
        "endpoint": "/v2/speak",
    }
    for name, accent, gender in FLUX_VOICE_DATA
] + [
    {
        "id": f"aura-{name}-en",
        "name": name.capitalize(),
        "family": "Aura",
        "accent": accent,
        "gender": gender,
        "endpoint": "/v1/speak",
    }
    for name, accent, gender in AURA_VOICE_DATA
]

TTS_VOICE_IDS = frozenset(voice["id"] for voice in TTS_VOICES)

STT_MODELS = [
    {"id": "browser", "label": "Browser speech recognition", "provider": "browser", "transport": "browser"},
    {"id": "nova-2", "label": "Deepgram Nova-2 · buffered", "provider": "deepgram", "transport": "HTTP /v1/listen"},
    {"id": "nova-3", "label": "Deepgram Nova-3 · buffered", "provider": "deepgram", "transport": "HTTP /v1/listen"},
    {"id": "flux-general-en", "label": "Deepgram Flux · streaming turns", "provider": "deepgram-flux", "transport": "WebSocket /v2/listen"},
]

PERSONA_PRESETS = [
    {
        "id": "custom", "label": "Custom persona", "purpose": "Custom BPO intake",
        "tone": "professional", "greeting": "",
    },
    {
        "id": "intake", "label": "Inbound intake specialist", "purpose": "Inbound service qualification",
        "tone": "professional",
        "greeting": "Hello — welcome to MMA BPO NEXUS. I’ll guide you through a short, transparent intake. Are you the account holder?",
    },
    {
        "id": "support", "label": "Customer support specialist", "purpose": "Customer account and service support",
        "tone": "empathetic",
        "greeting": "Hi, thanks for contacting MMA BPO NEXUS support. I’ll first confirm the account holder so we can keep your information safe. Are you the account holder?",
    },
    {
        "id": "sales", "label": "Sales qualification specialist", "purpose": "Inbound lead qualification and specialist review",
        "tone": "friendly",
        "greeting": "Hi — great to meet you. I’ll ask a few quick questions to route your request correctly. Are you the account holder?",
    },
    {
        "id": "healthcare", "label": "Healthcare scheduling assistant", "purpose": "Healthcare scheduling and coverage review",
        "tone": "empathetic",
        "greeting": "Hello, this is the MMA BPO NEXUS scheduling assistant. I’ll keep this brief and will not give medical advice or final coverage approval. Are you the account holder?",
    },
    {
        "id": "financial", "label": "Financial services intake", "purpose": "Financial account verification and advisor review",
        "tone": "authoritative",
        "greeting": "Hello. Before discussing any account or coverage details, I need to verify that you are the account holder. Is that you?",
    },
]

PERSONA_BY_ID = {preset["id"]: preset for preset in PERSONA_PRESETS}
TONES = ["professional", "friendly", "empathetic", "authoritative", "cheerful"]
