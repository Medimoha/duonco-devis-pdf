"""
Service webhook DUOnco - Génération automatique de PDF de devis
==================================================================

Ce service reçoit un webhook Monday.com quand le bouton "Générer PDF"
est cliqué sur un item du tableau Devis, génère le PDF (produits,
remises, TVA, récapitulatif pluriannuel) et l'attache directement à
l'item. Fonctionne 100% de façon autonome, sans dépendance à Claude.

Variables d'environnement requises :
  MONDAY_API_TOKEN   - Jeton d'API Monday (Admin > API dans Monday.com)

Déploiement : voir README.md
"""
import os
import io
import json
import textwrap

import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from flask import Flask, request, jsonify

app = Flask(__name__)

API = "https://api.monday.com/v2"
API_FILE = "https://api.monday.com/v2/file"
MONDAY_API_TOKEN = os.environ.get("MONDAY_API_TOKEN", "")

BLUE = "#1a5fa8"
DEVIS_BOARD = 5100458021
CATALOG_BOARD = 5100457983
ITPS_BOARD = 5100457987
DEVIS_FILE_COLUMN = "file_mm5gqd64"
BUTTON_COLUMN_ID = "button_mm5gm66d"


def _headers():
    return {"Authorization": MONDAY_API_TOKEN, "Content-Type": "application/json"}


def gql(query, variables=None):
    r = requests.post(API, json={"query": query, "variables": variables or {}}, headers=_headers())
    j = r.json()
    if "errors" in j:
        raise RuntimeError(json.dumps(j["errors"]))
    return j["data"]


def money(v, currency="EUR"):
    return f"{currency} {v:,.2f}".replace(",", " ").replace(".", ",")


def cv_map(column_values):
    return {c["id"]: c for c in column_values}


def get_devis(item_id):
    q = """
    query ($ids: [ID!]) {
      items(ids: $ids) {
        id
        name
        column_values { id text value }
        subitems {
          id
          name
          column_values(ids: ["board_relation_mm5gk5zd","numeric_mm5gsf0b","numeric_mm5gr19j","numeric_mm5g8qyc","boolean_mm5ggx5x"]) {
            id
            text
            value
            ... on BoardRelationValue { linked_item_ids linked_items { id name board { id } } }
          }
        }
      }
    }
    """
    data = gql(q, {"ids": [item_id]})
    items = data["items"]
    if not items:
        raise RuntimeError(f"Item {item_id} not found")
    return items[0]


def get_catalog_items(ids):
    result = {}
    if ids:
        q = """
        query ($ids: [ID!]) {
          items(ids: $ids) { id name column_values { id text value } }
        }
        """
        data = gql(q, {"ids": list(ids)})
        for it in data["items"]:
            result[it["id"]] = it
    return result


