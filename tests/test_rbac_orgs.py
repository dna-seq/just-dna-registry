"""Org accounts + capability RBAC + dual funding links (0.9.0).

Covers the permissions vocab (pure), own-vs-any scoping on amend/yank via `published_by`, the org
membership cascade to org-owned namespaces, role-assignment split, last-owner guards, the
contributor→member migration, and author+org funding on whoami and the module card."""

from fastapi.testclient import TestClient

from just_dna_registry.db.repository import Repository
from just_dna_registry.db.schema import connect, init_db
from just_dna_registry.permissions import (
    ROLE_CAPS,
    Capability,
    higher_role,
    role_has,
)

_YAML = (
    'schema_version: "1.0"\nmodule:\n  name: {name}\n  title: T\n  description: d\n'
    "  report_title: R\ngenome_build: GRCh38\n"
)
_VARIANTS = (
    "rsid,chrom,start,ref,alts,genotype,weight,state,conclusion,gene,category,direction,stat_significance\n"
    "rs4244285,10,94781859,G,A,A/G,-0.8,risk,het,CYP2C19,cyp2c19,risk,significant\n"
)
_STUDIES = "rsid,pmid,population,p_value,conclusion,study_design\nrs4244285,29165669,T,0.05,E,U\n"


def _auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _key(repo: Repository, name: str) -> str:
    aid = repo.create_account(name)
    repo.add_api_key(f"mk_live_{name}", aid)
    return f"mk_live_{name}"


def _publish(client: TestClient, key: str, ns: str, name: str, version: str) -> int:
    return client.post(
        f"/api/v1/modules/{ns}/{name}/versions",
        data={"version": version},
        files=[
            ("files", ("module_spec.yaml", _YAML.format(name=name).encode(), "text/yaml")),
            ("files", ("variants.csv", _VARIANTS.encode(), "text/csv")),
            ("files", ("studies.csv", _STUDIES.encode(), "text/csv")),
        ],
        headers=_auth(key),
    ).status_code


# ── Pure permissions vocab ───────────────────────────────────────────────────


def test_role_hierarchy_is_nested() -> None:
    assert ROLE_CAPS["member"] < ROLE_CAPS["admin"] < ROLE_CAPS["owner"]
    assert role_has("member", Capability.PUBLISH)
    assert not role_has("member", Capability.AMEND_ANY)
    assert role_has("admin", Capability.AMEND_ANY) and role_has("admin", Capability.CURATE)
    assert role_has("owner", Capability.MANAGE_ROLES)
    assert not role_has("admin", Capability.MANAGE_ROLES)
    assert not role_has(None, Capability.PUBLISH)


def test_higher_role() -> None:
    assert higher_role("member", "owner") == "owner"
    assert higher_role(None, "admin") == "admin"
    assert higher_role("member", None) == "member"
    assert higher_role(None, None) is None


# ── Own-vs-any scoping (member amends/yanks own; admin any) ──────────────────


def test_member_amends_own_but_not_others(client: TestClient, api_key: str, repo: Repository) -> None:
    # antonkulaga (owner of just-dna-seq) + a member labmate.
    labmate = _key(repo, "labmate")
    repo.add_member("just-dna-seq", int(repo.account_by_name("labmate")["id"]), "member")
    assert _publish(client, labmate, "just-dna-seq", "coronary", "1.0.0") == 201  # authored by labmate
    assert _publish(client, api_key, "just-dna-seq", "coronary", "2.0.0") == 201  # authored by owner

    base = "/api/v1/modules/just-dna-seq/coronary/versions"
    # member amends OWN version → ok
    assert client.patch(f"{base}/1.0.0", json={"changelog": "mine"}, headers=_auth(labmate)).status_code == 200
    # member amends ANOTHER's version → 403
    assert client.patch(f"{base}/2.0.0", json={"changelog": "nope"}, headers=_auth(labmate)).status_code == 403
    # owner amends ANY → ok
    assert client.patch(f"{base}/1.0.0", json={"changelog": "by owner"}, headers=_auth(api_key)).status_code == 200
    # member yanks OWN → ok; another's → 403
    assert client.post(f"{base}/1.0.0/yank", json={"yanked": True}, headers=_auth(labmate)).status_code == 200
    assert client.post(f"{base}/2.0.0/yank", json={"yanked": True}, headers=_auth(labmate)).status_code == 403


# ── Org membership cascade ───────────────────────────────────────────────────


def test_org_cascade_grants_publish_on_org_namespace(client: TestClient, repo: Repository) -> None:
    boss = _key(repo, "boss")
    dev = _key(repo, "dev")
    outsider = _key(repo, "outsider")
    # boss creates org acme, adds dev as member, creates an org-owned namespace.
    assert client.post("/api/v1/orgs", json={"name": "acme"}, headers=_auth(boss)).status_code == 201
    assert client.post("/api/v1/orgs/acme/members", json={"account": "dev", "role": "member"},
                       headers=_auth(boss)).status_code == 201
    assert client.post("/api/v1/orgs/acme/namespaces", json={"namespace": "acme-ns"},
                       headers=_auth(boss)).status_code == 201

    # dev (org member) can publish to the org namespace via cascade; outsider cannot.
    assert _publish(client, dev, "acme-ns", "tool", "1.0.0") == 201
    assert _publish(client, outsider, "acme-ns", "tool", "2.0.0") == 403
    # A member can't grant admin (needs owner/manage-roles).
    assert client.post("/api/v1/orgs/acme/members", json={"account": "outsider", "role": "admin"},
                       headers=_auth(dev)).status_code == 403


