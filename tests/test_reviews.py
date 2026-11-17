"""Reviews / audits (0.9.0): open, version-scoped reviews (rating + optional audit verdict); the
namespace owner highlights the good ones (SO accepted-answer style), which drives the `curated`
group and the card's `curated` flag. Registry-layer only — the manifest is untouched."""

from fastapi.testclient import TestClient

from just_dna_registry.db.repository import Repository

_YAML = """\
schema_version: "1.0"
module:
  name: coronary
  title: Coronary
  description: d
  report_title: R
genome_build: GRCh38
"""
_VARIANTS = (
    "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category,direction,stat_significance\n"
    "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,CYP2C19,cyp2c19,risk,significant\n"
)
_STUDIES = "rsid,pmid,population,p_value,conclusion,study_design\nrs4244285,29165669,T,0.05,E,U\n"
_V = "/api/v1/modules/just-dna-seq/coronary/versions/1.0.0"


def _publish(client: TestClient, key: str) -> None:
    resp = client.post(
        "/api/v1/modules/just-dna-seq/coronary/versions",
        data={"version": "1.0.0"},
        files=[
            ("files", ("module_spec.yaml", _YAML.encode(), "text/yaml")),
            ("files", ("variants.csv", _VARIANTS.encode(), "text/csv")),
            ("files", ("studies.csv", _STUDIES.encode(), "text/csv")),
        ],
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 201, resp.text


def _reviewer_key(repo: Repository, name: str = "bob") -> str:
    """A second account (not the namespace owner) with a usable key — 'anyone' can review."""
    account_id = repo.create_account(name)
    repo.add_api_key(f"mk_live_{name}", account_id)
    return f"mk_live_{name}"


def _auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def test_anyone_can_review_and_it_is_version_scoped(client: TestClient, api_key: str, app) -> None:
    _publish(client, api_key)
    bob = _reviewer_key(app.state.repo)
    resp = client.put(f"{_V}/reviews", json={"rating": 4, "verdict": "verified", "notes": "checked"},
                      headers=_auth(bob))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1 and body[0]["reviewer"] == "bob" and body[0]["rating"] == 4
    assert body[0]["verdict"] == "verified" and body[0]["highlighted"] is False


def test_review_is_upserted_not_duplicated(client: TestClient, api_key: str, app) -> None:
    _publish(client, api_key)
    bob = _reviewer_key(app.state.repo)
    client.put(f"{_V}/reviews", json={"rating": 3}, headers=_auth(bob))
    body = client.put(f"{_V}/reviews", json={"rating": 5}, headers=_auth(bob)).json()
    assert len(body) == 1 and body[0]["rating"] == 5  # replaced, not a second row


def test_rating_and_verdict_are_validated(client: TestClient, api_key: str, app) -> None:
    _publish(client, api_key)
    bob = _reviewer_key(app.state.repo)
    assert client.put(f"{_V}/reviews", json={"rating": 6}, headers=_auth(bob)).status_code == 422
    assert client.put(f"{_V}/reviews", json={"rating": 3, "verdict": "great"},
                      headers=_auth(bob)).status_code == 422


def test_only_owner_can_highlight(client: TestClient, api_key: str, app) -> None:
    _publish(client, api_key)
    bob = _reviewer_key(app.state.repo)
    client.put(f"{_V}/reviews", json={"rating": 5}, headers=_auth(bob))
    # A non-owner (bob) cannot highlight.
    assert client.put(f"{_V}/reviews/bob/highlight", headers=_auth(bob)).status_code == 403
    # The namespace owner (antonkulaga, the api_key account) can.
    body = client.put(f"{_V}/reviews/bob/highlight", headers=_auth(api_key)).json()
    assert body[0]["highlighted"] is True


def test_highlight_drives_curated_flag_and_group(client: TestClient, api_key: str, app) -> None:
    _publish(client, api_key)
    bob = _reviewer_key(app.state.repo)
    client.put(f"{_V}/reviews", json={"rating": 5, "verdict": "verified"}, headers=_auth(bob))

    # Before highlight: reviewed but not curated; absent from the curated group.
    card = client.get("/api/v1/modules").json()["items"][0]
    assert card["review_count"] == 1 and card["avg_rating"] == 5.0 and card["curated"] is False
    assert client.get("/api/v1/modules", params={"group": "curated"}).json()["total"] == 0

    client.put(f"{_V}/reviews/bob/highlight", headers=_auth(api_key))

    card = client.get("/api/v1/modules").json()["items"][0]
    assert card["curated"] is True
    curated = client.get("/api/v1/modules", params={"group": "curated"}).json()
    assert curated["total"] == 1 and curated["items"][0]["name"] == "coronary"

    # Un-highlight removes it from curated again.
    client.delete(f"{_V}/reviews/bob/highlight", headers=_auth(api_key))
    assert client.get("/api/v1/modules", params={"group": "curated"}).json()["total"] == 0


def test_reviews_list_highlighted_first(client: TestClient, api_key: str, app) -> None:
    _publish(client, api_key)
    repo = app.state.repo
    alice, bob = _reviewer_key(repo, "alice"), _reviewer_key(repo, "bob")
    client.put(f"{_V}/reviews", json={"rating": 3}, headers=_auth(alice))
    client.put(f"{_V}/reviews", json={"rating": 5}, headers=_auth(bob))
    client.put(f"{_V}/reviews/bob/highlight", headers=_auth(api_key))
    reviewers = [r["reviewer"] for r in client.get(f"{_V}/reviews").json()]
    assert reviewers[0] == "bob"  # highlighted floats to the top


def test_delete_own_review(client: TestClient, api_key: str, app) -> None:
    _publish(client, api_key)
    bob = _reviewer_key(app.state.repo)
    client.put(f"{_V}/reviews", json={"rating": 2}, headers=_auth(bob))
    assert client.delete(f"{_V}/reviews", headers=_auth(bob)).json() == []


def test_review_requires_existing_version(client: TestClient, api_key: str, app) -> None:
    _publish(client, api_key)
    bob = _reviewer_key(app.state.repo)
    resp = client.put(
        "/api/v1/modules/just-dna-seq/coronary/versions/9.9.9/reviews",
        json={"rating": 3}, headers=_auth(bob),
    )
    assert resp.status_code == 404


def test_a_highlighted_review_from_inside_the_namespace_never_curates(client: TestClient, api_key: str, app) -> None:
    """The 0.8.0 rule, "curation must come from outside" (0.32, S33): the owner's own review and a member's,
    highlighted, are kept and readable, and `curated`, the group and `/stats` ignore them. An outside one counts."""
    repo = app.state.repo
    _publish(client, api_key)
    member = _reviewer_key(repo, "member33")
    repo.add_member("just-dna-seq", int(repo.account_by_name("member33")["id"]), "member")
    outsider = _reviewer_key(repo, "outsider33")
    owner_name = client.get("/api/v1/auth/whoami", headers=_auth(api_key)).json()["account"]
    for key in (api_key, member):
        assert client.put(f"{_V}/reviews", json={"rating": 5, "verdict": "verified"}, headers=_auth(key)).status_code < 300
    for name in (owner_name, "member33"):
        assert client.put(f"{_V}/reviews/{name}/highlight", headers=_auth(api_key)).status_code == 200

    reviews = client.get(f"{_V}/reviews").json()
    assert {r["highlighted"] for r in reviews} == {True} and len(reviews) == 2
    card = client.get("/api/v1/modules").json()["items"][0]
    assert (card["review_count"], card["curated"]) == (2, False)
    assert client.get("/api/v1/modules", params={"group": "curated"}).json()["total"] == 0
    assert client.get("/api/v1/stats").json()["curated"] == 0

    client.put(f"{_V}/reviews", json={"rating": 4, "verdict": "verified"}, headers=_auth(outsider))
    client.put(f"{_V}/reviews/outsider33/highlight", headers=_auth(api_key))
    assert client.get("/api/v1/modules").json()["items"][0]["curated"] is True
    assert client.get("/api/v1/modules", params={"group": "curated"}).json()["total"] == 1
    assert client.get("/api/v1/stats").json()["curated"] == 1


def test_only_a_verified_outside_review_curates(client: TestClient, api_key: str, app) -> None:
    """0.32: an owner-highlighted outside review curates only with verdict `verified`. A `concerns` or `rejected`
    one is a pinned critique and a rating alone asserts nothing was checked; both stay listed and highlighted."""
    repo = app.state.repo
    _publish(client, api_key)

    def counts() -> tuple[bool, int, int]:
        return (
            client.get("/api/v1/modules").json()["items"][0]["curated"],
            client.get("/api/v1/modules", params={"group": "curated"}).json()["total"],
            client.get("/api/v1/stats").json()["curated"],
        )

    for name, body in (("critic", {"rating": 1, "verdict": "rejected"}), ("worried", {"rating": 3, "verdict": "concerns"}),
                       ("rater", {"rating": 5})):
        key = _reviewer_key(repo, name)
        assert client.put(f"{_V}/reviews", json=body, headers=_auth(key)).status_code < 300
        assert client.put(f"{_V}/reviews/{name}/highlight", headers=_auth(api_key)).status_code == 200
    reviews = client.get(f"{_V}/reviews").json()
    assert {r["reviewer"] for r in reviews if r["highlighted"]} == {"critic", "worried", "rater"}
    assert counts() == (False, 0, 0)

    checker = _reviewer_key(repo, "checker")
    client.put(f"{_V}/reviews", json={"rating": 4, "verdict": "verified"}, headers=_auth(checker))
    assert counts() == (False, 0, 0), "a verified review the owner has not highlighted curates nothing"
    client.put(f"{_V}/reviews/checker/highlight", headers=_auth(api_key))
    assert counts() == (True, 1, 1)


def test_a_changed_verdict_unpins_and_a_notes_edit_does_not(client: TestClient, api_key: str, app) -> None:
    """0.33, S35: an outside reviewer whose pinned `concerns` review is re-posted as `verified` must not raise
    `curated` with no act by the owner. The verdict change clears the pin; a rating or notes edit keeps it."""
    _publish(client, api_key)
    bob = _reviewer_key(app.state.repo)
    client.put(f"{_V}/reviews", json={"rating": 2, "verdict": "concerns", "notes": "n"}, headers=_auth(bob))
    client.put(f"{_V}/reviews/bob/highlight", headers=_auth(api_key))

    # Rating and notes only: the pin stays, and a pinned critique still never curates.
    body = client.put(f"{_V}/reviews", json={"rating": 3, "verdict": "concerns", "notes": "reworded"},
                      headers=_auth(bob)).json()
    assert body[0]["highlighted"] is True and body[0]["notes"] == "reworded"
    assert client.get("/api/v1/modules", params={"group": "curated"}).json()["total"] == 0

    # The verdict flips to verified: the pin is cleared, so nothing curates until the owner re-pins.
    body = client.put(f"{_V}/reviews", json={"rating": 5, "verdict": "verified", "notes": "reworded"},
                      headers=_auth(bob)).json()
    assert body[0]["verdict"] == "verified" and body[0]["highlighted"] is False
    assert client.get("/api/v1/modules").json()["items"][0]["curated"] is False
    assert client.get("/api/v1/modules", params={"group": "curated"}).json()["total"] == 0

    # The owner re-pins what they have now read: curated.
    client.put(f"{_V}/reviews/bob/highlight", headers=_auth(api_key))
    assert client.get("/api/v1/modules", params={"group": "curated"}).json()["total"] == 1

    # No verdict to a verdict is a change too (NULL compared as a value), and back again.
    body = client.put(f"{_V}/reviews", json={"rating": 5}, headers=_auth(bob)).json()
    assert body[0]["verdict"] is None and body[0]["highlighted"] is False
    client.put(f"{_V}/reviews/bob/highlight", headers=_auth(api_key))
    body = client.put(f"{_V}/reviews", json={"rating": 4}, headers=_auth(bob)).json()
    assert body[0]["highlighted"] is True  # None -> None is no change
    body = client.put(f"{_V}/reviews", json={"rating": 4, "verdict": "verified"}, headers=_auth(bob)).json()
    assert body[0]["highlighted"] is False
