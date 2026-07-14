"""Deterministic seeded month for a coherent 14-room inn (SEED_DATA.md).

30 nights x 40-60 transactions across three systems, with planted,
ground-truth-labeled discrepancy archetypes:

  A1 OTA commission skim   — 3% at source on every OTA folio (nightly)
  A2 rolling reserve       — processor holds 5% for 7 days (timing; self-heals)
  A3 FX rounding           — EUR-card guests, +/- $0.02-0.40 (noise class)
  A4 duplicate capture     — same auth captured twice on night 11 (HIGH)
  A5 unposted walk-in      — TRUE ERROR: room sold at the card terminal but
                             never posted in the PMS (nights 04 and 17).
                             Auto-clearing either one = invariant I1 failure.

plus the three PDF hazards (pdfgen.py) and tier-2/tier-3 matcher exercise rows
(settlements with dropped or typo'd folio refs that must still pair cleanly).

Everything derives from random.Random(f"{SEED}:{night}") — `--regen`
reproduces byte-identical fixtures (asserted by test + manifest hashes).

Night 2026-07-04 is hand-engineered so the demo ordering is stable:
mismatch #7 = the $189.00/$183.33 OTA commission (auto-clears with a bbox
citation), mismatch #12 = the $310 no-folio walk-in (queues at 0.6/0.4).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from . import __version__
from .amounts import pct_of, to_dollars
from .config import MONTH, NIGHTS, SEED, Paths, night_str
from .crypto import ensure_demo_keys, seal_bytes
from .pdfgen import render_statement
from .store import file_sha256, write_json

ROOMS: list[tuple[str, int]] = [
    ("101", 129_00), ("102", 129_00), ("103", 139_00), ("104", 139_00),
    ("105", 149_00), ("106", 149_00), ("107", 155_00), ("201", 155_00),
    ("202", 179_00), ("203", 179_00), ("204", 189_00), ("205", 210_00),
    ("206", 240_00), ("207", 310_00),
]
RATE = dict(ROOMS)
RATE_GRID = sorted({r for _, r in ROOMS})

GUESTS = [
    "M. Okafor", "L. Fernandez", "T. Nguyen", "S. Whitfield", "A. Braun",
    "K. Tanaka", "R. Dubois", "P. Lindqvist", "J. Carver", "N. Adeyemi",
    "E. Rossi", "H. Almeida", "C. Novak", "D. Petrov", "F. Laurent",
    "G. Santos", "I. Kowalski", "B. Hansen", "O. Virtanen", "V. Marino",
    "W. Schmidt", "Y. Chen", "Z. Haddad", "Q. Baptiste", "U. Eriksen",
]
EXTRA_DESCS = ["dinner", "bar", "breakfast", "parking", "spa", "laundry", "minibar", "room svc"]

OTA_COMMISSION_PCT = 3
RESERVE_PCT = 5
RESERVE_DAYS = 7
FOOTNOTE_ADJ_CENTS = 12_00
WALKIN_NIGHTS = {4: 310_00, 17: 155_00}  # night day -> amount (both in the rate grid)
DUP_NIGHT = 11
FOOTNOTE_NIGHT = 9
PAGEBREAK_NIGHT = 21


@dataclass
class _State:
    folio_seq: int = 1000
    stl_seq: int = 1
    ota_line_no: int = 0
    pending_releases: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    ground_truth: list[dict[str, Any]] = field(default_factory=list)
    ota_lines: list[dict[str, Any]] = field(default_factory=list)

    def next_folio(self) -> str:
        self.folio_seq += 1
        return f"folio-{self.folio_seq}"

    def next_stl(self) -> str:
        s = f"stl-{self.stl_seq:05d}"
        self.stl_seq += 1
        return s


def _label(st: _State, night: str, anchor: str, cls: str, subtype: str,
           severity: str, action: str, note: str = "") -> None:
    st.ground_truth.append(
        {"night": night, "anchor_ref": anchor, "class": cls, "subtype": subtype,
         "severity": severity, "expected_action": action, "note": note}
    )


# --------------------------------------------------------------------------- #
# per-night builders
# --------------------------------------------------------------------------- #


def _stay_plan(rng: random.Random, day: int) -> list[dict[str, Any]]:
    """Random plan for one night: which rooms, channel, method, archetypes."""
    if day in WALKIN_NIGHTS:
        # keep the walk-in amount un-T2-matchable: its rate's rooms stay
        # either vacant or card-paid (never an unmatched cash row).
        forbidden_cash = {room for room, rate in ROOMS if rate == WALKIN_NIGHTS[day]}
    else:
        forbidden_cash = set()
    k = rng.randint(11, 14)
    rooms = sorted(rng.sample([r for r, _ in ROOMS], k))
    if day == FOOTNOTE_NIGHT and "201" not in rooms:
        rooms = sorted(rooms[:-1] + ["201"])
    if day == DUP_NIGHT and "203" not in rooms:
        rooms = sorted(rooms[:-1] + ["203"])
    n_ota = rng.randint(3, min(6, len(rooms) - 4))
    ota_rooms = set(rng.sample([r for r in rooms if r != "203" or day != DUP_NIGHT], n_ota))
    if day == FOOTNOTE_NIGHT:
        ota_rooms.add("201")
    direct = [r for r in rooms if r not in ota_rooms]
    cash_rooms = {
        r for r in direct
        if r not in forbidden_cash and (day != DUP_NIGHT or r != "203") and rng.random() < 0.12
    }
    card_direct = [r for r in direct if r not in cash_rooms]
    n_fx = min(rng.randint(0, 3), max(0, len(card_direct) - 2))
    fx_rooms = set(rng.sample(card_direct, n_fx))
    rest = [r for r in card_direct if r not in fx_rooms and (day != DUP_NIGHT or r != "203")]
    n_res = min(rng.randint(1, 3), len(rest))
    res_rooms = set(rng.sample(rest, n_res))
    plan = []
    for room in rooms:
        plan.append(
            {"room": room, "rate": RATE[room], "guest": rng.choice(GUESTS),
             "channel": "ota" if room in ota_rooms else "direct",
             "method": ("ota_collect" if room in ota_rooms
                        else "cash" if room in cash_rooms else "card"),
             "fx": room in fx_rooms, "reserve": room in res_rooms}
        )
    return plan


def _stay_plan_night4(rng: random.Random) -> list[dict[str, Any]]:
    """Hand-engineered demo night: exactly 12 mismatches whose materiality
    ordering pins #7 = the $189 OTA commission and #12 = the $310 walk-in."""
    spec = [
        # OTA commissions: deltas 387 / 417 / 567(#7) / 630 cents
        ("101", "ota"), ("103", "ota"), ("204", "ota"), ("205", "ota"),
        # FX roundings: deltas planted below as 4 / 11 / 23 / 31 cents
        ("105", "fx"), ("106", "fx"), ("202", "fx"), ("107", "fx"),
        # rolling reserve 5%: deltas 645 / 775 / 895 cents
        ("102", "res"), ("201", "res"), ("203", "res"),
        # one clean direct card room; 104 + 207 vacant (207's $310 rate is
        # exactly what makes the walk-in hypothesis computable)
        ("206", "clean"),
    ]
    plan = []
    for room, kind in spec:
        plan.append(
            {"room": room, "rate": RATE[room], "guest": rng.choice(GUESTS),
             "channel": "ota" if kind == "ota" else "direct",
             "method": "ota_collect" if kind == "ota" else "card",
             "fx": kind == "fx", "reserve": kind == "res"}
        )
    return plan


