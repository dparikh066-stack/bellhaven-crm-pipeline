"""Generates the flow diagrams used in the PDF/PPTX deliverables."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.path import Path
import os

GREEN = "#2E5D50"
GOLD = "#C9A227"
CREAM = "#FAF7F0"
INK = "#2B2B26"
RED = "#a33"
PURPLE = "#8a4b9e"
BLUE = "#1c6fb0"

OUT_DIR = os.path.join(os.path.dirname(__file__), "diagrams")
os.makedirs(OUT_DIR, exist_ok=True)


def box(ax, xy, w, h, text, color=GREEN, textcolor="white", fontsize=11, diamond=False, style="round"):
    x, y = xy
    if diamond:
        pts = [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2), (x + w / 2, y)]
        ax.add_patch(plt.Polygon(pts, closed=True, facecolor=color, edgecolor=INK, linewidth=1.2, zorder=2))
    else:
        ax.add_patch(FancyBboxPatch(
            (x, y), w, h, boxstyle=f"{style},pad=0.02,rounding_size=0.06" if style == "round" else "square,pad=0.02",
            facecolor=color, edgecolor=INK, linewidth=1.2, zorder=2,
        ))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", color=textcolor,
             fontsize=fontsize, zorder=3, wrap=True, fontweight="medium")


def arrow(ax, start, end, label=None, color=INK, style="-|>", curve=0.0, fontsize=9, label_color=INK):
    a = FancyArrowPatch(start, end, arrowstyle=style, mutation_scale=14, color=color,
                         linewidth=1.4, zorder=1, connectionstyle=f"arc3,rad={curve}")
    ax.add_patch(a)
    if label:
        mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
        ax.text(mx, my + 0.15, label, ha="center", va="bottom", fontsize=fontsize, color=label_color, zorder=4)


def new_fig(w, h):
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.axis("off")
    fig.patch.set_facecolor("white")
    return fig, ax


# ---------------------------------------------------------------------------
# Diagram 1: end-to-end pipeline architecture
# ---------------------------------------------------------------------------
fig, ax = new_fig(13, 7.2)

box(ax, (0.4, 5.4), 2.6, 1.1, "Bellhaven\nwebsite", color=GOLD, textcolor=INK)
box(ax, (0.4, 3.2), 2.6, 1.1, "Bellhaven\nCRM API", color=GOLD, textcolor=INK)

box(ax, (3.6, 5.4), 2.6, 1.1, "scraper.py")
box(ax, (3.6, 3.2), 2.6, 1.1, "crm_client.py")

box(ax, (6.8, 4.3), 2.6, 1.1, "matcher.py\n(pure function)", color=GREEN)

box(ax, (10.0, 4.3), 2.6, 1.1, "proposals\n(in memory)", color=GREEN)

box(ax, (10.0, 2.2), 2.6, 1.1, "store.py\nSQLite ledger", color="#555")

box(ax, (6.8, 0.4), 2.6, 1.1, "review_app\n(Flask, localhost)", color=BLUE)

box(ax, (3.6, 0.4), 2.6, 1.1, "human reviewer\napprove / reject", color=PURPLE)

box(ax, (0.4, 0.4), 2.6, 1.1, "apply.py", color=RED)

arrow(ax, (3.0, 5.95), (3.6, 5.95))
arrow(ax, (3.0, 3.75), (3.6, 3.75))
arrow(ax, (6.2, 5.95), (6.8, 5.15), curve=-0.15)
arrow(ax, (6.2, 3.75), (6.8, 4.75), curve=0.15)
arrow(ax, (9.4, 4.85), (10.0, 4.85), label="upsert by\ndedupe_key")
arrow(ax, (11.3, 4.3), (11.3, 3.3))
arrow(ax, (10.0, 2.75), (9.4, 0.95), label="pending\nproposals", curve=-0.2)
arrow(ax, (6.8, 0.95), (6.2, 0.95), label="evidence")
arrow(ax, (3.6, 0.95), (3.0, 0.95), label="approve")
arrow(ax, (1.7, 1.5), (1.7, 3.2), label="writes via\nCRM API", curve=0.3)

ax.text(6.5, 6.9, "Bellhaven CRM Pipeline -- End-to-End Flow", ha="center", fontsize=16, fontweight="bold", color=INK)
ax.text(6.5, 6.55, "Nothing reaches the CRM until a human clicks Approve.", ha="center", fontsize=10.5, color="#666", style="italic")

fig.tight_layout()
fig.savefig(os.path.join(OUT_DIR, "architecture.png"), facecolor="white")
plt.close(fig)


# ---------------------------------------------------------------------------
# Diagram 2: matching / classification decision tree
# ---------------------------------------------------------------------------
fig, ax = new_fig(13, 9.2)

box(ax, (5.1, 7.5), 2.8, 0.9, "For each scraped\nlocation...", color=GOLD, textcolor=INK)
box(ax, (4.6, 6.0), 3.8, 1.0, "Any CRM account\naddress- or identity-\nconfirmed?", diamond=True, color="#eee", textcolor=INK, fontsize=9.5)

box(ax, (0.2, 4.5), 2.6, 1.0, "No match at all", color="#ccc", textcolor=INK)
box(ax, (0.2, 3.1), 2.6, 1.0, "New location\n-> create account", color=BLUE)

box(ax, (9.6, 4.5), 3.2, 1.0, "2+ matches, none already\ncorrect Bellhaven record", color="#ccc", textcolor=INK, fontsize=9.5)
box(ax, (9.6, 3.1), 3.2, 1.0, "Ambiguous\n-> propose every candidate,\nhuman picks one", color=PURPLE, fontsize=9.5)

box(ax, (4.4, 4.5), 4.0, 1.0, "Exactly one confirmed\naccount", color="#ccc", textcolor=INK)
box(ax, (3.0, 3.1), 2.6, 1.0, "Already Bellhaven +\nname matches", color="#ccc", textcolor=INK, fontsize=9.5)
box(ax, (3.0, 1.7), 2.6, 1.0, "Confident match\n(sync any field drift)", color=GREEN)

box(ax, (6.2, 3.1), 2.6, 1.0, "Wrong parent\nand/or name", color="#ccc", textcolor=INK, fontsize=9.5)
box(ax, (6.2, 1.7), 2.6, 1.0, "Needs fix\n(see CHOW diagram)", color=GOLD, textcolor=INK)

box(ax, (0.2, 0.2), 6.6, 1.0, "Any other CRM account at the same address\n-> duplicate check (has rev+AR? flag for review : mark duplicate + Inactive)", color=RED, fontsize=9)
box(ax, (7.2, 0.2), 5.6, 1.0, "Bellhaven-parented account no location claims\n-> orphan -> status Needs Review + note (never auto-Inactive)", color=RED, fontsize=9)

arrow(ax, (6.5, 7.5), (6.5, 7.0))
arrow(ax, (4.6, 6.3), (1.5, 5.5), label="no")
arrow(ax, (1.5, 4.5), (1.5, 4.1))
arrow(ax, (6.5, 6.0), (6.4, 5.5), label="exactly one")
arrow(ax, (8.4, 6.3), (11.2, 5.5), label="multiple")
arrow(ax, (11.2, 4.5), (11.2, 4.1))
arrow(ax, (5.5, 4.5), (4.3, 4.1), label="parent+name OK")
arrow(ax, (7.4, 4.5), (7.5, 4.1), label="parent/name wrong")
arrow(ax, (4.3, 3.1), (4.3, 2.7))
arrow(ax, (7.5, 3.1), (7.5, 2.7))

ax.text(6.5, 8.95, "Matching & Classification Logic", ha="center", fontsize=16, fontweight="bold", color=INK)

fig.tight_layout()
fig.savefig(os.path.join(OUT_DIR, "classification.png"), facecolor="white")
plt.close(fig)


# ---------------------------------------------------------------------------
# Diagram 3: CHOW SOP
# ---------------------------------------------------------------------------
fig, ax = new_fig(12, 7.2)

box(ax, (0.5, 5.2), 3.2, 1.1, "Account needs to move\nto a different parent", color=GOLD, textcolor=INK)
box(ax, (4.4, 4.9), 4.0, 1.5, "lifetime_revenue > 0\nAND\noutstanding_ar > 0 ?", diamond=True, color="#eee", textcolor=INK, fontsize=10.5)

box(ax, (8.9, 5.25), 2.6, 0.8, "NO", color="#ccc", textcolor=INK, fontsize=11)
box(ax, (4.4, 1.3), 3.2, 0.8, "YES", color="#ccc", textcolor=INK, fontsize=11)

box(ax, (7.7, 2.0), 4.0, 2.0,
    "Re-parent the EXISTING\naccount directly.\n\nNo new record created.",
    color=GREEN, fontsize=11)
box(ax, (0.0, 0.3), 4.2, 3.4,
    "Leave the OLD account\nexactly as it is.\n\nCreate a NEW account\nunder the correct parent.\n\nSet chow_current_account\non the OLD account\n-> new account's id.",
    color=RED, fontsize=10)

arrow(ax, (3.7, 5.75), (4.4, 5.65))
arrow(ax, (8.4, 5.9), (8.9, 5.65), label="no")
arrow(ax, (6.4, 4.9), (5.7, 2.1), label="yes")
arrow(ax, (9.9, 5.25), (9.7, 4.0))
arrow(ax, (5.6, 1.3), (3.2, 3.7), curve=-0.15)

ax.text(6, 6.95, "CHOW (Change of Ownership) SOP", ha="center", fontsize=16, fontweight="bold", color=INK)
ax.text(6, 6.62, "Checked before EVERY re-parent proposal, and before marking any duplicate Inactive",
        ha="center", fontsize=9.5, color="#666", style="italic")

fig.tight_layout()
fig.savefig(os.path.join(OUT_DIR, "chow_sop.png"), facecolor="white")
plt.close(fig)

print("Diagrams written to", OUT_DIR)
