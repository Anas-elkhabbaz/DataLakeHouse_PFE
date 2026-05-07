"""Phase 2 : Inspection des en-têtes CSV pour valider les positions $N."""
import csv
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
FILES = ["issues.csv", "comments.csv", "changelog.csv", "issuelinks.csv"]

NEEDED = {
    "issues.csv": [
        "id", "key", "summary", "description", "created", "resolutiondate",
        "issuetype.name", "resolution.name", "resolution.description",
        "priority.name", "status.name", "project.key",
        "assignee", "reporter", "creator", "votes.votes", "watches.watchCount",
    ],
    "comments.csv": [
        "key", "comment.id", "comment.author", "comment.body",
        "comment.created", "comment.updated",
    ],
    "changelog.csv": [
        "key", "author", "created", "field", "fromString", "toString",
    ],
    "issuelinks.csv": [
        "key", "type.name", "inwardIssue.key", "outwardIssue.key",
    ],
}

for fname in FILES:
    path = DATA_DIR / fname
    with open(path, encoding="utf-8", newline="") as f:
        headers = next(csv.reader(f))

    print(f"\n{'='*60}")
    print(f"  {fname}  ({len(headers)} colonnes)")
    print(f"{'='*60}")
    needed = NEEDED.get(fname, [])
    for i, col in enumerate(headers, 1):
        marker = " <--" if col in needed else ""
        print(f"  ${i:>2}  {col}{marker}")

    print(f"\n  Colonnes nécessaires et leurs positions :")
    for col in needed:
        if col in headers:
            pos = headers.index(col) + 1
            print(f"    ${pos:>2}  {col}")
        else:
            print(f"    ???  {col}  [INTROUVABLE]")
