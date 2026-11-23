"""
RIB Extractor v4 — Gemini Vision (primaire) + pdfplumber (vérification)

Identique à v3, mais Settings est défini localement avec pydantic.BaseModel
au lieu de pydantic-settings.BaseSettings, ce qui supprime la dépendance
pydantic-settings (non disponible sur certains environnements Streamlit Cloud).
"""

import io
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pdfplumber
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr, ValidationError
from google import genai
from google.genai import types

from models import RibData
from utils import (
    nettoyer,
    extraire_par_libelles,
    extraire_iban_valide,
    construire_iban_fr,
)


# ---------------------------------------------------------------------------
# Configuration (sans pydantic-settings)
# ---------------------------------------------------------------------------

class Settings(BaseModel):
    """Configuration chargée depuis .env ou variables d'environnement.

    SecretStr garantit que gemini_api_key n'apparaît jamais en clair
    dans les logs ou les repr().
    """

    gemini_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="Clé API Google Gemini (jamais loggée).",
    )
    gemini_model: str = Field(
        default="gemini-flash-latest",
        description="Identifiant du modèle Gemini.",
    )
    texte_min_chars: int = Field(
        default=80,
        ge=1,
        description="Seuil de caractères pour détecter un PDF natif (vérification pdfplumber).",
    )

    @classmethod
    def from_env(cls) -> "Settings":
        """Charge depuis .env (local) ou variables d'environnement (Streamlit Cloud)."""
        load_dotenv()
        return cls(
            gemini_api_key=SecretStr(os.getenv("GEMINI_API_KEY", "")),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
            texte_min_chars=int(os.getenv("TEXTE_MIN_CHARS", "80")),
        )


_settings = Settings.from_env()
# Surcharge depuis st.secrets si la clé n'est pas dans .env (Streamlit Cloud)
if not _settings.gemini_api_key.get_secret_value():
    _settings = _settings.model_copy(
        update={"gemini_api_key": SecretStr(st.secrets.get("GEMINI_API_KEY", ""))}
    )

_gemini_client: genai.Client | None = None
if _settings.gemini_api_key.get_secret_value():
    try:
        _gemini_client = genai.Client(api_key=_settings.gemini_api_key.get_secret_value())
    except Exception:
        _gemini_client = None


# ---------------------------------------------------------------------------
# Prompt Gemini
# ---------------------------------------------------------------------------

PROMPT = """
Tu es un expert en documents bancaires français.

Analyse ce RIB et renvoie STRICTEMENT ce JSON :

{
  "titulaire": "",
  "code_banque": "",
  "code_guichet": "",
  "numero_compte": "",
  "cle_rib": "",
  "iban": "",
  "bic": "",
  "domiciliation": ""
}

RÈGLES :
- Si une information est absente : mets "".
- Ne JAMAIS inventer.
- Tu dois renvoyer UNIQUEMENT le JSON, sans texte autour.
"""


# ---------------------------------------------------------------------------
# Extraction Gemini (primaire, tous fichiers)
# ---------------------------------------------------------------------------

def _nettoyer_json(texte: str) -> str:
    """Isole le JSON dans la réponse brute du modèle."""
    for pat in [
        r"```json\s*(\{.*?\})\s*```",
        r"```\s*(\{.*?\})\s*```",
        r"(\{.*\})",
    ]:
        m = re.search(pat, texte, re.DOTALL)
        if m:
            return m.group(1)
    return texte


_exhausted_models: set[str] = set()

_FALLBACK_MODELS: list[str] = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-omni-1.2-flash",
    "gemini-omni-1.1-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-image",
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
]
_MAX_RETRIES = 3


def _is_503(exc: Exception) -> bool:
    """Détecte une erreur 503 / UNAVAILABLE de l'API Gemini."""
    msg = str(exc)
    return "503" in msg or "UNAVAILABLE" in msg


def _is_404(exc: Exception) -> bool:
    """Détecte un modèle indisponible (retiré ou inaccessible)."""
    msg = str(exc)
    return "404" in msg or "NOT_FOUND" in msg


def _is_429(exc: Exception) -> bool:
    """Détecte un quota dépassé (quota free tier par modèle)."""
    msg = str(exc)
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg


