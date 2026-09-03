"""Race-safe, workspace-relative result artifact storage for external Workers."""

from __future__ import annotations

from collections.abc import Iterable
import errno
import hashlib
import os
from pathlib import Path
import stat

from .result import EvidenceReference


_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


class ArtifactStoreError(ValueError):
    """Raised when an artifact cannot be safely created or verified."""


def _inside(path: Path, roots: Iterable[Path]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            pass
    return False


def _hash_regular_fd(descriptor: int) -> str:
    digest = hashlib.sha256()
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        while chunk := os.read(descriptor, 64 * 1024):
            digest.update(chunk)
    except OSError as exc:
        raise ArtifactStoreError("existing result artifact could not be read") from exc
    return digest.hexdigest()


def _verify_existing_artifact(directory_fd: int, name: str, digest: str, *, appeared: bool) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(name, os.O_RDONLY | _CLOEXEC | _NOFOLLOW, dir_fd=directory_fd)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ArtifactStoreError("existing result artifact must be an owned regular file")
        if _hash_regular_fd(descriptor) != digest:
            message = "result artifact appeared with a different hash" if appeared else "existing result artifact has a different hash"
            raise ArtifactStoreError(message)
    except ArtifactStoreError:
        raise
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise ArtifactStoreError("result artifact must not be a symlink or directory") from exc
        raise ArtifactStoreError("existing result artifact could not be opened") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def write_artifact(cwd: Path, content: bytes, *, roots: Iterable[Path], directory_name: str) -> tuple[str, EvidenceReference]:
    """Create or verify a content-addressed file under an approved workspace.

    The workspace and child directory remain open for the whole operation;
    target creation and verification use directory-relative no-follow opens.
    """

    digest = hashlib.sha256(content).hexdigest()
    try:
        workspace = cwd.resolve(strict=True)
        if not workspace.is_dir() or not _inside(workspace, roots):
            raise ArtifactStoreError("result directory is outside approved workspace")
    except ArtifactStoreError:
        raise
    except (OSError, RuntimeError) as exc:
        raise ArtifactStoreError("result directory could not be prepared") from exc

    workspace_fd: int | None = None
    directory_fd: int | None = None
    target_name = f"result-{digest}.txt"
    try:
        workspace_fd = os.open(workspace, os.O_RDONLY | _CLOEXEC | _DIRECTORY | _NOFOLLOW)
        if not stat.S_ISDIR(os.fstat(workspace_fd).st_mode):
            raise ArtifactStoreError("result workspace must be a directory")
        try:
            os.mkdir(directory_name, 0o700, dir_fd=workspace_fd)
        except FileExistsError:
            pass
        directory_fd = os.open(
            directory_name,
            os.O_RDONLY | _CLOEXEC | _DIRECTORY | _NOFOLLOW,
            dir_fd=workspace_fd,
        )
        info = os.fstat(directory_fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ArtifactStoreError("result directory must be an owned non-symlink directory")
        if stat.S_IMODE(info.st_mode) != 0o700:
            try:
                os.fchmod(directory_fd, 0o700)
            except OSError as exc:
                raise ArtifactStoreError("result directory permissions could not be tightened") from exc
            info = os.fstat(directory_fd)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ArtifactStoreError("result directory permissions could not be verified")
        try:
            descriptor = os.open(
                target_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _CLOEXEC | _NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
        except FileExistsError:
            _verify_existing_artifact(directory_fd, target_name, digest, appeared=True)
        else:
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError as exc:
                raise ArtifactStoreError("result artifact could not be written") from exc
    except ArtifactStoreError:
        raise
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise ArtifactStoreError("result directory must be a non-symlink directory") from exc
        raise ArtifactStoreError("result directory could not be prepared") from exc
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
        if workspace_fd is not None:
            os.close(workspace_fd)

    ref = f"{directory_name}/{target_name}"
    return ref, EvidenceReference(
        id=f"native-result-{digest[:16]}",
        kind="file",
        artifact_ref=ref,
        content_hash=f"sha256:{digest}",
    )
