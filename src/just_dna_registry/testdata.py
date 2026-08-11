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


def test_data_refusal(namespace: str, name: str, settings: Settings) -> str | None:
    """Why production must refuse this `(namespace, name)`, or `None` when it is fine.

    Returns a message rather than raising: the publish path turns it into a `PublishError`, the
    namespace route into an `HTTPException`, and the CLI into a `BadParameter` — three shapes, one rule.

    Only production refuses. On the polygon this is exactly the data the instance exists to hold, and a
    guard there would make the test box unable to test.
    """
    if settings.is_test_instance:
        return None
    prefix = settings.test_data_prefix
    if is_test_namespace(namespace, settings):
        return (
            f"namespace {namespace!r} starts with {prefix!r}, which this production instance does not "
            f"accept. Publish it to the test instance instead, or drop the prefix if it is real."
        )
    if is_test_module_name(name, settings):
        return (
            f"module name {name!r} starts with {module_name_prefix(prefix)!r}, which this production "
            f"instance does not accept. Publish it to the test instance instead, or rename it."
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
