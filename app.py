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
ORANGE = "#e8862e"
DEVIS_BOARD = 5100458021
CATALOG_BOARD = 5100457983
ITPS_BOARD = 5100457987
DEVIS_FILE_COLUMN = "file_mm5gqd64"
BUTTON_COLUMN_ID = "button_mm5gm66d"

BANK_DETAILS = [
    "SG MONTPELLIER",
    "IBAN : FR76 3000 3014 3000 0200 9425 067",
    "CODE SWIFT : SOGEFRPP",
]

FOOTER_LEGAL = (
    "Intrasense SA | Agences : Montpellier, Shanghai | SIRET 452 479 504 00048\n"
    "Siège Social : 1231 avenue du Mondial 98 34000 Montpellier, France | Certification ISO 13485\n"
    "Capital Social 2 566 370,70 euros | RCS Montpellier 452 479 504 | APE 5829C | TVA Intracommunautaire FR 57 452 479 504\n"
    "Tél.: +33 (0) 467 130 130 | Fax: +33 (0) 467 130 132 | www.intrasense.fr | adv@intrasense.fr"
)


def get_labels(langue):
    """Returns all static (non data-driven) strings, in French or English."""
    if langue and langue.strip().lower().startswith("engl"):
        return {
            "quote": "QUOTE",
            "expiration": "Quote expiration date:",
            "subject": "Objet:" if False else "Subject:",
            "payment_conditions": "Payment conditions:",
            "delivery_conditions": "Delivery conditions:",
            "engagement_duration": "Engagement duration:",
            "years_suffix": "year(s)",
            "section_subscription": "SOFTWARE & SERVICES WITH SUBSCRIPTION",
            "section_onetime": "ITPS & ONE-TIME PRODUCTS",
            "section_subscription_optional": "OPTIONS - SOFTWARE & SERVICES WITH SUBSCRIPTION",
            "section_onetime_optional": "OPTIONS - ITPS & ONE-TIME PRODUCTS",
            "rec_headers": ["Product", "Description", "Qty", "List price", "Discount", "Duration", "Annual cost", "Total cost"],
            "one_headers": ["Product", "Description", "Qty", "List price", "Discount", "Total net"],
            "option_note": "Lines marked \u201cOptions\u201d are not included in the firm total below; they will be billed separately if the client confirms them.",
            "recap_title": "MULTI-YEAR CLIENT SUMMARY",
            "recap_col_label": "Item",
            "recap_row_onetime": "One-time cost (excl. VAT)",
            "recap_row_recurring": "Recurring cost (excl. VAT)",
            "recap_row_total_ht": "Total (excl. VAT)",
            "recap_row_vat": "VAT",
            "recap_row_total_ttc": "Total (incl. VAT)",
            "year_label": "Year",
            "net_total": "Net total (firm, excl. options)",
            "vat": "VAT",
            "total_incl_tax": "Total incl. tax",
            "bank_details_title": "Bank details",
            "net_total_box": "Net Total",
            "tax_box": "Tax",
            "total_including_tax": "Total Including Tax",
            "agreement_title": "AGREEMENT",
            "date_field": "Date:",
            "signature": "Signature:",
            "name": "Name:",
            "role": "Role:",
            "company_stamp": "Company stamp",
            "signed_return": "After verifying that all the information on the quote is accurate, please return it signed to the following email address: adv@intrasense.fr",
            "validation_title": "Validation and payment conditions.",
            "terms_title": "Terms and conditions",
            "terms_left": (
                "The commercial conditions of the quote, including pricing information, are considered "
                "confidential information of the supplier.\n"
                "Any order is subject to the general terms and conditions of sale of Intrasense, attached "
                "to this purchase order, of which I accept all terms and conditions.\n"
                "*Provisional delivery date subject to change if necessary."
            ),
            "terms_right": (
                "Validation of the order by Intrasense, on receipt of the signed quotation and associated "
                "terms and conditions together with:\n"
                "- For subscription products and services, the payment of the 1st instalment\n"
                "- For asset products, a deposit of 100% of the receipt amount\n"
                "For subscription products and services:\n"
                "- Annual prepayment for the duration of the subscription, invoiced on the anniversary date "
                "of commissioning."
            ),
            "footer_note": "Quote generated automatically \u2014 Intrasense SA",
        }
    return {
        "quote": "DEVIS",
        "expiration": "Date d'expiration du devis :",
        "subject": "Objet :",
        "payment_conditions": "Conditions de paiement :",
        "delivery_conditions": "Conditions de livraison :",
        "engagement_duration": "Durée d'engagement :",
        "years_suffix": "an(s)",
        "section_subscription": "PRODUITS & SERVICES AVEC ABONNEMENT",
        "section_onetime": "PRESTATIONS DE SERVICE & PRODUITS À COÛT UNIQUE",
        "section_subscription_optional": "OPTIONS - PRODUITS & SERVICES AVEC ABONNEMENT",
        "section_onetime_optional": "OPTIONS - PRESTATIONS DE SERVICE & PRODUITS À COÛT UNIQUE",
        "rec_headers": ["Produit", "Description", "Qté", "Prix unitaire", "Remise", "Durée", "Coût annuel", "Coût total"],
        "one_headers": ["Produit", "Description", "Qté", "Prix unitaire", "Remise", "Total net"],
        "option_note": "Les lignes « Options » ne sont pas incluses dans le total ferme ci-dessous ; elles seront facturées séparément si le client les confirme.",
        "recap_title": "RÉCAPITULATIF PLURIANNUEL CLIENT",
        "recap_col_label": "Type de coût",
        "recap_row_onetime": "Coût unique HT",
        "recap_row_recurring": "Coût récurrent HT",
        "recap_row_total_ht": "Total HT",
        "recap_row_vat": "TVA",
        "recap_row_total_ttc": "Total TTC",
        "year_label": "Année",
        "net_total": "Total net (ferme, hors option)",
        "vat": "TVA",
        "total_incl_tax": "Total TTC",
        "bank_details_title": "Coordonnées bancaires",
        "net_total_box": "Total net",
        "tax_box": "TVA",
        "total_including_tax": "Total TTC",
        "agreement_title": "BON POUR ACCORD",
        "date_field": "Date :",
        "signature": "Signature :",
        "name": "Nom :",
        "role": "Fonction :",
        "company_stamp": "Cachet de l'entreprise",
        "signed_return": "Après vérification, merci de retourner ce devis signé à l'adresse suivante : adv@intrasense.fr",
        "validation_title": "Conditions de validation et de paiement.",
        "terms_title": "Conditions générales",
        "terms_left": (
            "Les conditions commerciales du devis, y compris les informations tarifaires, sont "
            "considérées comme confidentielles par le fournisseur.\n"
            "Toute commande est soumise aux conditions générales de vente d'Intrasense, jointes à ce "
            "bon de commande, dont le client accepte l'intégralité des termes.\n"
            "*Date de livraison prévisionnelle, sujette à modification si nécessaire."
        ),
        "terms_right": (
            "Validation de la commande par Intrasense, à réception du devis signé et des conditions "
            "associées, avec :\n"
            "- Pour les produits et services par abonnement : paiement de la 1ère échéance\n"
            "- Pour les produits matériels : acompte de 100% du montant à réception\n"
            "Pour les produits et services par abonnement :\n"
            "- Paiement annuel anticipé pour la durée de l'abonnement, facturé à la date anniversaire "
            "de la mise en service."
        ),
        "footer_note": "Devis généré automatiquement — Intrasense SA",
    }


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
    L = get_labels(langue)
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
        is_english = langue and langue.strip().lower().startswith("engl")
        if "numeric_mm5g2n38" in ccv and ccv["numeric_mm5g2n38"].get("text"):
            list_price = float(ccv["numeric_mm5g2n38"]["text"] or 0)
            duration = ccv.get("numeric_mm5gfh40", {}).get("text")
            duration = int(float(duration)) if duration else 1
            if is_english:
                description = ccv.get("long_text_mm5h9z7y", {}).get("text") or ccv.get("long_text_mm5afcad", {}).get("text") or ""
            else:
                description = ccv.get("long_text_mm5afcad", {}).get("text") or ""
            recurring = True
        else:
            list_price = float(ccv.get("numeric_mm5a9va0", {}).get("text") or 0)
            duration = 1
            if is_english:
                description = ccv.get("long_text_mm5hkzxt", {}).get("text") or ccv.get("long_text_mm5agwgw", {}).get("text") or ""
            else:
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
        years_recap.append({"label": f"{L['year_label']} {y}", "onetime": onetime_y, "recurring": annual_recurring,
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

        def draw_logo():
            logo_ax = fig.add_axes([0.06, 0.905, 0.30, 0.06])
            logo_ax.set_xlim(0, 10)
            logo_ax.set_ylim(0, 2)
            logo_ax.axis("off")
            logo_ax.text(0, 1, "intra", fontsize=22, weight="bold", color="#3a3d42", va="center", ha="left")
            circle = plt.Circle((4.6, 1), 1.15, color="#2a8fd6")
            logo_ax.add_patch(circle)
            logo_ax.text(4.6, 1, "sense", fontsize=15, weight="bold", color="white", va="center", ha="center")

        def new_page():
            nonlocal fig, y
            pdf.savefig(fig)
            plt.close(fig)
            fig = plt.figure(figsize=(8.27, 11.69))
            fig.patch.set_facecolor("white")
            y = 0.95

        draw_logo()
        bar(0.965, 0.03, f"{L['quote']}   {quote_number}", fontsize=11, x=0.60, w=0.34)
        fig.text(0.60, 0.925, f"{L['expiration']} {date_expiration}", fontsize=8)
        fig.text(0.60, 0.912, f"{L['subject']} {objet}", fontsize=8, weight="bold")

        y = 0.86
        fig.text(0.06, y, f"{L['language']} : {langue}   |   {L['vat_regime']} : {regime_tva}   |   {L['price_type']} : {type_prix}", fontsize=8.5)
        y -= 0.014
        fig.text(0.06, y, f"{L['payment_conditions']} {conditions_paiement}", fontsize=8.5)
        y -= 0.014
        fig.text(0.06, y, f"{L['delivery_conditions']} {conditions_livraison}", fontsize=8.5)
        y -= 0.014
        fig.text(0.06, y, f"{L['engagement_duration']} {duree_engagement} {L['years_suffix']}", fontsize=8.5)
        y -= 0.03

        PAGE_H_IN = 11.69
        LINE_H_IN = 0.155
        HEADER_H_IN = 0.24
        NAME_CHARS_PER_IN = 1 / 0.058   # regular 7.3pt text, with safety margin
        DESC_CHARS_PER_IN = 1 / 0.058

        def wrap(text, width_chars):
            return "\n".join(textwrap.wrap(text, width=max(6, width_chars))) or ""

        def draw_table(y_top, title, rows_wrapped, row_lines, headers, col_widths):
            bar(y_top, 0.022, title, fontsize=9)
            y_table_top = y_top - 0.022

            header_h_frac = HEADER_H_IN / PAGE_H_IN
            row_h_fracs = [(n * LINE_H_IN + 0.06) / PAGE_H_IN for n in row_lines]
            table_h_frac = header_h_frac + sum(row_h_fracs)
            bottom = y_table_top - table_h_frac

            ax = fig.add_axes([0.06, bottom, 0.88, table_h_frac])
            ax.axis("off")
            tbl = ax.table(cellText=rows_wrapped, colLabels=headers, cellLoc="left",
                            colWidths=col_widths, loc="center")
            tbl.auto_set_font_size(False)
            tbl.set_fontsize(7.3)

            all_row_fracs = [header_h_frac / table_h_frac] + [h / table_h_frac for h in row_h_fracs]
            for (r, c), cell in tbl.get_celld().items():
                cell.set_height(all_row_fracs[r])
                cell.set_edgecolor("#cccccc")
                cell.PAD = 0.03
                cell.set_text_props(va="center")
                if r == 0:
                    cell.set_facecolor(BLUE)
                    cell.set_text_props(color="white", weight="bold", va="center")
                else:
                    cell.set_facecolor("white")
            return bottom - 0.015

        # Column layout (fractions of the 0.88-wide table, i.e. ~6.4in usable):
        # money columns sized to comfortably fit "EUR 93 375,00" (~0.75in)
        rec_headers = L["rec_headers"]
        rec_widths = [0.15, 0.24, 0.03, 0.13, 0.085, 0.075, 0.145, 0.145]
        rec_name_chars = int(rec_widths[0] * 6.4 * NAME_CHARS_PER_IN * 0.92)
        rec_desc_chars = int(rec_widths[1] * 6.4 * DESC_CHARS_PER_IN * 0.92)

        one_headers = L["one_headers"]
        one_widths = [0.20, 0.36, 0.04, 0.15, 0.10, 0.15]
        one_name_chars = int(one_widths[0] * 6.4 * NAME_CHARS_PER_IN * 0.92)
        one_desc_chars = int(one_widths[1] * 6.4 * DESC_CHARS_PER_IN * 0.92)

        def recurring_rows(ls):
            rows, lines = [], []
            for l in ls:
                disc = f"{l['disc_pct']}%" if l["disc_pct"] else ("-" if not l["disc_val"] else money(l["disc_val"]))
                total_engagement = l["net_total"] * l["duration"]
                name_w = wrap(l["name"], rec_name_chars)
                desc_w = wrap(l["description"], rec_desc_chars)
                row = [name_w, desc_w, str(int(l["qty"])), money(l["list_price"]),
                       disc, f"{l['duration']} {L['years_suffix']}", money(l["net_total"]), money(total_engagement)]
                rows.append(row)
                lines.append(max(cell.count("\n") + 1 for cell in row))
            return rows, lines

        def onetime_rows(ls):
            rows, lines = [], []
            for l in ls:
                disc = f"{l['disc_pct']}%" if l["disc_pct"] else ("-" if not l["disc_val"] else money(l["disc_val"]))
                name_w = wrap(l["name"], one_name_chars)
                desc_w = wrap(l["description"], one_desc_chars)
                row = [name_w, desc_w, str(int(l["qty"])), money(l["list_price"]), disc, money(l["net_total"])]
                rows.append(row)
                lines.append(max(cell.count("\n") + 1 for cell in row))
            return rows, lines

        if firm_recurring:
            tbl_rows, tbl_lines = recurring_rows(firm_recurring)
            y = draw_table(y, L["section_subscription"], tbl_rows, tbl_lines, rec_headers, rec_widths)
        if firm_onetime:
            tbl_rows, tbl_lines = onetime_rows(firm_onetime)
            y = draw_table(y, L["section_onetime"], tbl_rows, tbl_lines, one_headers, one_widths)
        if opt_recurring:
            tbl_rows, tbl_lines = recurring_rows(opt_recurring)
            y = draw_table(y, L["section_subscription_optional"], tbl_rows, tbl_lines, rec_headers, rec_widths)
        if opt_onetime:
            tbl_rows, tbl_lines = onetime_rows(opt_onetime)
            y = draw_table(y, L["section_onetime_optional"], tbl_rows, tbl_lines, one_headers, one_widths)

        if opt_recurring or opt_onetime:
            fig.text(0.06, y, L["option_note"], fontsize=7.5, style="italic")
            y -= 0.02

        recap_headers = [L["recap_col_label"]] + [yr["label"] for yr in years_recap]
        recap_rows = [
            [L["recap_row_onetime"]] + [money(yr["onetime"]) for yr in years_recap],
            [L["recap_row_recurring"]] + [money(yr["recurring"]) for yr in years_recap],
            [L["recap_row_total_ht"]] + [money(yr["total_ht"]) for yr in years_recap],
            [f"{L['recap_row_vat']} ({int(vat_rate*100)}%)"] + [money(yr["vat"]) for yr in years_recap],
            [L["recap_row_total_ttc"]] + [money(yr["total_ttc"]) for yr in years_recap],
        ]
        recap_widths = [0.22] + [0.78 / len(years_recap)] * len(years_recap)
        recap_lines = [1] * len(recap_rows)
        y = draw_table(y, L["recap_title"], recap_rows, recap_lines, recap_headers, recap_widths)

        y -= 0.015
        fig.text(0.06, y, f"{L['net_total']} : {money(net_ferme)}", fontsize=9, weight="bold")
        y -= 0.016
        fig.text(0.06, y, f"{L['vat']} ({int(vat_rate*100)}%) : {money(vat_ferme)}", fontsize=9)
        y -= 0.016
        fig.text(0.06, y, f"{L['total_incl_tax']} : {money(ttc_ferme)}", fontsize=10, weight="bold", color=BLUE)
        y -= 0.03

        # ---------- Bottom sections: bank details, agreement, terms, footer ----------
        # Estimate needed space; break to a new page if it won't fit
        if y < 0.34:
            new_page()

        # Bank details (left) + Net/Tax/Total boxes (right)
        bank_top = y
        bar(bank_top, 0.02, L["bank_details_title"], fontsize=8, x=0.06, w=0.42)
        by = bank_top - 0.02 - 0.014
        for line in BANK_DETAILS:
            fig.text(0.07, by, line, fontsize=7.8)
            by -= 0.014

        box_w, box_h, gap = 0.20, 0.022, 0.01
        rx = 0.52
        bar(bank_top, box_h, L["net_total_box"], fontsize=7.5, x=rx, w=box_w)
        bar(bank_top, box_h, L["tax_box"], fontsize=7.5, x=rx + box_w + gap, w=box_w)
        fig.text(rx + 0.01, bank_top - box_h - 0.013, money(net_ferme), fontsize=8)
        fig.text(rx + box_w + gap + 0.01, bank_top - box_h - 0.013, money(vat_ferme), fontsize=8)

        total_box_y = bank_top - box_h - 0.032
        fig.patches.append(plt.Rectangle((rx, total_box_y - box_h), box_w, box_h, transform=fig.transFigure,
                                          facecolor="white", edgecolor=ORANGE, linewidth=1.4))
        fig.text(rx + 0.01, total_box_y - box_h / 2, L["total_including_tax"], fontsize=7.5, weight="bold", va="center")
        fig.patches.append(plt.Rectangle((rx + box_w + gap, total_box_y - box_h), box_w, box_h, transform=fig.transFigure,
                                          facecolor="white", edgecolor=ORANGE, linewidth=1.4))
        fig.text(rx + box_w + gap + 0.01, total_box_y - box_h / 2, money(ttc_ferme), fontsize=8, weight="bold", va="center")

        y = min(by, total_box_y - box_h) - 0.03

        if y < 0.22:
            new_page()

        # Agreement block
        agr_top = y
        bar(agr_top, 0.018, L["agreement_title"], fontsize=8)
        rows_agr = [L["date_field"], L["signature"], L["name"], L["role"]]
        ay = agr_top - 0.018
        row_h = 0.021
        for label in rows_agr:
            fig.patches.append(plt.Rectangle((0.06, ay - row_h), 0.42, row_h, transform=fig.transFigure,
                                              facecolor="white", edgecolor="#999999", linewidth=0.6))
            fig.text(0.07, ay - row_h / 2, label, fontsize=7.5, va="center")
            ay -= row_h
        stamp_h = row_h * len(rows_agr)
        fig.patches.append(plt.Rectangle((0.52, agr_top - 0.018 - stamp_h), 0.42, stamp_h, transform=fig.transFigure,
                                          facecolor="white", edgecolor="#999999", linewidth=0.6))
        fig.text(0.53, agr_top - 0.018 - 0.012, L["company_stamp"], fontsize=7.5)

        y = ay - 0.018
        fig.text(0.06, y, L["signed_return"], fontsize=7.3)
        y -= 0.03

        if y < 0.16:
            new_page()

        # Validation / terms conditions (two columns)
        cond_top = y
        left_txt = "\n".join(textwrap.wrap(L["terms_left"], width=62))
        right_txt = "\n".join(textwrap.wrap(L["terms_right"], width=62))
        fig.text(0.06, cond_top, L["validation_title"], fontsize=7.6, weight="bold")
        fig.text(0.52, cond_top, L["terms_title"], fontsize=7.6, weight="bold")
        fig.text(0.06, cond_top - 0.018, left_txt, fontsize=6.8, va="top")
        fig.text(0.52, cond_top - 0.018, right_txt, fontsize=6.8, va="top")

        n_left_lines = left_txt.count("\n") + 1
        n_right_lines = right_txt.count("\n") + 1
        y = cond_top - 0.018 - max(n_left_lines, n_right_lines) * 0.012 - 0.02

        fig.text(0.5, max(y, 0.05), FOOTER_LEGAL, fontsize=6.3, color="#888888", ha="center", va="top")

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
