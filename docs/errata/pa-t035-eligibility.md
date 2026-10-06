# pa_t035: missing member enrollment evidence

Task: `pa_t035_t035_o001_p01_intake_payer`.

The eligibility ground truth remains `decision_member_eligible = false`.
The corrected runtime stop is completed intake, with the case left `submitted`
and no clinical review or determination. The member's coverage terminated on
2025-11-30, before the requested service dates, 2026-03-18 through 2026-03-21.
This is an administrative eligibility stop; the clinical merits of inpatient
vEEG do not change it. The original packet supplied no enrollment evidence,
so that ground truth could not be derived through the supported agent surfaces.

## Synthesis history

The saved `batch_v2_full` run dates are April 13–14, 2026. Its path
`t035.o001.p01`, bundle `draft_c2fb4be1`, takes the false edge from
`node_01_member_eligibility` to `out_01_member_not_eligible`.

The synthesis history was read from the captured artifact payloads in the
Actava catalog's `logs/inventory/2026-09-28/wsl-actava.jsonl.gz`. The catalog
records these original source-byte SHA-256 values. Reconstructing the JSON
bytes from the captured payloads matched all three hashes:

| Original run-relative path | SHA-256 |
| --- | --- |
| `stages/synth/t035.o001.p01/workspace/outputs/synthesized_bundle.json` | `05f70819feeab3094522fd1c2a688961f092e0a7f0c1b0b2be01433eab3d8c27` |
| `stages/synth/t035.o001.p01/synthesized_bundle.json` | `22952c6bdd507c0dd9409aa07993b1e7d25dd9ec37438732a4119483ef81a3a9` |
| `export/t035.o001.p01/synthesized_bundle.json` | `4efec3447e333101fb84ffc265d2b008a4ba708e52cb762542a7bbf35fd07b35` |

All three payloads put the termination date, Facets `TERMED` status, group
premium lapse, and absence of COBRA/continuity arrangements in the intake
stage's `coverage_details` answer field. Their two clinical documents do not
contain those facts. Their document plan requests only a neurology note and
monitoring attestation. The eligibility edge has `affected_documents: []`
and `evidence_posture: not_applicable`; the tree's required evidence lists
identifiers and service date, without an enrollment-status source.

The April 2 exporter change (`24a63f932`) clears `coverage_details` and
eligibility decisions for an intake-start shell. The adjacent runtime change
(`27e5b1c433`) intentionally removes `get_member_coverage` and `verify_provider`
from payer MCP. The exported bundle retains only `Coverage.active = false`,
with null effective/termination dates. Its intake shell has null coverage
details, while its expectations retain the full termination narrative.
The request-form renderer prints payer, plan, and network status only.

The May 18 PDF re-render (`7d3c676678`) did not cause this omission: extracting
the preceding revision's three request PDFs also finds no enrollment status
or termination date. The missing record was never authored into the packet.
Later curation and branding changes preserved the answer and the omission.
The exact invocation that produced the published revision is not pinned in
the catalog; this conclusion uses the saved source payloads, export snapshot,
current packet, and pre-re-render PDFs rather than assuming a same-name bundle
proves an exact historical export.

There is also an unreachable status expectation. The original exported intake
fixture starts its case at `submitted` but expects `requirement_checked`.
The exporter maps the bundle's `not_covered` requirement outcome to that
provider-side status even for payer tasks. Payer `confirm_decisions` only
completes the intake row, and the case state machine does not allow
`submitted` to transition back to `requirement_checked`. A live MCP check
confirmed that recording eligibility false leaves the case `submitted`.
The deterministic outcome verifier rejects that otherwise correct intake
stop against the old expectation. The repair therefore corrects the expected
case status to `submitted`, retaining the false eligibility decision as the
controlling result. It does not introduce a new rejection workflow or tool.

## Repair

Run this explicit data repair before building the runtime image:

```bash
uv run python scripts/repair_pa_t035_eligibility.py --data-dir data
uv run cb docker build
```

The script adds a factual Facets enrollment record to the case's documents and
`fixtures/request/03_member-enrollment-record.pdf`. It restores the termination
date in both copies of `healthverse-pa-v2-payer.json`; Docker takes its world
from `prior_auth_provider/shared/worlds/`. It also copies the same PDF to the
UM marathon task when present. The existing `payer_intake_hub.list_documents`
tool and incoming-request workspace can then expose the enrollment facts.

The repair preserves the intake decisions as agent work. It changes only
`expected_target_status` in all four expectation copies (fixtures, solution,
tests, and marathon). It aligns the canonical judge records' status and source
document catalog, preserving clinical ground truth and rationale. Rubrics,
existing PDFs, and the restricted MCP tool list stay intact. It validates
the original inactive-member identity before writing and preserves bytes on a
second run. PDF generation uses the installed Playwright Chromium; install it
with `uv run playwright install chromium` if the host does not have it.

This changes dataset bytes and task checksums. Preserve original trial results
as results of the original dataset; the repaired data needs a new dataset
revision before publication. The script does not publish a Hugging Face
revision or relabel the local dataset version pin.
