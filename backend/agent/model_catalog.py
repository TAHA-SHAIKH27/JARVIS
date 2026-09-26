"""
Phase 1 — Supplied model catalog.

Every candidate name from the Phase 1 brief is listed exactly once, with a
capability hint and match tokens. Match tokens are ONLY used to match a name
against the live NVIDIA `/v1/models` listing at runtime — they are never
treated as endpoint identifiers themselves. An identifier is accepted only if
it comes from the live listing (or from in-repo runtime evidence, recorded
in KNOWN_ENDPOINT_IDS). Nothing here enables a model; the registry +
validation layer decides that from live evidence.
"""
from typing import Dict, List, Optional

# -- Endpoint ids with in-repo runtime evidence (AGENT_RECALL 2026-09-14,
# -- config.json). These are the ONLY statically trusted identifiers.
KNOWN_ENDPOINT_IDS: Dict[str, str] = {
    "GLM-5.3-Flash": "z-ai/glm-5.3-flash",
}

# -- category -> default capabilities ------------------------------------
_CATEGORY_CAPS = {
    "chat": ["chat"],
    "reasoning": ["chat", "reasoning"],
    "coding": ["chat", "coding"],
    "vision": ["chat", "vision"],
    "embed": ["embed"],
    "rerank": ["rerank"],
    "ocr": ["ocr", "vision"],
    "voice": ["voice"],
    "tts": ["tts"],
    "translation": ["translation"],
    "safety": ["safety"],
    "image": ["image_gen"],
    "video": ["video"],
    "perception": ["vision"],
    "biology": ["chat"],
}


def _entry(name: str, category: str, tokens: List[str]) -> Dict:
    return {
        "candidate": name,
        "category": category,
        "capabilities": list(_CATEGORY_CAPS.get(category, ["chat"])),
        "match_tokens": [t.lower() for t in tokens],
    }


