"""Compare plusieurs mesures explain (report/explain/<label>/summary.json).

  python -m queries.compare_explain before after after-extra
  python -m queries.compare_explain before after after-extra --out report/data/explain_comparison.md

Le gain est calculé par rapport au premier label (référence). Aucune connexion
MongoDB n'est nécessaire : seuls les fichiers summary.json sont lus.
"""

import argparse
import json
import os


def load(label, base):
    with open(os.path.join(base, label, "summary.json"), encoding="utf-8") as f:
        return json.load(f)


def fmt_ms(v):
    return "—" if v is None else f"{v:,.0f}".replace(",", " ")


def gain(ref, v):
    if ref is None or v is None:
        return ""
    if ref < 20 and v < 20:
        return "≈"            # quelques ms : écart non significatif (bruit de mesure)
    if v == 0:
        return f"×{ref:,.0f}+".replace(",", " ") if ref else "="
    r = ref / v
    if 0.9 <= r <= 1.1:
        return "≈"
    return f"×{r:.1f}" if r >= 1 else f"**÷{1 / r:.1f}**"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("labels", nargs="+", help="labels à comparer, le premier sert de référence")
    p.add_argument("--base", default="report/explain")
    p.add_argument("--out", help="fichier Markdown de sortie (sinon affichage)")
    args = p.parse_args()

    runs = [load(lbl, args.base) for lbl in args.labels]
    ref = runs[0]
    queries = list(ref["queries"])

    lines = [f"Référence temporelle : {ref['reference_time']} — "
             f"{ref['counts']['telemetry']:,} documents".replace(",", " "), ""]
    header = "| Requête | " + " | ".join(
        f"{r['label']} (ms)" + ("" if i == 0 else " | gain") for i, r in enumerate(runs)
    ) + " | Docs examinés (" + " → ".join(r["label"] for r in runs) + ") | Étapes (dernier) |"
    sep = "|" + "---|" * (1 + 1 + 2 * (len(runs) - 1) + 2)
    lines += [header, sep]

    for q in queries:
        ref_ms = ref["queries"][q].get("executionTimeMillis")
        cells = [q, fmt_ms(ref_ms)]
        for r in runs[1:]:
            v = r["queries"].get(q, {}).get("executionTimeMillis")
            cells += [fmt_ms(v), gain(ref_ms, v)]
        docs = " → ".join(
            f"{r['queries'].get(q, {}).get('totalDocsExamined', '—'):,}".replace(",", " ")
            if isinstance(r["queries"].get(q, {}).get("totalDocsExamined"), int) else "—"
            for r in runs)
        stages = ",".join(runs[-1]["queries"].get(q, {}).get("stages", []))
        cells += [docs, stages]
        lines.append("| " + " | ".join(cells) + " |")

    lines += ["", "Index présents :"]
    for r in runs:
        lines.append(f"- **{r['label']}** : {', '.join(r['indexes']['telemetry'])}")
    text = "\n".join(lines) + "\n"

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Tableau écrit : {args.out}")
    print(text)


if __name__ == "__main__":
    main()
