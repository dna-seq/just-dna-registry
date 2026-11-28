"""The local GRCh38 reference FASTA a re-derivation reads its sequence from (0.36).

A re-derivation that left-aligns an indel or checks a reference allele reads reference sequence. Through
enricher 0.9 there was no local reader a host could hand it, so every such read was one HTTP request to
the public seqrepo service, about six a second, and that was most of a catalog sweep's 13 to 30 hours
(2026-11-11, 2026-11-17; the person: "a scaling blocker"). Upstream 0.10 (RM385, with our S166) reads an
uncompressed FASTA with a `.fai` beside it through `SequenceProxy("fasta+file://...")`, and the file is
the host's to provision. This module is that provisioning, and the report of where it stands.

**It is not a lane.** Upstream decided a URI over a cache lane for 0.10 (ROADMAP_0_10 RM385, answer 2),
so nothing in `CACHE_LANES` names it, and `warm-caches` handles it beside the lanes rather than through
`prepare_caches`. Where the file lives follows the lanes' shared base so that one setting places both.

**Present is not ready.** A FASTA that opens is not one that binds: upstream compares each GRCh38
primary contig's refget digest with the expected one and withholds a contig that differs, never falling
back to the network. Ensembl's primary assembly opens fine and binds 10 of 25 (its ambiguity codes are
written as N); NCBI's RefSeq file binds all 25 (the liaison, upstream 135eed6d, 2026-11-28). So the state
reported here stops at `indexed` until the binding is read, and the binding is upstream's
`contig_identity()`, never a count of anything in the `.refget.json` cache it writes (an early reading
here counted that file's entries and called the Ensembl file bound).

What this module does not do yet, and why: write the `.fai` (asked upstream as their S167, since their
reader owns the format's rules; no tool on our boxes writes one) and the first read that binds the
contigs (upstream 0.10, not yet on PyPI).
"""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import os
import shutil
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from just_dna_registry.config import Settings

#: The variable every enricher lane's default directory sits under (upstream's `CACHE_BASE_VAR`). Read as a
#: literal, as `PathScrubber` does, because this module must not import the enricher tier.
CACHE_BASE_VAR = "JUST_DNA_PIPELINES_CACHE_DIR"
#: The directory under the cache base that holds the reference, beside the lanes' own. Its own name: a bare
#: `reference/` is what people already use by hand for assorted genomes (one box holds eleven entries there).
REFERENCE_SUBDIR = "grch38_reference"
#: NCBI publishes one checksum file per assembly folder, naming each file as `./<name>`.
CHECKSUM_FILE = "md5checksums.txt"

#: Every state `reference_state` reports, in the order provisioning moves through them.
REFERENCE_STATES: tuple[str, ...] = ("not_configured", "absent", "partial", "unindexed", "indexed")

_CHUNK = 16 * 1024 * 1024
#: Seconds to wait before each retry, so a short outage does not spend every attempt at once.
RETRY_DELAYS: tuple[float, ...] = (5.0, 15.0, 30.0, 60.0)


class ReferenceFastaError(RuntimeError):
    """Provisioning could not finish; the message says which step and what is left on disk."""


@dataclass(frozen=True)
class ReferenceState:
    """Where the local reference stands on this box, as `warm-caches` reports it."""

    path: Path | None
    state: str
    detail: str

    def __post_init__(self) -> None:
        if self.state not in REFERENCE_STATES:
            raise ValueError(f"unknown reference state: {self.state!r}")


def reference_name(url: str) -> str:
    """The unpacked file's name: the download's last path segment without `.gz` (`Settings` checks the suffix)."""
    return Path(urlsplit(url).path).name.removesuffix(".gz")


def reference_path(settings: Settings) -> Path | None:
    """The configured FASTA path, else the one under the shared cache base, else `None`."""
    if settings.reference_fasta is not None:
        return settings.reference_fasta.expanduser().absolute()  # a fasta+file:// URI takes an absolute path
    base = os.environ.get(CACHE_BASE_VAR)
    if not base:
        return None
    return Path(base).expanduser().absolute() / REFERENCE_SUBDIR / reference_name(settings.reference_fasta_url)


def _gz(path: Path) -> Path:
    return path.with_name(f"{path.name}.gz")


def _part(path: Path) -> Path:
    return path.with_name(f"{path.name}.part")


def _index(path: Path) -> Path:
    return path.with_name(f"{path.name}.fai")