def test_org_last_owner_guarded(client: TestClient, repo: Repository) -> None:
    boss = _key(repo, "boss2")
    _key(repo, "second")
    client.post("/api/v1/orgs", json={"name": "beta"}, headers=_auth(boss))
    # Can't remove or demote the sole owner.
    assert client.delete("/api/v1/orgs/beta/members/boss2", headers=_auth(boss)).status_code == 409
    assert client.put("/api/v1/orgs/beta/members/boss2/role", json={"role": "member"},
                      headers=_auth(boss)).status_code == 409
    # Add a second owner, then the first can be removed.
    client.post("/api/v1/orgs/beta/members", json={"account": "second", "role": "owner"}, headers=_auth(boss))
    assert client.delete("/api/v1/orgs/beta/members/boss2", headers=_auth(boss)).status_code == 200


# ── Funding links (author + org) ─────────────────────────────────────────────


def test_funding_on_whoami_and_card(client: TestClient, repo: Repository) -> None:
    boss = _key(repo, "boss3")
    client.post("/api/v1/orgs", json={"name": "gamma"}, headers=_auth(boss))
    client.post("/api/v1/orgs/gamma/namespaces", json={"namespace": "gamma-ns"}, headers=_auth(boss))
    # boss sets a personal funding link (whoami) + the org's funding link (org settings).
    assert client.patch("/api/v1/auth/whoami", json={"funding_url": "https://ko-fi.com/boss"},
                        headers=_auth(boss)).json()["funding_url"] == "https://ko-fi.com/boss"
    client.patch("/api/v1/orgs/gamma/settings", json={"funding_url": "https://opencollective.com/gamma"},
                 headers=_auth(boss))
    assert _publish(client, boss, "gamma-ns", "tool", "1.0.0") == 201  # boss authors it

    card = [c for c in client.get("/api/v1/modules").json()["items"] if c["namespace"] == "gamma-ns"][0]
    assert card["author_funding_url"] == "https://ko-fi.com/boss"        # the author's link
    assert card["org_funding_url"] == "https://opencollective.com/gamma"  # the owning org's link

    # Bad funding URL rejected.
    assert client.patch("/api/v1/auth/whoami", json={"funding_url": "ftp://x"},
                        headers=_auth(boss)).status_code == 422


# ── Migration: contributor → member ──────────────────────────────────────────


def test_contributor_migrates_to_member(tmp_path) -> None:
    conn = connect(tmp_path / "legacy.db")
    init_db(conn)
    repo = Repository(conn)
    aid = repo.create_account("carol")
    # Simulate a pre-0.9 row written under the old vocabulary, then re-run the migration.
    conn.execute(
        "INSERT INTO namespace_members(namespace, account_id, role) VALUES ('legacy-ns', ?, 'contributor')",
        (aid,),
    )
    conn.commit()
    init_db(conn)  # idempotent _migrate runs the contributor→member update
    assert repo.namespace_role("legacy-ns", aid) == "member"


# ── What whoami says the caller reaches (0.32, S31) ──────────────────────────


def test_whoami_lists_every_namespace_the_caller_reaches_and_its_orgs(
    client: TestClient, repo: Repository
) -> None:
    """`member_of` and `orgs` against `effective_role()` itself, over every namespace in the catalog.

    Three routes: an explicit membership of somebody else's namespace, an org's namespace by cascade,
    and one namespace reached both ways (two rows, the higher being the effective role). The caller's own
    namespace stays in `namespaces` only, and a namespace the caller cannot reach appears nowhere.
    """
    from just_dna_registry.api.deps import effective_role
    from just_dna_registry.permissions import higher_role

    dev = _key(repo, "dev31")
    boss = _key(repo, "boss31")
    _key(repo, "stranger31")
    dev_id = int(repo.account_by_name("dev31")["id"])
    for owner, ns in ((dev, "dev31-own"), (boss, "boss31-lab"), (boss, "boss31-private")):
        assert client.post("/api/v1/namespaces", json={"namespace": ns}, headers=_auth(owner)).status_code == 201
    repo.add_member("boss31-lab", dev_id, "member")
    assert client.post("/api/v1/orgs", json={"name": "acme31"}, headers=_auth(boss)).status_code == 201
    assert client.post("/api/v1/orgs/acme31/members", json={"account": "dev31", "role": "admin"},
                       headers=_auth(boss)).status_code == 201
    for ns in ("acme31-tools", "acme31-shared"):
        assert client.post("/api/v1/orgs/acme31/namespaces", json={"namespace": ns},
                           headers=_auth(boss)).status_code == 201
    repo.add_member("acme31-shared", dev_id, "member")

    me = client.get("/api/v1/auth/whoami", headers=_auth(dev)).json()
    assert me["namespaces"] == ["dev31-own"]
    assert me["orgs"] == [{"org": "acme31", "role": "admin"}]
    assert {(m["namespace"], m["via"]) for m in me["member_of"]} == {
        ("boss31-lab", "member"), ("acme31-tools", "org:acme31"),
        ("acme31-shared", "member"), ("acme31-shared", "org:acme31"),
    }

    account = repo.account_by_name("dev31")
    everything = [row["name"] for row in repo.conn.execute("SELECT name FROM namespaces").fetchall()]
    assert len(everything) >= 5
    from just_dna_registry.api.deps import _account

    caller = _account(repo, int(account["id"]))
    reached: dict[str, str | None] = {}
    for m in me["member_of"]:
        reached[m["namespace"]] = higher_role(reached.get(m["namespace"]), m["role"])
    for ns in everything:
        role = effective_role(repo, caller, ns)
        if ns in me["namespaces"]:
            continue
        assert reached.get(ns) == role, ns  # boss31-private: None on both sides

    # register reissuing a key for an existing install answers the same reach (same helper).
    from just_dna_registry.api.routers.auth import _reach

    assert _reach(repo, dev_id) == {"member_of": me["member_of"], "orgs": me["orgs"]}