def extraire_via_gemini(raw_bytes: bytes, mime_type: str) -> RibData | str:
    """Envoie le document à Gemini avec retry + fallback automatique sur 503.

    Stratégie :
      1. Tente le modèle principal jusqu'à _MAX_RETRIES fois (backoff exponentiel).
      2. Si toujours 503, essaie les modèles de secours dans _FALLBACK_MODELS.
      3. Retourne une erreur lisible si tous les modèles échouent.
    """
    if not _gemini_client:
        return "__ERROR__ Clé GEMINI_API_KEY manquante ou invalide"

    models = [
        m for m in [_settings.gemini_model] + _FALLBACK_MODELS
        if m not in _exhausted_models
    ]

    for model in models:
        for attempt in range(_MAX_RETRIES):
            try:
                response = _gemini_client.models.generate_content(
                    model=model,
                    contents=[
                        types.Part.from_text(text=PROMPT),
                        types.Part.from_bytes(data=raw_bytes, mime_type=mime_type),
                    ],
                )
                json_str = _nettoyer_json(response.text)
                return RibData.model_validate_json(json_str)
            except ValidationError as e:
                return f"__ERROR__ Données invalides ({e.error_count()} champ(s)) : {e.errors()[0]['msg']}"
            except json.JSONDecodeError:
                raw = getattr(response, "text", "")
                return f"__ERROR__ Réponse non-JSON : {raw[:200]}"
            except Exception as e:
                if _is_404(e) or _is_429(e):
                    _exhausted_models.add(model)  # ne plus retenter ce modèle
                    break
                if _is_503(e):
                    if attempt < _MAX_RETRIES - 1:
                        time.sleep(2 ** attempt)  # 1s, 2s, 4s
                        continue
                    break  # passe au modèle suivant
                return f"__ERROR__ {e}"

    return "__ERROR__ Tous les modèles sont indisponibles (quota épuisé ou surcharge). Réessayez demain ou passez à un plan payant."


# ---------------------------------------------------------------------------
# Vérification pdfplumber (PDF natifs uniquement)
# ---------------------------------------------------------------------------

def _extraire_texte_pdfplumber(raw_bytes: bytes) -> str:
    """Extrait le texte brut d'un PDF natif."""
    with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages).strip()


def _extraire_iban_via_regex(texte: str) -> str:
    """Extrait uniquement l'IBAN depuis un texte pdfplumber pour comparaison."""
    tclean = nettoyer(texte)
    iban = extraire_iban_valide(tclean)
    if not iban:
        lb_cb, lb_cg, lb_nc, lb_cle, _, _ = extraire_par_libelles(tclean)
        if all([lb_cb, lb_cg, lb_nc, lb_cle]):
            iban = construire_iban_fr(lb_cb, lb_cg, lb_nc, lb_cle)
    return iban


def verifier_iban(iban_gemini: str, raw_bytes: bytes) -> tuple[str, str]:
    """Compare l'IBAN Gemini avec celui extrait par pdfplumber.

    Retourne (statut, iban_corrige) où iban_corrige est l'IBAN pdfplumber
    quand il diffère de Gemini (correction d'hallucination), sinon "".
    """
    texte = _extraire_texte_pdfplumber(raw_bytes)
    if len(texte) < _settings.texte_min_chars:
        return "— scan ou image", ""
    iban_pdf = _extraire_iban_via_regex(texte)
    if not iban_pdf:
        return "— pdfplumber : aucun IBAN trouvé", ""
    if iban_gemini.replace(" ", "").upper() == iban_pdf.replace(" ", "").upper():
        return "✅ IBAN concordant", ""
    return f"⚠️ IBAN corrigé (Gemini : {iban_gemini})", iban_pdf


# ---------------------------------------------------------------------------
# Interface Streamlit
# ---------------------------------------------------------------------------

st.set_page_config(page_title="RIB Extractor v4", page_icon="💳", layout="centered")