def generate_and_upload(item_id):
    devis = get_devis(item_id)
    dcv = cv_map(devis["column_values"])

    objet = dcv.get("text_mm5ghzkg", {}).get("text") or devis["name"]
    langue = dcv.get("dropdown_mm5gt3at", {}).get("text") or "Français"
    regime_tva = dcv.get("dropdown_mm5gzjg6", {}).get("text") or ""
    type_prix = dcv.get("dropdown_mm5g2ke0", {}).get("text") or ""
    duree_engagement = dcv.get("numeric_mm5gddnv", {}).get("text") or "1"
    conditions_paiement = dcv.get("dropdown_mm5gdv6j", {}).get("text") or ""
    conditions_livraison = dcv.get("dropdown_mm5gpdje", {}).get("text") or ""
    date_expiration = dcv.get("date_mm5gbfg1", {}).get("text") or ""
    quote_number_raw = dcv.get("autonumber_mm5g3aew", {}).get("text") or ""

    try:
        duree_engagement = max(1, int(float(duree_engagement)))
    except Exception:
        duree_engagement = 1

    try:
        quote_number = f"Q-{int(quote_number_raw):07d}"
    except Exception:
        quote_number = quote_number_raw or "Q-XXXXXXX"

    vat_rate = 0.20 if "20%" in regime_tva else 0.0

    subitems = devis.get("subitems", [])
    catalog_ids = set()
    line_specs = []
    for si in subitems:
        scv = cv_map(si["column_values"])
        rel = scv.get("board_relation_mm5gk5zd", {})
        linked_ids = rel.get("linked_item_ids") or []
        if not linked_ids:
            continue
        linked_id = str(linked_ids[0])
        qty = scv.get("numeric_mm5gsf0b", {}).get("text") or "1"
        try:
            qty = float(qty)
        except Exception:
            qty = 1.0
        disc_pct = scv.get("numeric_mm5gr19j", {}).get("text") or "0"
        disc_val = scv.get("numeric_mm5g8qyc", {}).get("text") or "0"
        try:
            disc_pct = float(disc_pct)
        except Exception:
            disc_pct = 0.0
        try:
            disc_val = float(disc_val)
        except Exception:
            disc_val = 0.0
        optional = False
        opt_cv = scv.get("boolean_mm5ggx5x", {}).get("value")
        if opt_cv:
            try:
                optional = bool(json.loads(opt_cv).get("checked"))
            except Exception:
                optional = False
        line_specs.append({"linked_id": linked_id, "qty": qty, "disc_pct": disc_pct,
                            "disc_val": disc_val, "optional": optional})
        catalog_ids.add(linked_id)

    all_catalog = get_catalog_items(catalog_ids)

    lines = []
    for spec in line_specs:
        cat_item = all_catalog.get(spec["linked_id"])
        if not cat_item:
            continue
        ccv = cv_map(cat_item["column_values"])
        if "numeric_mm5g2n38" in ccv and ccv["numeric_mm5g2n38"].get("text"):
            list_price = float(ccv["numeric_mm5g2n38"]["text"] or 0)
            duration = ccv.get("numeric_mm5gfh40", {}).get("text")
            duration = int(float(duration)) if duration else 1
            description = ccv.get("long_text_mm5afcad", {}).get("text") or ""
            recurring = True
        else:
            list_price = float(ccv.get("numeric_mm5a9va0", {}).get("text") or 0)
            duration = 1
            description = ccv.get("long_text_mm5agwgw", {}).get("text") or ""
            recurring = False

        net_unit = list_price * (1 - spec["disc_pct"] / 100) - spec["disc_val"]
        net_total = net_unit * spec["qty"]
        lines.append({"name": cat_item["name"], "description": description, "qty": spec["qty"],
                      "list_price": list_price, "disc_pct": spec["disc_pct"], "disc_val": spec["disc_val"],
                      "net_total": net_total, "recurring": recurring, "optional": spec["optional"],
                      "duration": duration or 1})

    firm_recurring = [l for l in lines if l["recurring"] and not l["optional"]]
    firm_onetime = [l for l in lines if not l["recurring"] and not l["optional"]]
    opt_recurring = [l for l in lines if l["recurring"] and l["optional"]]
    opt_onetime = [l for l in lines if not l["recurring"] and l["optional"]]

    annual_recurring = sum(l["net_total"] for l in firm_recurring)
    onetime_total = sum(l["net_total"] for l in firm_onetime)

    years_recap = []
    for y in range(1, duree_engagement + 1):
        onetime_y = onetime_total if y == 1 else 0.0
        total_ht = onetime_y + annual_recurring
        vat = total_ht * vat_rate
        years_recap.append({"label": f"Année {y}", "onetime": onetime_y, "recurring": annual_recurring,
                             "total_ht": total_ht, "vat": vat, "total_ttc": total_ht + vat})

    net_ferme = annual_recurring + onetime_total
    vat_ferme = net_ferme * vat_rate
    ttc_ferme = net_ferme + vat_ferme

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor("white")

        def bar(y, h, text, fontsize=10, color=BLUE, textcolor="white", x=0.06, w=0.88):
            fig.patches.append(plt.Rectangle((x, y - h), w, h, transform=fig.transFigure,
                                              facecolor=color, edgecolor="none"))
            fig.text(x + 0.01, y - h / 2, text, fontsize=fontsize, color=textcolor,
                      va="center", ha="left", weight="bold")

        logo_ax = fig.add_axes([0.06, 0.905, 0.30, 0.06])
        logo_ax.set_xlim(0, 10)
        logo_ax.set_ylim(0, 2)
        logo_ax.axis("off")
        logo_ax.text(0, 1, "intra", fontsize=22, weight="bold", color="#3a3d42", va="center", ha="left")
        circle = plt.Circle((4.6, 1), 1.15, color="#2a8fd6")
        logo_ax.add_patch(circle)
        logo_ax.text(4.6, 1, "sense", fontsize=15, weight="bold", color="white", va="center", ha="center")

        bar(0.965, 0.03, f"DEVIS   {quote_number}", fontsize=11, x=0.60, w=0.34)
        fig.text(0.60, 0.925, f"Date d'expiration : {date_expiration}", fontsize=8)
        fig.text(0.60, 0.912, f"Objet : {objet}", fontsize=8, weight="bold")

        y = 0.86
        fig.text(0.06, y, f"Langue : {langue}   |   Régime TVA : {regime_tva}   |   Type Prix : {type_prix}", fontsize=8.5)
        y -= 0.014
        fig.text(0.06, y, f"Conditions de paiement : {conditions_paiement}", fontsize=8.5)
        y -= 0.014
        fig.text(0.06, y, f"Conditions de livraison : {conditions_livraison}", fontsize=8.5)
        y -= 0.014
        fig.text(0.06, y, f"Durée d'engagement : {duree_engagement} an(s)", fontsize=8.5)
        y -= 0.03

        PAGE_H_IN = 11.69
        ROW_H_IN = 0.30  # fixed absolute row height (comfortable for 7.5pt text)

        def draw_table(y_top, title, rows, headers, col_widths):
            bar(y_top, 0.022, title, fontsize=9)
            y_table_top = y_top - 0.022
            n_rows = len(rows) + 1
            table_h_frac = (ROW_H_IN * n_rows) / PAGE_H_IN
            bottom = y_table_top - table_h_frac
            ax = fig.add_axes([0.06, bottom, 0.88, table_h_frac])
            ax.axis("off")
            tbl = ax.table(cellText=rows, colLabels=headers, cellLoc="left",
                            colWidths=col_widths, loc="center")
            tbl.auto_set_font_size(False)
            tbl.set_fontsize(7.5)
            row_frac = 1.0 / n_rows
            for (r, c), cell in tbl.get_celld().items():
                cell.set_height(row_frac)
                cell.set_edgecolor("#cccccc")
                if r == 0:
                    cell.set_facecolor(BLUE)
                    cell.set_text_props(color="white", weight="bold")
                else:
                    cell.set_facecolor("white")
            return bottom - 0.015

        def recurring_rows(ls):
            rows = []
            for l in ls:
                disc = f"{l['disc_pct']}%" if l["disc_pct"] else ("-" if not l["disc_val"] else money(l["disc_val"]))
                total_engagement = l["net_total"] * l["duration"]
                desc_short = textwrap.shorten(l["description"], width=70, placeholder="...")
                rows.append([l["name"], desc_short, str(int(l["qty"])), money(l["list_price"]),
                             disc, f"{l['duration']} an(s)", money(l["net_total"]), money(total_engagement)])
            return rows

        def onetime_rows(ls):
            rows = []
            for l in ls:
                disc = f"{l['disc_pct']}%" if l["disc_pct"] else ("-" if not l["disc_val"] else money(l["disc_val"]))
                desc_short = textwrap.shorten(l["description"], width=90, placeholder="...")
                rows.append([l["name"], desc_short, str(int(l["qty"])), money(l["list_price"]), disc, money(l["net_total"])])
            return rows

        rec_headers = ["Produit", "Description", "Qté", "Px liste", "Remise", "Durée", "Coût annuel", "Coût total"]
        rec_widths = [0.16, 0.30, 0.05, 0.10, 0.09, 0.08, 0.11, 0.11]
        one_headers = ["Produit", "Description", "Qté", "Px liste", "Remise", "Total net"]
        one_widths = [0.18, 0.42, 0.06, 0.11, 0.11, 0.12]

        if firm_recurring:
            y = draw_table(y, "PRODUITS & SERVICES AVEC ABONNEMENT", recurring_rows(firm_recurring), rec_headers, rec_widths)
        if firm_onetime:
            y = draw_table(y, "ITPS & PRODUITS À COÛT UNIQUE", onetime_rows(firm_onetime), one_headers, one_widths)
        if opt_recurring:
            y = draw_table(y, "OPTIONS - PRODUITS & SERVICES AVEC ABONNEMENT", recurring_rows(opt_recurring), rec_headers, rec_widths)
        if opt_onetime:
            y = draw_table(y, "OPTIONS - ITPS & PRODUITS À COÛT UNIQUE", onetime_rows(opt_onetime), one_headers, one_widths)

        if opt_recurring or opt_onetime:
            fig.text(0.06, y, "Les lignes « Options » ne sont pas incluses dans le total ferme ci-dessous.", fontsize=7.5, style="italic")
            y -= 0.02

        recap_headers = ["Poste"] + [yr["label"] for yr in years_recap]
        recap_rows = [
            ["Coût unique HT"] + [money(yr["onetime"]) for yr in years_recap],
            ["Coût récurrent HT"] + [money(yr["recurring"]) for yr in years_recap],
            ["Total HT"] + [money(yr["total_ht"]) for yr in years_recap],
            [f"TVA ({int(vat_rate*100)}%)"] + [money(yr["vat"]) for yr in years_recap],
            ["Total TTC"] + [money(yr["total_ttc"]) for yr in years_recap],
        ]
        recap_widths = [0.22] + [0.66 / len(years_recap)] * len(years_recap)
        y = draw_table(y, "RÉCAPITULATIF PLURIANNUEL CLIENT", recap_rows, recap_headers, recap_widths)

        y -= 0.01
        fig.text(0.06, y, f"Total net (ferme, hors option) : {money(net_ferme)}", fontsize=9, weight="bold")
        y -= 0.016
        fig.text(0.06, y, f"TVA ({int(vat_rate*100)}%) : {money(vat_ferme)}", fontsize=9)
        y -= 0.016
        fig.text(0.06, y, f"Total TTC : {money(ttc_ferme)}", fontsize=10, weight="bold", color=BLUE)

        fig.text(0.06, 0.03, "Devis généré automatiquement — Intrasense SA", fontsize=7, color="#888888")

        pdf.savefig(fig)
        plt.close(fig)

    buf.seek(0)
    pdf_bytes = buf.read()

    upload_query = """
    mutation ($item_id: ID!, $column_id: String!, $file: File!) {
      add_file_to_column(item_id: $item_id, column_id: $column_id, file: $file) { id }
    }
    """
    variables = {"item_id": item_id, "column_id": DEVIS_FILE_COLUMN, "file": None}
    map_field = {"file": ["variables.file"]}
    resp = requests.post(
        API_FILE,
        headers={"Authorization": MONDAY_API_TOKEN},
        data={"query": upload_query, "variables": json.dumps(variables), "map": json.dumps(map_field)},
        files={"file": (f"{quote_number}.pdf", pdf_bytes, "application/pdf")},
    )
    return {"quote_number": quote_number, "n_lines": len(lines), "net_ferme": net_ferme,
            "ttc_ferme": ttc_ferme, "upload_result": resp.json()}


@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_json(force=True, silent=True) or {}

    # Monday webhook handshake: must echo back the challenge, unmodified
    if "challenge" in payload:
        return jsonify({"challenge": payload["challenge"]})

    event = payload.get("event", {})
    column_id = event.get("columnId")
    item_id = event.get("pulseId") or event.get("itemId")

    # Only react to clicks on the "Générer PDF" button column
    if column_id != BUTTON_COLUMN_ID or not item_id:
        return jsonify({"status": "ignored"}), 200

    try:
        result = generate_and_upload(int(item_id))
        return jsonify({"status": "ok", "result": result}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
