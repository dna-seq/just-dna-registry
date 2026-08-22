"""
Named namespace groups behind the webui's listing tabs (all / featured / popular / new / test).

The *membership policy* lives here on the server — not in a consumer — so the webui, the
`registry-client` CLI, and any other client agree on what each tab contains. In particular, which
namespaces count as **test/sandbox** is a server-config regex (`Settings.test_namespace_pattern`),
and those spaces are hidden from every tab except `test`. Rendering the tabs is the frontend's job;
defining what falls in them is not.

**Hiding them is a production policy, and since 0.21.1 it asks which instance it is running on**
(`Settings.is_test_instance`, the same reading `testdata.publish_refusal` has always made). The
exclusion answers "this catalog is for real modules, and a sandbox space is noise in the default
tab" — a sentence with no meaning on the polygon, where the sandbox spaces are the entire catalog.
Left instance-blind it hid every module the test box held from the default listing, `group=all` and
free-text search, so an author who rehearsed a publish there and searched for it read `total: 0`
and concluded the publish had failed (S17). `/health` was the only route saying otherwise.

Each group is a thin preset over the primitives `search_modules` already supports (a `sort`, the
`featured` flag, and a namespace scope), so this adds policy, not a new query engine.
"""

import re

from pydantic import BaseModel, Field

from just_dna_registry.db.repository import Repository


class GroupInfo(BaseModel):
    """A listing group, as advertised by `GET /api/v1/modules/groups` for the UI to render tabs."""

    key: str = Field(description="Value to pass as `?group=`")
    label: str = Field(description="Human tab label")
    description: str = Field(description="What the tab contains")


# The catalog-wide group registry. `key` is the `?group=` value; order is the suggested tab order.
GROUPS: list[GroupInfo] = [
    GroupInfo(key="all", label="All", description="Everything published (test/sandbox spaces excluded)."),
    GroupInfo(key="featured", label="Featured", description="Namespaces curated by the operators."),
    GroupInfo(key="curated", label="Curated", description="Has an owner-highlighted review/audit."),
    GroupInfo(key="popular", label="Popular", description="Most viewed, downloaded, and starred."),
    GroupInfo(key="new", label="New", description="Most recently updated."),
    GroupInfo(key="test", label="Test", description="Sandbox / test namespaces (hidden from other tabs)."),
]
GROUP_KEYS: frozenset[str] = frozenset(g.key for g in GROUPS)

# What `all` contains depends on the instance, so its description does too (S17). A tab whose label
# says "test/sandbox spaces excluded" while the listing behind it excludes nothing is a UI telling
# its reader the opposite of what it shows them, and the polygon's whole audience is people checking
# whether their rehearsal landed.
_ALL_ON_TEST_INSTANCE = "Everything published on this test instance (nothing is excluded here)."


def groups_for(*, is_test_instance: bool) -> list[GroupInfo]:
    """`GROUPS` as this instance should advertise them. Same keys and order on both."""
    if not is_test_instance:
        return GROUPS
    return [
        g.model_copy(update={"description": _ALL_ON_TEST_INSTANCE}) if g.key == "all" else g
        for g in GROUPS
    ]


def test_namespaces(repo: Repository, pattern: str) -> list[str]:
    """The published namespaces classified as test/sandbox by the server-config `pattern`."""
    matcher = re.compile(pattern)
    return [ns for ns in repo.distinct_module_namespaces() if matcher.match(ns)]


def group_filters(
    group: str | None, repo: Repository, pattern: str, *, is_test_instance: bool = False
) -> dict[str, object]:
    """Translate a group key into `search_modules` kwargs (sort / featured / namespace scope).

    `test` isolates the test/sandbox spaces; every other group (and the default, `group=None`)
    excludes them. Returns only the keys a group sets, to merge over the caller's explicit filters.

    On the polygon (`is_test_instance`) the exclusion is dropped, so the default listing and search
    answer for the whole catalog — see the module docstring. `group=test` is deliberately *not*
    special-cased alongside it: it still means "the test/sandbox spaces", which on that instance is
    usually everything, and a client asking for the tab by name gets the same answer on both
    instances. The keyword defaults to `False` so a caller that has no `Settings` to consult keeps
    production's policy, which is the safe direction to be wrong in.
    """
    if group == "test":
        return {"only_namespaces": test_namespaces(repo, pattern)}

    # All non-test views hide the test/sandbox spaces — on production. The polygon holds nothing else.
    filters: dict[str, object] = {}
    if not is_test_instance:
        filters["exclude_namespaces"] = test_namespaces(repo, pattern)
    if group == "featured":
        filters["featured"] = True
    elif group == "curated":
        filters["curated_only"] = True
    elif group == "popular":
        filters["sort"] = "popular"
    elif group == "new":
        filters["sort"] = "recent"
    # group in (None, "all") → just the test-exclusion above, and nothing at all on the polygon.
    return filters
