"""
Endpoint à ajouter à l'app Flask existante (duonco-devis-pdf.onrender.com)
pour générer les contrats Pilote / Bêta depuis le board Monday "Contrats Pilote/Bêta".

À faire pour l'intégrer :
1. Copier ce fichier dans le repo de l'app Flask existante.
2. Copier le dossier `templates/` (les 3 .docx normalisés) dans le repo, par ex. sous `contract_templates/`.
3. Dans le fichier principal de l'app (app.py ou main.py), ajouter :
       from contracts_endpoint import contracts_bp
       app.register_blueprint(contracts_bp)
4. Vérifier que la variable d'environnement MONDAY_API_TOKEN est déjà définie sur Render
   (c'est censé être le cas puisque l'app appelle déjà l'API Monday pour les Devis).
5. Redéployer sur Render.
"""

import os
import re
import zipfile
import shutil
import tempfile
from pathlib import Path

import requests
from flask import Blueprint, request, jsonify

contracts_bp = Blueprint("contracts", __name__)

MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_API_TOKEN = os.environ.get("MONDAY_API_TOKEN")

TEMPLATES_DIR = Path(__file__).parent / "contract_templates"

# --- Colonnes du board "Contrats Pilote/Bêta" (id 5101130932) ---
COL = {
    "type_contrat": "color_mm5py518",
    "variante": "color_mm5pbpv7",
    "nom_etablissement": "lookup_mm5p8awe",
    "adresse_rue": "lookup_mm5p1r89",
    "ville": "lookup_mm5p43xh",
    "code_postal": "lookup_mm5p4084",
    "nom_contact": "lookup_mm5p7k9",
    "fonction_contact": "lookup_mm5pbta4",
    "forme_juridique": "text_mm5p3hhh",
    "numero_rcs": "text_mm5p5j85",
    "ville_rcs": "text_mm5pdd10",
    "nom_signataire": "text_mm5pw3ft",
    "titre_signataire": "text_mm5pvrqm",
    "medecin_responsable": "text_mm5pmp85",
    "comite_site": "long_text_mm5psxg8",
    "comite_intrasense": "long_text_mm5p4bzt",
    "duree_evaluation": "text_mm5prh76",
    "file_column": "file_mm5p9fq",
}

TEMPLATE_MAP = {
    ("Bêta", None): "Beta_Unity.docx",
    ("Pilote", "Standard"): "Pilote_Standard.docx",
    ("Pilote", "Avec Option d'Achat"): "Pilote_AvecOA.docx",
}


