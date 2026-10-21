"""Central configuration. Every value can be overridden through environment variables / .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _load_streamlit_secrets() -> None:
    """Streamlit Cloud: copy top-level secrets into the environment (env / .env values win)."""
    try:
        import streamlit as st

        for key, value in st.secrets.items():
            if isinstance(value, (str, int, float, bool)):
                os.environ.setdefault(key, str(value))
    except Exception:  # streamlit missing or no secrets.toml
        pass


_load_streamlit_secrets()

ROOT_DIR = Path(__file__).resolve().parent.parent

# --- LLM (any OpenAI-compatible API: Gemini direct or OpenRouter) ---
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
LLM_BASE_URL = os.getenv("LLM_BASE_URL", os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))
IS_GEMINI = "generativelanguage.googleapis.com" in LLM_BASE_URL
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("OPENROUTER_API_KEY")
_DEFAULT_MODEL = "gemini-3.5-flash-lite" if IS_GEMINI else "google/gemini-2.5-flash"

# Each agent can have its own model and API key (<AGENT>_MODEL / <AGENT>_API_KEY), falling back to LLM_API_KEY.
# Orchestrator, Specialist and Figure need vision. Validator / Compliance are text-only.
AGENT_NAMES = ("orchestrator", "specialist", "validator", "compliance", "figure")
AGENTS = {
    name: {
        "model": os.getenv(f"{name.upper()}_MODEL", _DEFAULT_MODEL),
        "api_key": os.getenv(f"{name.upper()}_API_KEY") or LLM_API_KEY,
    }
    for name in AGENT_NAMES
}

# --- Preprocessing ---
PDF_DPI = int(os.getenv("PDF_DPI", "200"))
MAX_IMAGE_SIDE = int(os.getenv("MAX_IMAGE_SIDE", "2048"))   # px, longest side sent to the model
MIN_IMAGE_SIDE = int(os.getenv("MIN_IMAGE_SIDE", "800"))    # px, smaller images are upscaled
MAX_PAGES = int(os.getenv("MAX_PAGES", "6"))

# --- RAG ---
CHROMA_DIR = Path(os.getenv("CHROMA_DIR", ROOT_DIR / "chroma_db"))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "is_codes_v2")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5")
# BGE retrieval instruction, prepended to queries only (not to passages).
QUERY_INSTRUCTION = os.getenv(
    "QUERY_INSTRUCTION", "Represent this sentence for searching relevant passages: "
)
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "700"))        # characters
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))  # characters
RETRIEVE_K = int(os.getenv("RETRIEVE_K", "4"))

KB_SOURCES_DIR = Path(os.getenv("KB_SOURCES_DIR", ROOT_DIR / "kb_sources"))
KB_MARKDOWN_DIR = Path(os.getenv("KB_MARKDOWN_DIR", ROOT_DIR / "SP34_md"))
KB_OCR_DIR = Path(os.getenv("KB_OCR_DIR", ROOT_DIR / "kb_md"))  # per-page Gemini OCR of kb_sources PDFs
# Exported numpy index (src.rag.index_store) for deployments without Chroma/torch.
KB_INDEX_DIR = Path(os.getenv("KB_INDEX_DIR", ROOT_DIR / "kb_index"))
VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "auto")  # auto | chroma | numpy

# --- Output ---
REPORTS_DIR = ROOT_DIR / "reports"
UPLOADS_DIR = ROOT_DIR / "uploads"