def reference_state(settings: Settings) -> ReferenceState:
    """What a run on this box would find, without touching the network."""
    path = reference_path(settings)
    if path is None:
        return ReferenceState(
            None, "not_configured",
            f"no REGISTRY_REFERENCE_FASTA and no ${CACHE_BASE_VAR}: sequence is read from the public seqrepo "
            f"service",
        )
    if path.is_file():
        if _index(path).is_file():
            return ReferenceState(path, "indexed", "indexed; which contigs bind is read on its first use")
        return ReferenceState(path, "unindexed", f"no {_index(path).name} beside it")
    leftovers = [p for p in (_part(_gz(path)), _gz(path), _part(path)) if p.exists()]
    if leftovers:
        names = ", ".join(p.name for p in leftovers)
        return ReferenceState(path, "partial", f"an unfinished provisioning left {names}; --apply resumes it")
    return ReferenceState(path, "absent", f"not provisioned; --apply downloads {settings.reference_fasta_url}")


@contextmanager
def _exclusive(path: Path) -> Generator[None]:
    """One provisioning per file: two instances share one cache base on a box."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(f"{path.name}.lock")
    with lock.open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ReferenceFastaError(f"another provisioning of {path.name} is running (it holds {lock.name})") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def expected_md5(client: httpx.Client, url: str) -> str:
    """NCBI's md5 for the download, from the checksum file in the same folder."""
    folder, _, name = url.rpartition("/")
    response = client.get(f"{folder}/{CHECKSUM_FILE}")
    response.raise_for_status()
    for line in response.text.splitlines():
        digest, _, listed = line.strip().partition("  ")
        if listed in (f"./{name}", name):
            return digest.lower()
    raise ReferenceFastaError(f"{CHECKSUM_FILE} beside {url} lists no {name}, so the download cannot be checked")


def download(client: httpx.Client, url: str, target: Path, echo: Callable[[str], None]) -> None:
    """Fetch `url` into `target`, resuming a partial `.part` across attempts, then rename it into place.

    Raw bytes with `Accept-Encoding: identity`: the resume offset and NCBI's md5 are both over the bytes on the
    wire, so nothing may decode them on the way to disk. Written as they arrive, since a chunker drops whatever
    it holds when the connection is cut.
    """
    part = _part(target)
    attempts = len(RETRY_DELAYS) + 1
    for attempt in range(1, attempts + 1):
        have = part.stat().st_size if part.exists() else 0
        headers = {"Accept-Encoding": "identity"} | ({"Range": f"bytes={have}-"} if have else {})
        try:
            with client.stream("GET", url, headers=headers) as response:
                if response.status_code == 416 and have:
                    break  # the partial file already holds every byte
                response.raise_for_status()
                resumed = response.status_code == 206
                if have and not resumed:
                    echo(f"  · {url} did not honour the resume; starting over")
                with part.open("ab" if resumed else "wb") as handle:
                    for chunk in response.iter_raw():
                        handle.write(chunk)
            break
        except httpx.HTTPError as exc:
            if attempt == attempts:
                raise ReferenceFastaError(
                    f"could not download {url} in {attempts} attempts: {exc}; {part.name} is kept"
                ) from exc
            delay = RETRY_DELAYS[attempt - 1]
            echo(f"  · download attempt {attempt} of {attempts} stopped ({type(exc).__name__}); resuming in {delay:g}s")
            time.sleep(delay)
    part.replace(target)


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def unpack(source: Path, target: Path) -> None:
    """Gunzip `source` into `target` through a `.part`, so a stopped unpack never reads as a FASTA."""
    part = _part(target)
    with gzip.open(source, "rb") as reader, part.open("wb") as writer:
        shutil.copyfileobj(reader, writer, _CHUNK)
        writer.flush()
        os.fsync(writer.fileno())
    part.replace(target)


def provision_reference(
    settings: Settings, echo: Callable[[str], None], *, client: httpx.Client | None = None
) -> ReferenceState:
    """Download, check and unpack the reference FASTA; a present one is left alone.

    Each step leaves a file the next run resumes from (`.gz.part`, then `.gz`, then `.part`), and a
    download whose md5 disagrees with NCBI's is removed, since resuming it would only extend a wrong file.
    """
    path = reference_path(settings)
    if path is None:
        return reference_state(settings)
    url = settings.reference_fasta_url
    owned = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(120.0, connect=30.0))
    try:
        with _exclusive(path):
            if not path.is_file():
                gz = _gz(path)
                if not gz.is_file():
                    echo(f"  · downloading {url}")
                    download(http, url, gz, echo)
                want = expected_md5(http, url)
                got = _md5(gz)
                if got != want:
                    gz.unlink()
                    raise ReferenceFastaError(f"{gz.name}: md5 {got}, NCBI lists {want}; the download was removed")
                echo(f"  · md5 matches NCBI's ({want}); unpacking")
                unpack(gz, path)
                gz.unlink()
    finally:
        if owned:
            http.close()
    return reference_state(settings)
