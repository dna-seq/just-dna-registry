"""
What counts as test data, and what each deployment mode does about it (0.12).

One module because the question is asked from four places that must agree: the publish gate, namespace
creation over HTTP, the admin CLI's `issue-key`, and the purge. A second opinion anywhere means prod
refuses something the purge will not clean, or cleans something prod was happy to accept.

**The two identifier spellings are not interchangeable.** Namespaces and account handles allow hyphens
(`test-sandbox`, `just-dna-seq`); a module name is validated `lowercase alphanumeric with underscores`,
so the same prefix has to be spelled `test_` there. `services.purge.module_name_prefix` owns that
conversion and this module reuses it rather than re-deriving it.
"""

from just_dna_registry.config import Settings
from just_dna_registry.services.purge import module_name_prefix


def is_test_namespace(namespace: str, settings: Settings) -> bool:
    """Whether a namespace (or account handle) is marked as test data."""
    return namespace.startswith(settings.test_data_prefix)


def is_test_module_name(name: str, settings: Settings) -> bool:
    """Whether a *module name* is marked as test data, in the spelling a module name can have."""
    return name.startswith(module_name_prefix(settings.test_data_prefix))


#: The parameter that lets test data onto production deliberately (0.14). Spelled once, because it is
#: a request field on two routes, a flag on the CLI, and a sentence in three error messages.
OVERRIDE_PARAM: str = "allow_test_data"


def override_hint() -> str:
    """How to proceed anyway, appended to every refusal so the dead end is navigable."""
    return (
        f"If you mean it, resend with {OVERRIDE_PARAM}=true — production accepts test-prefixed data "
        f"when it is asked explicitly."
    )


def accepted_anyway(finding: str) -> str:
    """The warning a caller gets back when the override was used.

    A refusal turned into a warning has to *stay* a warning: this lands on the response so the
    publisher sees that production is now holding test-prefixed data, and so the fact appears in a
    log rather than only in whoever's memory passed the flag.

    It also names the purge, which is the sharp edge of this feature: `registry purge-test-data`
    selects on exactly the prefix that was just waved through, so data kept here on purpose is data a
    routine cleanup would remove. It lists what it will delete before deleting it — that listing is
    the moment to notice.
    """
    return (
        f"accepted on production by explicit request ({OVERRIDE_PARAM}=true): {finding} "
        f"NOTE: `registry purge-test-data` matches this prefix, so a routine cleanup would remove it."
    )


def test_data_refusal(namespace: str, name: str, settings: Settings) -> str | None:
    """Why production would refuse this `(namespace, name)`, or `None` when it is fine.

    Returns a message rather than raising: the publish path turns it into a `PublishError`, the
    namespace route into an `HTTPException`, and the CLI into a `BadParameter` — three shapes, one rule.
    Since 0.14 it is also read by the *availability* pre-flight, which neither refuses nor warns but
    reports (S6) — a fourth shape, and the reason this returns prose instead of raising.

    **This is the rule, not the verdict.** A caller passing `allow_test_data=true` proceeds anyway;
    the finding then becomes a warning via `accepted_anyway`. Keeping the two apart is what lets one
    rule serve a refusal, a warning and a pre-flight report without any of them re-deriving it.

    Only production has anything to say here. On the polygon this is exactly the data the instance
    exists to hold, and a guard there would make the test box unable to test.
    """
    if settings.is_test_instance:
        return None
    prefix = settings.test_data_prefix
    if is_test_namespace(namespace, settings):
        return (
            f"namespace {namespace!r} starts with {prefix!r}, which this production instance does not "
            f"accept by default. Publish it to the test instance instead, or drop the prefix if it is "
            f"real."
        )
    if is_test_module_name(name, settings):
        return (
            f"module name {name!r} starts with {module_name_prefix(prefix)!r}, which this production "
            f"instance does not accept by default. Publish it to the test instance instead, or rename "
            f"it."
        )
    return None


def duplicate_scope_account(settings: Settings) -> bool:
    """Whether `duplicate_content` should only consider versions published by the *same* account.

    Production says no: identical data under a second `(namespace, name)` is a re-list whoever owns it,
    and that is the whole point of a name-independent signature.

    The polygon says yes, and it is a deliberate divergence rather than a relaxation. A shared test box
    has several publishers rehearsing overlapping data, and cross-account blocking there is noise about
    somebody else's rehearsal. Within-account is kept so the gate is still *exercised* — a publisher can
    still discover their own rename being refused before they meet the same refusal on production.

    The cost is real and worth stating: this is one contract with two behaviours, so a test run cannot
    prove a *cross-account* duplicate would be refused in production. That case is covered by the
    `409 duplicate_content` unit tests rather than by the polygon.
    """
    return settings.is_test_instance