def monday_query(query: str, variables: dict | None = None) -> dict:
    resp = requests.post(
        MONDAY_API_URL,
        json={"query": query, "variables": variables or {}},
        headers={"Authorization": MONDAY_API_TOKEN, "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def get_item_values(item_id: int) -> dict:
    query = """
    query ($itemId: [ID!]) {
      items(ids: $itemId) {
        column_values {
          id
          text
          value
        }
      }
    }
    """
    data = monday_query(query, {"itemId": [item_id]})
    values = {}
    for cv in data["items"][0]["column_values"]:
        values[cv["id"]] = cv["text"]
    return values


def build_merge_data(col_values: dict) -> dict:
    """Traduit les colonnes Monday en clés de merge fields du template."""
    return {
        "NOM_ETABLISSEMENT": col_values.get(COL["nom_etablissement"], ""),
        "ADRESSE_ETABLISSEMENT": ", ".join(
            filter(None, [
                col_values.get(COL["adresse_rue"], ""),
                col_values.get(COL["code_postal"], ""),
                col_values.get(COL["ville"], ""),
            ])
        ),
        "FORME_JURIDIQUE": col_values.get(COL["forme_juridique"], ""),
        "NUMERO_RCS": col_values.get(COL["numero_rcs"], ""),
        "VILLE_RCS": col_values.get(COL["ville_rcs"], ""),
        "NOM_REPRESENTANT": col_values.get(COL["nom_contact"], ""),
        "TITRE_REPRESENTANT": col_values.get(COL["fonction_contact"], ""),
        "NOM_SIGNATAIRE": col_values.get(COL["nom_signataire"], "") or col_values.get(COL["nom_contact"], ""),
        "TITRE_SIGNATAIRE": col_values.get(COL["titre_signataire"], "") or col_values.get(COL["fonction_contact"], ""),
        "MEDECIN_RESPONSABLE": col_values.get(COL["medecin_responsable"], ""),
        "DUREE_EVALUATION": col_values.get(COL["duree_evaluation"], ""),
        "COMITE_SUIVI_SITE": col_values.get(COL["comite_site"], ""),
        "COMITE_SUIVI_INTRASENSE": col_values.get(COL["comite_intrasense"], ""),
    }


def escape_xml_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fill_docx(template_path: Path, values: dict, output_path: Path) -> list[str]:
    work_dir = Path(tempfile.mkdtemp())
    with zipfile.ZipFile(template_path) as z:
        z.extractall(work_dir)

    doc_xml_path = work_dir / "word" / "document.xml"
    xml = doc_xml_path.read_text(encoding="utf-8")

    tokens = set(re.findall(r"\{\{([A-Z_]+)\}\}", xml))
    missing = []
    for token in tokens:
        val = values.get(token)
        if val:
            xml = xml.replace("{{%s}}" % token, escape_xml_text(str(val)))
        else:
            missing.append(token)

    doc_xml_path.write_text(xml, encoding="utf-8")

    if output_path.exists():
        output_path.unlink()
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(work_dir.rglob("*")):
            if file.is_file():
                zf.write(file, file.relative_to(work_dir))
    shutil.rmtree(work_dir)
    return missing


def upload_file_to_column(item_id: int, board_id: int, column_id: str, file_path: Path):
    query = """
    mutation ($file: File!, $itemId: ID!, $columnId: String!) {
      add_file_to_column (item_id: $itemId, column_id: $columnId, file: $file) {
        id
      }
    }
    """
    with open(file_path, "rb") as f:
        resp = requests.post(
            MONDAY_API_URL,
            headers={"Authorization": MONDAY_API_TOKEN},
            data={
                "query": query,
                "variables": f'{{"itemId": "{item_id}", "columnId": "{column_id}"}}',
                "map": '{"file": "variables.file"}',
            },
            files={"file": (file_path.name, f)},
            timeout=60,
        )
    resp.raise_for_status()
    return resp.json()


@contracts_bp.route("/generate-contract", methods=["POST"])
def generate_contract():
    """
    Webhook appelé par le bouton "Générer le contrat" du board Monday.
    Payload attendu (format standard des automatisations "when button clicked"):
        { "payload": { "inboundFieldValues": {...}, "itemId": ..., "boardId": ... } }
    """
    payload = request.json or {}

    # Étape de vérification obligatoire lors de la création du webhook côté Monday :
    # Monday envoie {"challenge": "..."} et attend exactement la même valeur en retour.
    if "challenge" in payload:
        return jsonify({"challenge": payload["challenge"]})

    item_id = payload.get("payload", {}).get("itemId") or payload.get("itemId")
    board_id = payload.get("payload", {}).get("boardId") or payload.get("boardId")

    if not item_id:
        return jsonify({"error": "itemId manquant dans le payload"}), 400

    col_values = get_item_values(int(item_id))
    contract_type = col_values.get(COL["type_contrat"])
    variante = col_values.get(COL["variante"])

    template_key = (contract_type, variante if contract_type == "Pilote" else None)
    template_filename = TEMPLATE_MAP.get(template_key)
    if not template_filename:
        return jsonify({"error": f"Pas de template pour Type={contract_type} / Variante={variante}"}), 400

    template_path = TEMPLATES_DIR / template_filename
    merge_data = build_merge_data(col_values)

    output_path = Path(tempfile.mkdtemp()) / f"contrat_{item_id}.docx"
    missing = fill_docx(template_path, merge_data, output_path)

    upload_file_to_column(item_id, board_id, COL["file_column"], output_path)

    return jsonify({
        "status": "ok",
        "champs_manquants": missing,
        "fichier": output_path.name,
    })
