import streamlit as st
import pandas as pd
import tempfile
import os
from utils import (
    extraire_texte_ocr,
    nettoyer,
    extraire_par_libelles,
    extraire_iban_valide,
    extraire_bic_valide,
    decomposer_iban_fr,
    calculer_cle_rib,
    construire_iban_fr,
)

# streamlit run app_with_ocr.py --server.port 8502


# Configuration de la page Streamlit
st.set_page_config(page_title="RIB Extractor", page_icon="💳", layout="centered")

# --- En-tête de l'application ---
st.title("💳 RIB Extractor - OCR et Analyse Automatique")

st.markdown("""
Cet outil extrait automatiquement les informations d'un **RIB PDF** grâce à l'OCR :
- Titulaire du compte  
- Code banque, guichet, compte et clé RIB  
- IBAN et BIC / SWIFT  
- Domiciliation complète (multi-lignes)

Téléversez un ou plusieurs fichiers PDF ci-dessous pour démarrer l'analyse.
""")

# --- Zone d'upload ---
uploaded_files = st.file_uploader(
    "📁 Sélectionnez un ou plusieurs fichiers PDF :",
    type=["pdf"],
    accept_multiple_files=True
)

# --- Si aucun fichier n'est chargé ---
if not uploaded_files:
    st.info("En attente de fichiers PDF à analyser...")
    st.stop()

# --- Traitement des fichiers uploadés ---
data: list[dict] = []  # Contiendra les résultats finaux
progress = st.progress(0) # Barre de progression Streamlit
total = len(uploaded_files) # Nombre total de fichiers



# Petite fonction utilitaire : remplace "" par "MANQUANT"
def nz(v: str) -> str:
    return v if (v is not None and str(v).strip() != "") else "MANQUANT"

# Boucle principale : traitement de chaque fichier PDF uploadé
for idx, file in enumerate(uploaded_files):
    tmp_path = None
    try:
        # 1) Sauvegarde temporaire du PDF
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(file.read()) # Écriture du contenu dans un fichier local
            tmp_path = tmp.name # Stockage du chemin vers le fichier temp

        # 2) OCR
        st.write(f"🔍 Lecture et OCR sur **{file.name}** ...")
        texte = extraire_texte_ocr(tmp_path) # OCR brut
        tclean = nettoyer(texte) # Nettoyage du texte OCR

        # Si rien n'est lu par l'OCR, on considère que c'est une erreur "douce"
        if not tclean.strip():
            raise RuntimeError("OCR vide (aucun texte exploitable)")

        # 3) Extraction des informations
        iban = extraire_iban_valide(tclean)
        cb = cg = nc = cle = tit = dom = ""

        if iban:
            cb, cg, nc, cle = decomposer_iban_fr(iban)

        # Valeurs trouvées via libellés si IBAN incomplet
        lb_cb, lb_cg, lb_nc, lb_cle, lb_tit, lb_dom = extraire_par_libelles(tclean)
        cb = cb or lb_cb
        cg = cg or lb_cg
        nc = nc or lb_nc
        cle = cle or lb_cle
        tit = lb_tit
        dom = lb_dom

        # 4) Calcul clé ou reconstruction IBAN si possible
        if not cle and all([cb, cg, nc]):
            cle = calculer_cle_rib(cb, cg, nc)
        if not iban and all([cb, cg, nc, cle]):
            iban = construire_iban_fr(cb, cg, nc, cle)

        # Extraction du bic
        bic = extraire_bic_valide(tclean)

        # 5) Ajout des résultats OK
        data.append({
            "Fichier": file.name,
            "Statut": "OK",
            "Titulaire du compte": nz(tit),
            "Code Banque": nz(cb),
            "Code Guichet": nz(cg),
            "N° de compte": nz(nc),
            "Clé RIB": nz(cle),
            "BIC / SWIFT": nz(bic),
            "IBAN": nz(iban),
            "Domiciliation": nz(dom),
        })

    except Exception as e:
        # En cas d'erreur: on ajoute quand même une ligne avec le nom du fichier et le message d'erreur
        err_msg = f"ERREUR: {str(e)}"
        # Si besoin de deboggage plus fin, décommente la ligne suivante:
        # err_msg = f"ERREUR: {e}\n{traceback.format_exc()}"
        data.append({
            "Fichier": file.name,
            "Statut": err_msg,
            "Titulaire du compte": "MANQUANT",
            "Code Banque": "MANQUANT",
            "Code Guichet": "MANQUANT",
            "N° de compte": "MANQUANT",
            "Clé RIB": "MANQUANT",
            "BIC / SWIFT": "MANQUANT",
            "IBAN": "MANQUANT",
            "Domiciliation": "MANQUANT",
        })
    finally:
        # Nettoyage du fichier temporaire
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

        # Mise à jour de la progression
        progress.progress((idx + 1) / total)

# --- Affichage des résultats ---
df = pd.DataFrame(data)

# On met la colonne Statut devant pour la visibilité
cols = ["Fichier", "Statut", "Titulaire du compte", "Code Banque", "Code Guichet",
        "N° de compte", "Clé RIB", "BIC / SWIFT", "IBAN", "Domiciliation"]
df = df.reindex(columns=cols)

st.success("✅ Extraction terminée !")
st.dataframe(df, width="stretch")

# --- Export CSV ---
csv = df.to_csv(index=False).encode("utf-8")
st.download_button(
    label="⬇️ Télécharger les résultats en CSV",
    data=csv,
    file_name="rib_infos.csv",
    mime="text/csv",
)
