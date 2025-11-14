# 🧾 RIB Extractor

**RIB Extractor** est un outil Python permettant d’extraire automatiquement les informations bancaires contenues dans des fichiers **RIB au format PDF**, qu’ils soient numériques ou scannés.

Le script utilise la reconnaissance optique de caractères (OCR) pour analyser les documents, détecte les champs bancaires (IBAN, BIC, code banque, titulaire, etc.), puis consigne le tout dans un **fichier CSV propre et structuré**.

---

## 📦 Sommaire

- [Fonctionnalités](#-fonctionnalités)
- [Aperçu du fonctionnement](#-aperçu-du-fonctionnement)
- [Installation](#-installation)
- [Utilisation](#-utilisation)
- [Structure du projet](#-structure-du-projet)
- [Dépendances techniques](#-dépendances-techniques)
- [Compatibilité](#-compatibilité)
- [Sortie CSV](#-sortie-csv)
- [Licence](#-licence)

---

## 🚀 Fonctionnalités

- **OCR automatique** sur tous les fichiers PDF (via [Tesseract](https://github.com/tesseract-ocr/tesseract))
- Extraction des champs suivants :
  - Titulaire du compte  
  - Code Banque  
  - Code Guichet  
  - Numéro de compte  
  - Clé RIB  
  - BIC / SWIFT  
  - IBAN  
  - Domiciliation (multi-lignes)
- Validation syntaxique des IBAN et BIC avec [`python-stdnum`](https://arthurdejong.org/python-stdnum/)
- Reconstruction possible d’un IBAN à partir du RIB partiel
- Export CSV clair et exploitable sous Excel (zéros conservés)
- Compatible avec les RIBs de différentes banques françaises

---

## 🧠 Aperçu du fonctionnement

1. Le script lit chaque fichier PDF présent dans le dossier `rib/`.
2. Chaque page est convertie en image haute résolution (300 dpi).
3. L’image est analysée par **Tesseract OCR** pour produire un texte brut.
4. Des expressions régulières et heuristiques détectent les champs bancaires.
5. Les résultats sont formatés, validés et exportés dans `rib_infos.csv`.

---

## ⚙️ Installation

### 1. Cloner le projet
```bash
git clone https://github.com/ton-utilisateur/rib-extractor.git
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
```
3. Les résultats sont exportés dans : `rib_infos.csv`


## Licence

Ce projet est distribué sous licence MIT.
Tu es libre de l’utiliser, de le modifier et de le redistribuer, tant que la mention d’auteur est conservée.

## Auteur

Développé par : GASMI Rémy