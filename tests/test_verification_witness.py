"""Format 0.8 (RM292): a verification record names where its values came from and what it compared
them against, and upstream derives `independence` from the two. The detail view carries all four and
says, per check, whether its agreement counts as evidence for the value."""

from conftest import _make_manifest
from just_dna_format.manifest import (
    VALID_VERIFICATION_INDEPENDENCE,
    ModuleManifest,
    Verification,
    VerificationRecord,
)

from just_dna_registry.models.api import agreement_is_evidence
from just_dna_registry.services.catalog import _verification


def _with(records: list[VerificationRecord]) -> ModuleManifest:
    manifest, _ = _make_manifest("ns1", "modul", "1.0.0", genes=["G"], categories=["x"])
    manifest.verification = Verification(checks=records)
    return manifest


def test_every_member_upstream_names_has_an_answer_and_an_unknown_one_cannot_say() -> None:
    assert len(VALID_VERIFICATION_INDEPENDENCE) >= 2  # a floor: an emptied import must not pass
    answered = {member: agreement_is_evidence(member) for member in VALID_VERIFICATION_INDEPENDENCE}
    assert None not in answered.values(), answered
    assert answered == {"independent": True, "self_consistent": False}
    assert agreement_is_evidence(None) is None
    assert agreement_is_evidence("a_member_added_later") is None


def test_the_detail_view_carries_the_witness_and_reads_independence_by_member() -> None:
    info = _verification(_with([
        VerificationRecord(check="clinical_significance", subjects=4, findings=0,
                           checked_source="clinvar", witness_source="clinvar",
                           independence="self_consistent"),
        VerificationRecord(check="clinical_significance", subjects=4, findings=1,
                           checked_source="authored", witness_source="clinvar",
                           independence="independent", undecided=2),
        VerificationRecord(check="clinical_significance", subjects=4),  # written before 0.8
    ]))
    assert info is not None
    rows = [(c.checked_source, c.witness_source, c.independence, c.undecided, c.agreement_is_evidence)
            for c in info.checks]
    assert rows == [
        ("clinvar", "clinvar", "self_consistent", None, False),
        ("authored", "clinvar", "independent", 2, True),
        (None, None, None, None, None),
    ]
