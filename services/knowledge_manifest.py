"""
Knowledge manifest utilities for URUK Trinity Console.

The manifest is a control plane for the local knowledge corpus. It records
document identity, namespaces, aliases, and canonical/runtime status without
rewriting the theory files themselves.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


ROOT = Path(__file__).parent.parent
MANIFEST_PATH = ROOT / "data" / "knowledge_manifest.json"
RAG_MANIFEST_PATH = ROOT / "data" / "rag_index" / "manifest.json"
_GENERIC_BASENAME_DRIFT_OK = {"readme.md", "skill.md"}

_KEY_RE = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")
_CAU_ID_RE = re.compile(r"(\d{1,3})")
_CAU_FILE_RE = re.compile(r"CAU-(\d{3})_", re.IGNORECASE)
_CAU_EVENT_RE = re.compile(r"事件\s*([0-9]{3})")
_MOJIBAKE_MARKERS = tuple(
    chr(code)
    for code in (
        0xFFFD,
        0x00C3,
        0x00C2,
        0x00E2,
        0x00E5,
        0x00E7,
        0x00E6,
        0x00E3,
        0x5699,
        0x7E59,
        0x7E55,
        0x8076,
        0x7AC5,
    )
)


@dataclass(frozen=True)
class KnowledgeDocument:
    id: str
    path: str
    layer: str
    canonical: bool
    status: str = "active"
    aliases: Tuple[str, ...] = ()
    ref_namespaces: Tuple[str, ...] = ()
    tags: Tuple[str, ...] = ()
    legacy_paths: Tuple[str, ...] = ()
    title: str = ""
    projection_of: Optional[str] = None

    def abs_path(self, root: Path = ROOT) -> Path:
        return Path(root) / self.path

    def current_sha256(self, root: Path = ROOT) -> Optional[str]:
        path = self.abs_path(root)
        if not path.exists() or not path.is_file():
            return None
        return file_sha256(path)

    def to_dict(self, *, root: Path = ROOT, include_hash: bool = False) -> Dict[str, Any]:
        out = {
            "id": self.id,
            "path": self.path,
            "layer": self.layer,
            "canonical": self.canonical,
            "status": self.status,
            "aliases": list(self.aliases),
            "ref_namespaces": list(self.ref_namespaces),
            "tags": list(self.tags),
        }
        if self.legacy_paths:
            out["legacy_paths"] = list(self.legacy_paths)
        if self.title:
            out["title"] = self.title
        if self.projection_of:
            out["projection_of"] = self.projection_of
        if include_hash:
            out["sha256"] = self.current_sha256(root)
        return out


def load_knowledge_manifest(
    *,
    root: Path = ROOT,
    manifest_path: Optional[Path] = None,
) -> Dict[str, Any]:
    path = Path(manifest_path) if manifest_path else Path(root) / "data" / "knowledge_manifest.json"
    if not path.exists():
        return {
            "schema_version": "1.0",
            "corpus_id": "uruk-knowledge",
            "collections": [],
            "documents": [],
            "layers": {},
        }
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def manifest_sha256(
    *,
    root: Path = ROOT,
    manifest_path: Optional[Path] = None,
) -> Optional[str]:
    path = Path(manifest_path) if manifest_path else Path(root) / "data" / "knowledge_manifest.json"
    if not path.exists():
        return None
    return file_sha256(path)


def _as_tuple(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(str(item) for item in value if item is not None)
    return (str(value),)


def _rel(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _key(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    if value.endswith(".md"):
        value = value[:-3]
    value = _KEY_RE.sub("_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value


def _slug_from_path(rel_path: str, layer: str) -> str:
    stem = Path(rel_path).stem
    stem = _key(stem) or _key(rel_path)
    stem = stem.replace("_", ".")
    return f"{layer}.{stem}"


def _doc_from_mapping(raw: Mapping[str, Any], *, default_id: Optional[str] = None) -> KnowledgeDocument:
    path = str(raw["path"])
    layer = str(raw.get("layer") or "unknown")
    return KnowledgeDocument(
        id=str(raw.get("id") or default_id or _slug_from_path(path, layer)),
        path=path.replace("\\", "/"),
        layer=layer,
        canonical=bool(raw.get("canonical", False)),
        status=str(raw.get("status") or "active"),
        aliases=_as_tuple(raw.get("aliases")),
        ref_namespaces=_as_tuple(raw.get("ref_namespaces")),
        tags=_as_tuple(raw.get("tags")),
        legacy_paths=_as_tuple(raw.get("legacy_paths")),
        title=str(raw.get("title") or ""),
        projection_of=(str(raw["projection_of"]) if raw.get("projection_of") else None),
    )


def _merge_doc(base: KnowledgeDocument, override: Mapping[str, Any]) -> KnowledgeDocument:
    aliases = tuple(dict.fromkeys(base.aliases + _as_tuple(override.get("aliases"))))
    tags = tuple(dict.fromkeys(base.tags + _as_tuple(override.get("tags"))))
    legacy_paths = tuple(dict.fromkeys(base.legacy_paths + _as_tuple(override.get("legacy_paths"))))
    ref_namespaces = (
        _as_tuple(override.get("ref_namespaces"))
        if "ref_namespaces" in override
        else base.ref_namespaces
    )
    return KnowledgeDocument(
        id=str(override.get("id") or base.id),
        path=str(override.get("path") or base.path).replace("\\", "/"),
        layer=str(override.get("layer") or base.layer),
        canonical=bool(override.get("canonical", base.canonical)),
        status=str(override.get("status") or base.status),
        aliases=aliases,
        ref_namespaces=ref_namespaces,
        tags=tags,
        legacy_paths=legacy_paths,
        title=str(override.get("title") or base.title),
        projection_of=(
            str(override["projection_of"])
            if override.get("projection_of")
            else base.projection_of
        ),
    )


def iter_documents(
    *,
    root: Path = ROOT,
    manifest_path: Optional[Path] = None,
) -> List[KnowledgeDocument]:
    root = Path(root)
    manifest = load_knowledge_manifest(root=root, manifest_path=manifest_path)
    docs_by_path: Dict[str, KnowledgeDocument] = {}

    for collection in manifest.get("collections", []) or []:
        pattern = collection.get("path_glob")
        if not pattern:
            continue
        defaults = {
            "layer": collection.get("layer") or "unknown",
            "canonical": bool(collection.get("canonical", False)),
            "status": collection.get("status") or "active",
            "ref_namespaces": collection.get("ref_namespaces") or [],
            "tags": collection.get("tags") or [],
        }
        for path in sorted(root.glob(str(pattern))):
            if not path.is_file():
                continue
            rel = _rel(path, root)
            raw = {**defaults, "path": rel}
            doc = _doc_from_mapping(raw, default_id=_slug_from_path(rel, defaults["layer"]))
            docs_by_path[doc.path] = doc

    for raw in manifest.get("documents", []) or []:
        if "path" not in raw:
            continue
        rel = str(raw["path"]).replace("\\", "/")
        if rel in docs_by_path:
            docs_by_path[rel] = _merge_doc(docs_by_path[rel], raw)
            continue
        docs_by_path[rel] = _doc_from_mapping(raw)

    return sorted(docs_by_path.values(), key=lambda d: (d.layer, d.path, d.id))


def documents_by_path(
    *,
    root: Path = ROOT,
    manifest_path: Optional[Path] = None,
) -> Dict[str, KnowledgeDocument]:
    out: Dict[str, KnowledgeDocument] = {}
    for doc in iter_documents(root=root, manifest_path=manifest_path):
        current = out.get(doc.path)
        if current is None or (doc.canonical and not current.canonical):
            out[doc.path] = doc
    return out


def _match_tokens(doc: KnowledgeDocument) -> set[str]:
    path = Path(doc.path)
    stem = path.stem
    tokens = {doc.id, stem, path.name}
    tokens.update(doc.aliases)
    for prefix in ("SCR_", "MODULE_T_CALIBRATION_", "CAU-", "CAU_"):
        if stem.upper().startswith(prefix):
            tokens.add(stem[len(prefix):])
    return {_key(token) for token in tokens if _key(token)}


def resolve_ref(
    ref: str,
    *,
    root: Path = ROOT,
    manifest_path: Optional[Path] = None,
) -> List[KnowledgeDocument]:
    """Resolve a `namespace:name` reference through the manifest aliases."""
    if not ref or ":" not in ref:
        return []
    kind, name = ref.split(":", 1)
    kind_key = _key(kind)
    name_key = _key(name)
    if not kind_key or not name_key:
        return []

    docs = [
        doc for doc in iter_documents(root=root, manifest_path=manifest_path)
        if doc.status == "active" and kind_key in {_key(ns) for ns in doc.ref_namespaces}
    ]

    matches: List[KnowledgeDocument] = []
    for doc in docs:
        tokens = _match_tokens(doc)
        if name_key in tokens:
            matches.append(doc)
            continue
        if kind_key == "cau":
            cau_match = _CAU_ID_RE.search(name)
            if cau_match:
                cau_id = cau_match.group(1).zfill(3)
                if f"cau_{cau_id}" in _key(Path(doc.path).stem):
                    matches.append(doc)
                    continue
            if len(name_key) >= 3 and name_key in _key(Path(doc.path).stem):
                matches.append(doc)
                continue
    return sorted(matches, key=lambda doc: doc.path)


def _load_rag_manifest(root: Path) -> Dict[str, Any]:
    path = Path(root) / "data" / "rag_index" / "manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_load_error": f"{type(exc).__name__}: {exc}"}


def _looks_mojibake(path: str) -> bool:
    return any(marker in path for marker in _MOJIBAKE_MARKERS)


def _issue(severity: str, code: str, message: str, *, doc: Optional[KnowledgeDocument] = None,
           evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    if doc is not None:
        out["doc_id"] = doc.id
        out["path"] = doc.path
    if evidence:
        out["evidence"] = evidence
    return out


def _audit_cau_structure(root: Path, docs: List[KnowledgeDocument], issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    checked = 0
    passed = 0
    for doc in docs:
        if doc.status != "active" or not doc.path.startswith("data/causal_db/CAU-"):
            continue
        checked += 1
        path = doc.abs_path(root)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        failures: List[str] = []

        file_match = _CAU_FILE_RE.search(Path(doc.path).name)
        event_match = _CAU_EVENT_RE.search(text)
        if not file_match:
            failures.append("filename_missing_cau_id")
        if not event_match:
            failures.append("heading_missing_event_id")
        if file_match and event_match and file_match.group(1) != event_match.group(1):
            failures.append("filename_event_id_mismatch")
        if "# CAUSAL_DATABASE" not in text:
            failures.append("missing_causal_database_heading")
        if "因果記錄格式" not in text:
            failures.append("missing_causal_record_format")
        if "## 基本參數" not in text:
            failures.append("missing_basic_parameters")
        if re.search(r"^##\s*對.*協議.*意義", text, re.MULTILINE) is None:
            failures.append("missing_protocol_meaning_section")

        if failures:
            issues.append(_issue(
                "P1",
                "cau_structure_incomplete",
                "CAU file is missing required structural markers.",
                doc=doc,
                evidence={"failures": failures},
            ))
        else:
            passed += 1

    return {"checked": checked, "passed": passed, "failed": checked - passed}


def audit_knowledge(
    *,
    root: Path = ROOT,
    manifest_path: Optional[Path] = None,
    include_documents: bool = False,
) -> Dict[str, Any]:
    root = Path(root)
    docs = iter_documents(root=root, manifest_path=manifest_path)
    rag_manifest = _load_rag_manifest(root)
    rag_hashes = rag_manifest.get("source_hashes") or {}
    issues: List[Dict[str, Any]] = []

    by_id: Dict[str, List[KnowledgeDocument]] = {}
    by_basename: Dict[str, List[KnowledgeDocument]] = {}
    alias_map: Dict[Tuple[str, str], List[KnowledgeDocument]] = {}

    for doc in docs:
        by_id.setdefault(doc.id, []).append(doc)
        by_basename.setdefault(Path(doc.path).name, []).append(doc)
        if doc.status == "active":
            for namespace in doc.ref_namespaces:
                ns_key = _key(namespace)
                for alias in doc.aliases:
                    alias_key = _key(alias)
                    if ns_key and alias_key:
                        alias_map.setdefault((ns_key, alias_key), []).append(doc)

            path = doc.abs_path(root)
            if not path.exists() or not path.is_file():
                issues.append(_issue("P0", "missing_document", "Active manifest document does not exist.", doc=doc))
                continue

            if _looks_mojibake(doc.path):
                issues.append(_issue(
                    "P2",
                    "mojibake_path",
                    "Document path looks encoding-corrupted; keep alias coverage until renamed.",
                    doc=doc,
                ))

            if doc.canonical:
                rag_hash = rag_hashes.get(doc.path)
                current_hash = doc.current_sha256(root)
                if not rag_hash:
                    issues.append(_issue(
                        "P1",
                        "rag_missing_source",
                        "Active canonical document is not listed in the RAG manifest.",
                        doc=doc,
                    ))
                elif current_hash and rag_hash != current_hash[:16]:
                    issues.append(_issue(
                        "P1",
                        "rag_stale_source",
                        "RAG manifest hash does not match the current document hash.",
                        doc=doc,
                        evidence={"rag_hash": rag_hash, "current_hash16": current_hash[:16]},
                    ))

    for doc_id, grouped in by_id.items():
        paths = {doc.path for doc in grouped}
        if len(paths) > 1:
            issues.append(_issue(
                "P0",
                "duplicate_document_id",
                "Multiple documents share the same manifest id.",
                evidence={"doc_id": doc_id, "paths": sorted(paths)},
            ))

    for (namespace, alias), grouped in alias_map.items():
        paths = {doc.path for doc in grouped if doc.status == "active"}
        canonical_paths = {doc.path for doc in grouped if doc.status == "active" and doc.canonical}
        if len(canonical_paths) > 1:
            issues.append(_issue(
                "P0",
                "duplicate_canonical_alias",
                "Alias resolves to multiple active canonical documents.",
                evidence={"namespace": namespace, "alias": alias, "paths": sorted(paths)},
            ))

    for basename, grouped in by_basename.items():
        if basename.casefold() in _GENERIC_BASENAME_DRIFT_OK:
            continue
        active = [doc for doc in grouped if doc.status == "active"]
        if len(active) < 2:
            continue
        hashes = {
            doc.path: doc.current_sha256(root)
            for doc in active
            if doc.abs_path(root).exists()
        }
        distinct = {h for h in hashes.values() if h}
        if len(distinct) > 1 and any(doc.canonical for doc in active):
            issues.append(_issue(
                "P1",
                "duplicate_basename_drift",
                "Same filename appears in multiple active knowledge locations with different content.",
                evidence={"basename": basename, "paths": sorted(hashes)},
            ))

    cau_structure = _audit_cau_structure(root, docs, issues)

    severity_counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    for issue in issues:
        sev = issue.get("severity")
        if sev in severity_counts:
            severity_counts[sev] += 1

    result: Dict[str, Any] = {
        "manifest": {
            "path": str((Path(manifest_path) if manifest_path else root / "data" / "knowledge_manifest.json").resolve()),
            "sha256": manifest_sha256(root=root, manifest_path=manifest_path),
        },
        "rag": {
            "path": str((root / "data" / "rag_index" / "manifest.json").resolve()),
            "present": bool(rag_manifest) and "_load_error" not in rag_manifest,
            "built_at": rag_manifest.get("built_at"),
            "n_chunks": rag_manifest.get("n_chunks"),
            "source_count": len(rag_hashes),
            "load_error": rag_manifest.get("_load_error"),
        },
        "summary": {
            "documents": len(docs),
            "active": sum(1 for doc in docs if doc.status == "active"),
            "canonical": sum(1 for doc in docs if doc.canonical and doc.status == "active"),
            "issues": severity_counts,
            "fatal": severity_counts["P0"],
        },
        "issues": issues,
        "cau_structure": cau_structure,
    }
    if include_documents:
        result["documents"] = [doc.to_dict(root=root, include_hash=True) for doc in docs]
    return result