# One entry per UNIQUE supplied candidate (prompt listed
# "Qwen2.5 Coder 32b Instruct" twice — deduplicated here).
SUPPLIED_CANDIDATES: List[Dict] = [
    _entry("GLM-5.3-Flash", "chat", ["glm-5.3-flash", "glm", "5.3", "flash"]),
    _entry("GLM-5.3", "chat", ["glm-5", "glm"]),
    _entry("DeepSeek V4 Pro 0813", "reasoning", ["deepseek", "v4", "pro", "0813"]),
    _entry("Nemotron 3.5 Lightning 30B A3B", "chat", ["nemotron", "3.5", "lightning", "30b", "a3b"]),
    _entry("Muse Glimmer 30B", "chat", ["glimmer", "30b"]),
    _entry("DeepSeek V4 Flash 0731", "chat", ["deepseek", "v4", "flash", "0731"]),
    _entry("Kimi K3", "chat", ["kimi", "k3"]),
    _entry("Inkling", "chat", ["inkling"]),
    _entry("Laguna XS 2.1", "chat", ["laguna", "xs", "2.1"]),
    _entry("GLM-5.2", "chat", ["glm-5.2", "glm", "5.2"]),
    _entry("Nemotron 3 Ultra 550B A55B", "reasoning", ["nemotron", "3", "ultra", "550b", "a55b"]),
    _entry("MiniMax-M3", "chat", ["minimax", "m3"]),
    _entry("Step 3.7 Flash", "chat", ["step", "3.7", "flash"]),
    _entry("Mistral Medium 3.5", "chat", ["mistral", "medium", "3.5"]),
    _entry("Nemotron 3 Nano Omni", "reasoning", ["nemotron", "3", "nano", "omni"]),
    _entry("DeepSeek V4 Flash", "chat", ["deepseek", "v4", "flash"]),
    _entry("DeepSeek V4 Pro", "reasoning", ["deepseek", "v4", "pro"]),
    _entry("Gemma-4-31B-IT", "chat", ["gemma", "31b"]),
    _entry("MiniMax-M2.7", "chat", ["minimax", "m2.7", "m2"]),
    _entry("mistral-small-4-119b-2603", "chat", ["mistral-small", "119b", "2603"]),
    _entry("Qwen3.5 122B-A10B", "chat", ["qwen3.5", "qwen", "122b", "a10b"]),
    _entry("Qwen3.5-397B-A17B", "reasoning", ["qwen3.5", "qwen", "397b", "a17b"]),
    _entry("Step 3.5 Flash", "chat", ["step", "3.5", "flash"]),
    _entry("Ministral 3 14B Instruct 2512", "chat", ["ministral", "14b", "2512"]),
    _entry("Mistral Large 3 675B Instruct 2512", "reasoning", ["mistral-large", "675b", "2512"]),
    _entry("Cosmos Reason2 8B", "reasoning", ["cosmos", "reason", "8b"]),
    _entry("Magistral Small 2506", "reasoning", ["magistral", "small", "2506"]),
    _entry("Mistral Medium 3", "chat", ["mistral", "medium", "3"]),
    _entry("ByteDance-Seed/Seed-OSS-36B-Instruct", "chat", ["seed-oss", "seed", "36b"]),
    _entry("GPT OSS 20B", "chat", ["gpt-oss", "20b"]),
    _entry("GPT-OSS-120B", "reasoning", ["gpt-oss", "120b"]),
    _entry("Phi 4 Multimodal", "vision", ["phi-4", "phi", "multimodal"]),
    _entry("Qwen3 Coder 480B A35B Instruct", "coding", ["qwen3", "coder", "480b", "a35b"]),
    _entry("Qwen2.5 Coder 32b Instruct", "coding", ["qwen2.5", "qwen", "coder", "32b"]),
    _entry("Llama 3.3 Nemotron Super 49B v1.5", "chat", ["llama-3.3", "nemotron", "super", "49b", "v1.5"]),
    _entry("Llama 3.1 Nemotron 70B Instruct", "chat", ["llama-3.1", "nemotron", "70b"]),
    _entry("Llama 3.1 Nemotron Ultra 253B", "reasoning", ["llama-3.1", "nemotron", "ultra", "253b"]),
    _entry("Llama 3.3 Nemotron Super 49B v1", "chat", ["llama-3.3", "nemotron", "super", "49b"]),
    _entry("Llama 4 Maverick 17b 128e Instruct", "vision", ["llama-4", "maverick", "17b", "128e"]),
    _entry("Mistral-7B-Instruct-v0.3", "chat", ["mistral-7b", "mistral", "7b", "v0.3"]),
    _entry("Llama 3.1 Nemotron Nano 8B v1", "chat", ["llama-3.1", "nemotron", "nano", "8b"]),
    _entry("Qwen3-Next-80B-A3B-Instruct", "chat", ["qwen3-next", "qwen", "80b", "a3b"]),
    _entry("nemotron-3-nano-30b-a3b", "chat", ["nemotron-3", "nemotron", "nano", "30b", "a3b"]),
    _entry("Llama 3.3 70b Instruct", "chat", ["llama-3.3", "llama", "70b"]),
    _entry("Gemma 3 12B IT", "chat", ["gemma-3", "gemma", "12b"]),
    _entry("Gemma 3 4B IT", "chat", ["gemma-3", "gemma", "4b"]),
    _entry("Llama 3.1 8B Instruct", "chat", ["llama-3.1", "llama", "8b"]),
    _entry("Phi-4-Mini", "chat", ["phi-4-mini", "phi", "mini"]),
    _entry("Llama 3.2 1b Instruct", "chat", ["llama-3.2", "llama", "1b"]),
    _entry("Llama 3.2 3B Instruct", "chat", ["llama-3.2", "llama", "3b"]),
    _entry("Gemma 3n E2b It", "chat", ["gemma-3n", "gemma", "e2b"]),
    _entry("Gemma 3n E4b It", "chat", ["gemma-3n", "gemma", "e4b"]),
    _entry("Llama-3.2-90B-Vision-Instruct", "vision", ["llama-3.2", "llama", "90b", "vision"]),
    _entry("Llama 3.2 11b Vision Instruct", "vision", ["llama-3.2", "llama", "11b", "vision"]),
    _entry("Nemotron Nano 12B v2 VL", "vision", ["nemotron", "nano", "12b", "vl"]),
    _entry("Llama 3.1 Nemotron Nano VL 8B v1", "vision", ["llama-3.1", "nemotron", "nano", "vl", "8b"]),
    _entry("paligemma", "vision", ["paligemma", "pali"]),
    _entry("usdcode", "coding", ["usdcode", "usd", "code"]),
    _entry("nv-embedcode-7b-v1", "embed", ["embedcode", "embed", "code", "7b"]),
    _entry("llama-nemotron-embed-vl-1b-v2", "embed", ["embed", "vl", "1b"]),
    _entry("llama-3_2-nemoretriever-300m-embed-v1", "embed", ["nemoretriever", "retriever", "embed", "300m"]),
    _entry("nv-embed-v1", "embed", ["nv-embed", "embed"]),
    _entry("llama-nemotron-rerank-vl-1b-v2", "rerank", ["rerank", "vl", "1b"]),
    _entry("nemotron-parse-2.0", "ocr", ["nemotron-parse", "parse", "2.0"]),
    _entry("nemotron-ocr-v2", "ocr", ["nemotron-ocr", "ocr", "v2"]),
    _entry("nemotron-voicechat", "voice", ["voicechat", "voice"]),
    _entry("studiovoice", "tts", ["studiovoice", "studio", "voice"]),
    _entry("magpie-tts-zeroshot", "tts", ["magpie", "tts", "zeroshot"]),
    _entry("sarvam-m", "voice", ["sarvam"]),
    _entry("riva-translate-4b-instruct-v1_1", "translation", ["riva", "translate", "4b"]),
    _entry("nemotron-3-content-safety", "safety", ["content-safety", "safety"]),
    _entry("nemotron-content-safety-reasoning-4b", "safety", ["content-safety", "reasoning", "4b"]),
    _entry("llama-3.1-nemotron-safety-guard-8b-v3", "safety", ["safety-guard", "safety", "8b"]),
    _entry("Llama Guard 4 12B", "safety", ["llama-guard", "guard", "12b"]),
    _entry("gliner-pii", "safety", ["gliner", "pii"]),
    _entry("synthetic-video-detector", "video", ["synthetic-video", "detector"]),
    _entry("Active Speaker Detection", "video", ["active-speaker", "speaker"]),
    _entry("cosmos-transfer2.5-2b", "video", ["cosmos-transfer", "transfer", "2b"]),
    _entry("cosmos-transfer1-7b", "video", ["cosmos-transfer", "transfer", "7b"]),
    _entry("cosmos-predict1-5b", "video", ["cosmos-predict", "predict", "5b"]),
    _entry("streampetr", "perception", ["streampetr", "stream", "petr"]),
    _entry("bevformer", "perception", ["bevformer", "bev"]),
    _entry("sparsedrive", "perception", ["sparsedrive", "sparse", "drive"]),
    _entry("esm2-650m", "biology", ["esm2", "esm", "650m"]),
    _entry("esmfold", "biology", ["esmfold", "esm", "fold"]),
    _entry("FLUX.2 Klein 4B", "image", ["flux.2", "flux", "klein", "4b"]),
    _entry("FLUX.1-Kontext-dev", "image", ["flux.1", "flux", "kontext"]),
    _entry("FLUX.1-dev", "image", ["flux.1", "flux", "dev"]),
    _entry("FLUX.1-schnell", "image", ["flux.1", "flux", "schnell"]),
    _entry("Qwen Image", "image", ["qwen-image", "qwen", "image"]),
    _entry("Qwen Image Edit", "image", ["qwen-image-edit", "qwen", "image", "edit"]),
    _entry("usdvalidate", "perception", ["usdvalidate", "usd", "validate"]),
    _entry("mistral-nemotron", "chat", ["mistral-nemotron", "mistral", "nemotron"]),
]


def get_candidate(name: str) -> Optional[Dict]:
    for entry in SUPPLIED_CANDIDATES:
        if entry["candidate"] == name:
            return entry
    return None


def known_endpoint_id(candidate: str) -> Optional[str]:
    """Statically trusted endpoint id, or None (resolve live instead)."""
    return KNOWN_ENDPOINT_IDS.get(candidate)
