# 🧾 RIB Extractor


[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-App-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![OCR](https://img.shields.io/badge/OCR-Tesseract-blue)](https://github.com/tesseract-ocr/tesseract)
[![Gemini API](https://img.shields.io/badge/Google_AI_Gemini-2.0_Flash-yellow?logo=google&logoColor=white)](https://ai.google.dev)
[![UV Managed](https://img.shields.io/badge/Package_Manager-uv-7F52FF?logo=python&logoColor=white)](https://docs.astral.sh/uv/)



RIB Extractor est un outil complet permettant d’extraire automatiquement les informations d’un RIB français, que ce soit via :

  * 🟦 OCR Tesseract (version autonome, locale, sans API)

  * 🟨 IA Vision (VLM) Gemini 2.0 Flash (lecture visuelle solide directement sur PDF/images)

L’application est disponible en ligne :
👉 https://mastocodeur-rib-extractor-app-su5k18.streamlit.app/


---

## 🚀 Fonctionnalités

Quel que soit le mode choisi (OCR ou VLM), l’outil extrait :

* Titulaire du compte
* Code Banque
* Code Guichet
* Numéro de compte
* Clé RIB
* IBAN (format propre et espacés 4/4)
* BIC / SWIFT (normalisation automatique)
* Domiciliation multi-lignes
* Export CSV utilisable dans Excel (zéros conservés)

---

# Version OCR locale : `app_with_ocr.py`

1. Le script lit chaque fichier PDF présent dans le dossier `rib/`.
2. Chaque page est convertie en image haute résolution (300 dpi).
3. L’image est analysée par **Tesseract OCR** pour produire un texte brut.
4. Des expressions régulières et heuristiques détectent les champs bancaires.
5. Les résultats sont formatés, validés et exportés dans `rib_infos.csv`.



## ⚙️ Installation

### 1. Cloner le projet
```bash
git clone https://github.com/Mastocodeur/rib-extractor.git
cd rib-extractor
```

### 2. Créer un environnement virtuel (via uv ou venv)
```bash
uv venv
source .venv/bin/activate
```

### 3. Installer les dépendances (depuis pyproject.toml)

```bash
uv pip install -e .
```

### 4. Installer Tesseract OCR et Poppler

```bash
sudo apt install tesseract-ocr tesseract-ocr-fra poppler-utils
```

---

## Utilisation

1. Dépose tous tes fichiers PDF de RIB dans le dossier `rib/`.
2. Exécute le script principal :
```bash
uv run python rib_extractor.py

ou

uv run streamlit run app_with_ocr.py
```
3. Les résultats sont exportés dans : `rib_infos.csv`

**On notera que cette version fait des erreurs**.



# Version IA Vision Gemini : `app.py`

Cette version utilise le modèle Gemini 2.0 Flash Vision via l’API REST Google.

Elle lit :

* PDF natifs
* PDF scannés
* Photos de RIB
* RIB partiellement illisibles par OCR

L’IA extrait directement le contenu visuel sans OCR local.

L'avantage est sa robustesse sur tous les formats (photo, scan, flou) et la diminution drastique du nombre d'erreurs vis à vis de la version avec OCR.


## 🔑 Obtenir une clé API Gemini

1. Aller sur Google AI Studio : https://ai.google.dev

2. Menu “API Keys” ==> Générer une clé API.

3. Pour la version Streamlit Cloud : il faudra ajouter cette clé API dans Settings puis Secrets.

4. Pour une utilisation locale : Créer un fichier `.env`


5. `uv run streamlit run app.py`

## Licence

Ce projet est distribué sous licence MIT.
Les contributions sont les bienvenues !

## Auteur

Développé par : GASMI Rémy