st.title("💳 RIB Extractor v4")
st.markdown("""
**Stratégie d'extraction :**
- **Gemini 2.0 Flash** — extraction principale sur tous les fichiers (PDF natif, scanné, image)
- **pdfplumber** — vérification croisée de l'IBAN sur les PDF natifs (colonne *Vérification*)

Téléversez vos RIB (PDF ou images) pour démarrer.
""")

if not _settings.gemini_api_key.get_secret_value():
    st.error(
        "❌ Aucune clé `GEMINI_API_KEY` détectée. "
        "Ajoutez-la dans `.env` ou `.streamlit/secrets.toml`."
    )
    st.stop()

uploaded_files = st.file_uploader(
    "📁 Sélectionnez vos RIB :",
    type=["pdf", "png", "jpg", "jpeg"],
    accept_multiple_files=True,
)

if not uploaded_files:
    st.session_state.pop("results", None)
    st.info("En attente de fichiers…")
    st.stop()

# Lecture séquentielle (objets Streamlit non thread-safe)
file_data = [(f.name, f.type, f.read()) for f in uploaded_files]
uploaded_names = {name for name, _, _ in file_data}

# Initialise / purge les résultats obsolètes
if "results" not in st.session_state:
    st.session_state.results = {}
st.session_state.results = {
    k: v for k, v in st.session_state.results.items() if k in uploaded_names
}

# Fichiers à traiter : pas encore dans les résultats, ou en erreur
to_process = [
    (name, mime, rb) for name, mime, rb in file_data
    if name not in st.session_state.results
    or st.session_state.results[name].get("Erreur", "").startswith("__ERROR__")
]


def _traiter_fichier(name: str, mime_type: str, raw_bytes: bytes) -> dict:
    """Traite un fichier : extraction Gemini + vérification pdfplumber."""
    erreur = ""
    verification = ""
    rib_data = RibData()
    result = extraire_via_gemini(raw_bytes, mime_type)
    if isinstance(result, str):
        erreur = result
    else:
        rib_data = result
        if mime_type == "application/pdf":
            verification, iban_corrige = verifier_iban(rib_data.iban, raw_bytes)
            if iban_corrige:
                rib_data = rib_data.model_copy(update={"iban": iban_corrige})
    return rib_data.to_export_row(name, "Gemini Vision", erreur, verification)


if to_process:
    progress = st.progress(0)
    total = len(to_process)
    table_placeholder = st.empty()
    done = 0

    with ThreadPoolExecutor(max_workers=min(total, 2)) as executor:
        futures = {
            executor.submit(_traiter_fichier, name, mime, rb): name
            for name, mime, rb in to_process
        }
        for future in as_completed(futures):
            row = future.result()
            st.session_state.results[row["Fichier"]] = row
            done += 1
            progress.progress(done / total)
            current_rows = [st.session_state.results[n] for n, _, _ in file_data if n in st.session_state.results]
            table_placeholder.dataframe(pd.DataFrame(current_rows), use_container_width=True)

rows = [st.session_state.results[name] for name, _, _ in file_data if name in st.session_state.results]
df = pd.DataFrame(rows)

error_count = sum(1 for r in rows if r.get("Erreur", "").startswith("__ERROR__"))
if error_count:
    st.warning(f"⚠️ {error_count} fichier(s) en erreur.")
    if st.button(f"🔄 Réessayer ({error_count} fichier(s))"):
        for r in rows:
            if r.get("Erreur", "").startswith("__ERROR__"):
                st.session_state.results.pop(r["Fichier"], None)
        st.rerun()
else:
    st.success("✅ Extraction terminée")

st.dataframe(df, use_container_width=True)

csv_bytes = df.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Télécharger CSV", data=csv_bytes, file_name="rib_extraction_v4.csv", mime="text/csv")

excel_buf = io.BytesIO()
with pd.ExcelWriter(excel_buf, engine="xlsxwriter") as writer:
    df.to_excel(writer, index=False)
st.download_button("📎 Télécharger Excel", data=excel_buf.getvalue(), file_name="rib_extraction_v4.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

parquet_buf = io.BytesIO()
df.to_parquet(parquet_buf, index=False)
st.download_button("🗂️ Télécharger Parquet", data=parquet_buf.getvalue(), file_name="rib_extraction_v4.parquet", mime="application/octet-stream")