NIGHT4_FX_DELTAS = {"105": 4, "106": -11, "202": 23, "107": -31}


def _build_night(st: _State, month: str, day: int, nights_total: int) -> tuple[list[dict], list[dict]]:
    night = night_str(month, day)
    rng = random.Random(f"{SEED}:{night}")
    engineered = day == 4
    plan = _stay_plan_night4(rng) if engineered else _stay_plan(rng, day)

    pms: list[dict[str, Any]] = []
    proc: list[dict[str, Any]] = list(st.pending_releases.pop(day, []))
    for row in proc:  # releases planted earlier: label on THIS night
        _label(st, night, row["ref"], "timing", "reserve_release", "low", "auto_clear",
               row["memo"])
    batch = f"b{day:02d}42"
    row_no = len(proc)

    # --- room folios ------------------------------------------------------- #
    for stay in plan:
        ref = st.next_folio()
        stay["ref"] = ref
        memo = "EUR card" if stay["fx"] else ""
        pms.append(
            {"src": "pms", "ref": ref, "folio": ref, "amount_cents": stay["rate"],
             "date": night, "method": "card" if stay["method"] == "card" else stay["method"],
             "kind": "sale", "memo": memo,
             "raw": {"room": stay["room"], "guest": stay["guest"], "channel": stay["channel"]}}
        )
        if stay["channel"] == "ota":
            st.ota_line_no += 1
            gross = stay["rate"]
            comm = pct_of(gross, OTA_COMMISSION_PCT, 100)
            adj = FOOTNOTE_ADJ_CENTS if (day == FOOTNOTE_NIGHT and stay["room"] == "201") else 0
            payout = gross - comm - adj
            hazard = None
            if day == PAGEBREAK_NIGHT and not any(
                l["hazard"] == "page_broken" for l in st.ota_lines
            ):
                hazard = "page_broken"
            line = {
                "line_no": st.ota_line_no, "night": night, "folio": ref,
                "guest": stay["guest"], "room": stay["room"],
                "gross": to_dollars(gross), "commission": to_dollars(comm),
                "payout": to_dollars(payout),
                "footnote_adjustment": to_dollars(adj) if adj else 0.0,
                "hazard": hazard,
            }
            if hazard:
                # pass-B misjoins the split row -> planted two-pass disagreement
                line["pass_b_payout"] = to_dollars(payout - 60_00)
                _label(st, night, ref, "fee", "ota_commission", "medium", "queue",
                       "two_pass_disagreement on page-broken row (I5)")
            elif adj:
                _label(st, night, ref, "fee", "promo_cofunding", "low", "auto_clear",
                       "3% commission + $12.00 promo co-funding footnote")
            else:
                _label(st, night, ref, "fee", "ota_commission", "low", "auto_clear",
                       f"3% commission on {to_dollars(gross):.2f}")
            st.ota_lines.append(line)
        elif stay["method"] == "card":
            settle = stay["rate"]
            memo_p, kind_cls = "", None
            if stay["fx"]:
                delta = (NIGHT4_FX_DELTAS[stay["room"]] if engineered
                         else rng.choice([-1, 1]) * rng.randint(2, 40))
                settle = stay["rate"] - delta
                memo_p = "FX conversion EUR->USD"
                kind_cls = ("fx", "fx_rounding")
            elif stay["reserve"]:
                held = pct_of(stay["rate"], RESERVE_PCT, 100)
                settle = stay["rate"] - held
                release_day = day + RESERVE_DAYS
                release_date = night_str(month, release_day) if release_day <= nights_total else "next-month"
                memo_p = f"rolling reserve {RESERVE_PCT}% held (release {release_date})"
                kind_cls = ("timing", "rolling_reserve")
                if release_day <= nights_total:
                    rref = st.next_stl()
                    st.pending_releases.setdefault(release_day, []).append(
                        {"src": "processor", "ref": rref, "folio": None,
                         "amount_cents": held, "date": night_str(month, release_day),
                         "method": "card", "kind": "reserve_release",
                         "memo": f"reserve release for {ref} (held {night})",
                         "raw": {"batch": f"b{release_day:02d}42", "row": 0,
                                 "auth": f"auth-{rng.randrange(16**6):06x}"}}
                    )
            row_no += 1
            proc.append(
                {"src": "processor", "ref": st.next_stl(), "folio": ref,
                 "amount_cents": settle, "date": night, "method": "card", "kind": "sale",
                 "currency": "EUR" if stay["fx"] else "USD", "memo": memo_p,
                 "raw": {"batch": batch, "row": row_no,
                         "auth": f"auth-{rng.randrange(16**6):06x}"}}
            )
            if kind_cls:
                _label(st, night, ref, kind_cls[0], kind_cls[1], "low", "auto_clear", memo_p)
            if day == DUP_NIGHT and stay["room"] == "203":
                dup_ref = st.next_stl()
                row_no += 1
                proc.append(
                    {**proc[-1], "ref": dup_ref,
                     "raw": {**proc[-1]["raw"], "row": row_no, "auth": proc[-1]["raw"]["auth"]},
                     "memo": "second capture of same auth"}
                )
                _label(st, night, dup_ref, "duplicate", "duplicate_capture", "high",
                       "queue", "same auth captured twice")

    # --- extras (F&B etc.) -------------------------------------------------- #
    n_extras = 9 if engineered else rng.randint(8, 12)
    amounts = rng.sample(range(9, 66), n_extras)
    room_folios = [s["ref"] for s in plan]
    mangle_slots: dict[int, str] = {}
    if not engineered:
        mangle_slots[0] = "drop_ref"  # tier-2 exercise: folio ref lost in batch import
        if day % 3 == 0 and n_extras > 1:
            mangle_slots[1] = "typo"  # tier-3 exercise: one-char folio typo
    for i, amt in enumerate(amounts):
        folio = rng.choice(room_folios)
        ref = f"{folio}-E{i + 1}"
        cash = (not engineered) and i not in mangle_slots and rng.random() < 0.10
        pms.append(
            {"src": "pms", "ref": ref, "folio": folio, "amount_cents": amt * 100,
             "date": night, "method": "cash" if cash else "card", "kind": "extra",
             "memo": rng.choice(EXTRA_DESCS), "raw": {}}
        )
        if cash:
            continue
        row_no += 1
        mangle = mangle_slots.get(i)
        proc_folio = None if mangle == "drop_ref" else (ref[:-2] + "_E" + ref[-1] if mangle == "typo" else ref)
        proc.append(
            {"src": "processor", "ref": st.next_stl(), "folio": proc_folio,
             "amount_cents": amt * 100, "date": night, "method": "card", "kind": "sale",
             "memo": "ref missing — batch import" if mangle == "drop_ref" else "",
             "raw": {"batch": batch, "row": row_no,
                     "auth": f"auth-{rng.randrange(16**6):06x}"}}
        )

    # --- planted TRUE ERROR: unposted walk-in (A5) --------------------------- #
    if day in WALKIN_NIGHTS:
        ref = st.next_stl() if day != 4 else "stl-e0777"
        row_no += 1
        proc.append(
            {"src": "processor", "ref": ref, "folio": None,
             "amount_cents": WALKIN_NIGHTS[day], "date": night, "method": "card",
             "kind": "sale", "memo": "keyed terminal capture 22:41",
             "raw": {"batch": batch, "row": row_no,
                     "auth": f"auth-{rng.randrange(16**6):06x}"}}
        )
        _label(st, night, ref, "true_error", "unposted_walkin", "high", "queue",
               "card terminal capture with no PMS folio")

    pms.sort(key=lambda t: t["ref"])
    proc.sort(key=lambda t: t["ref"])
    return pms, proc


