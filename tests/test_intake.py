"""The problem contract: what the user asked must survive into the run.

The failure these tests exist for: the kernel proves a generated Claim
perfectly, the Claim is not the question, and every downstream artifact reports
success. `verified_by` cannot catch it, because it measures how well the
machine checked the claim it was given.
"""
import json

import pytest

from simagent import intake as intake_mod
from simagent.library import get


def test_hash_changes_when_a_bound_changes():
    """A formalizer that quietly widens a bound writes a different claim, and
    the fingerprint must say so, or an approval of the old one still counts."""
    claim = get("positive-quadratic")
    before = intake_mod.claim_hash(claim)

    edited = json.loads(json.dumps(claim.to_json()))
    space = edited["spaces"][0]
    space["high"] = float(space["high"]) + 1.0
    from simagent.core.claim import Claim

    after = intake_mod.claim_hash(Claim.from_json(edited))
    assert before != after


def test_approval_dies_when_the_claim_changes():
    claim = get("positive-quadratic")
    record = intake_mod.record(claim, "some words", "conjecture", formalizer="faux/model")
    assert record.needs_approval, "a translated claim starts unapproved"

    record.approve(record.claim_hash)
    assert record.approved and not record.needs_approval

    # re-formalizing produced a different claim: the old approval is no longer
    # an approval of what will run
    record.claim_hash = "0" * 64
    assert not record.approved
    assert record.needs_approval


def test_approving_the_wrong_hash_is_refused():
    record = intake_mod.record(get("positive-quadratic"), "words", "conjecture")
    with pytest.raises(ValueError, match="re-read the claim"):
        record.approve("deadbeef")
    assert record.needs_approval


def test_bundled_and_spec_input_need_no_translation_review():
    """Nothing translated a bundled id, so there is no translation to approve.
    Demanding approval there would train the user to click past the gate."""
    record = intake_mod.record(get("positive-quadratic"), "positive-quadratic", "bundled")
    assert record.review_state == "not-required"
    assert not record.needs_approval


def test_description_says_what_the_claim_actually_says():
    rows = intake_mod.describe_claim(get("positive-quadratic"))
    labels = {r["label"] for r in rows}
    assert {"Question", "Quantifier", "Domain", "Assumptions", "Margin",
            "Verification available"} <= labels
    for row in rows:
        assert row["why"], f"{row['label']} states a value with no explanation"
    quantifier = next(r for r in rows if r["label"] == "Quantifier")
    assert "forall" in quantifier["value"]
    assert "never prove" in quantifier["why"]


def test_the_record_survives_a_round_trip(tmp_path):
    record = intake_mod.record(get("positive-quadratic"), "words", "conjecture",
                               formalizer="faux/model")
    record.approve(record.claim_hash)
    path = record.save(tmp_path)
    assert path.name == "intake.json"

    back = intake_mod.Intake.load(tmp_path)
    assert back.approved
    assert back.formalizer == "faux/model"
    assert back.claim_hash == record.claim_hash
    assert back.claim_json == record.claim_json


def test_render_text_shows_source_model_and_review_state():
    record = intake_mod.record(get("positive-quadratic"), "is x^2+1 positive?",
                               "conjecture", formalizer="faux/model")
    text = intake_mod.render_text(record)
    assert "is x^2+1 positive?" in text
    assert "faux/model" in text
    assert record.claim_hash in text
    assert "approval required" in text


def test_the_review_never_touches_the_verdict():
    """Approval confirms the translation. If it could carry a stamp, a user
    could approve their way to a proof, so the record has nowhere to put one."""
    record = intake_mod.record(get("positive-quadratic"), "words", "conjecture")
    before = record.to_json()
    record.approve(record.claim_hash)
    after = record.to_json()

    changed = {k for k in after if before[k] != after[k]}
    assert changed == {"review_state", "approved_hash"}
    assert "verified_by" not in after and "proof" not in after
    assert not any("verified_by" in json.dumps(v) for v in after.values())