# --------------------------------------------------------------------------- #
# month orchestrator
# --------------------------------------------------------------------------- #


def generate_month(paths: Paths, nights: int = NIGHTS, month: str = MONTH) -> dict[str, Any]:
    """Generate the full fixture set. Deterministic: same SEED -> same bytes."""
    st = _State()
    for day in range(1, nights + 1):
        night = night_str(month, day)
        pms, proc = _build_night(st, month, day, nights)
        write_json(paths.pms_dir / f"{night}.json", {"night": night, "txns": pms})
        write_json(paths.processor_dir / f"{night}.json", {"night": night, "txns": proc})

    gross = sum(round(l["gross"] * 100) for l in st.ota_lines)
    comm = sum(round(l["commission"] * 100) for l in st.ota_lines)
    adj = sum(round(l["footnote_adjustment"] * 100) for l in st.ota_lines)
    totals = {"gross": to_dollars(gross), "commission": to_dollars(comm),
              "adjustments": to_dollars(adj), "payout": to_dollars(gross - comm - adj)}

    sidecar = render_statement(month, st.ota_lines, totals, paths.ota_pdf(month))
    pdf_sha = file_sha256(paths.ota_pdf(month))
    sidecar["pdf_sha256"] = pdf_sha
    write_json(paths.ota_sidecar(month), sidecar)

    keys = ensure_demo_keys(paths)
    paths.ota_sealed(month).write_bytes(seal_bytes(paths.ota_pdf(month).read_bytes(), keys.sealing_pub))

    write_json(paths.ground_truth, {
        "month": month, "seed": SEED,
        "counts": _gt_counts(st.ground_truth),
        "mismatches": sorted(st.ground_truth, key=lambda e: (e["night"], e["anchor_ref"])),
    })

    manifest = _manifest(paths, month, nights)
    write_json(paths.manifest, manifest)
    return manifest


def _gt_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in entries:
        out[e["class"]] = out.get(e["class"], 0) + 1
    out["total"] = len(entries)
    return out


def _manifest(paths: Paths, month: str, nights: int) -> dict[str, Any]:
    files: dict[str, str] = {}
    for p in sorted(paths.fixtures.rglob("*")):
        if p.is_dir() or p.name == "seed_manifest.json":
            continue
        rel = str(p.relative_to(paths.fixtures))
        if rel.endswith(".sealed"):
            # SealedBox uses an ephemeral key: ciphertext is intentionally
            # non-deterministic. Determinism is defined over plaintext bytes;
            # the unseal-roundtrip is asserted by test instead.
            continue
        files[rel] = file_sha256(p)
    return {
        "generator": f"innkeeper-audit/{__version__}",
        "seed": SEED, "month": month, "nights": nights,
        "determinism": "byte-identical plaintext fixtures; .sealed excluded (ephemeral ECIES key)",
        "pdf_sha256": file_sha256(paths.ota_pdf(month)),
        "files": files,
    }
