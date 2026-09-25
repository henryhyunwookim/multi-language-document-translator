"""Content-based capability inspection; extensions are claims, not evidence."""
from __future__ import annotations

import hashlib
import io
import json
import posixpath
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile, BadZipFile

from lxml import etree

from backend.quality.models import Manifest

CAPABILITIES = {
    "xlsx": {"adapter": "office", "output": "xlsx", "guarantee": "native objects and immutable fields preserved"},
    "pptx": {"adapter": "office", "output": "pptx", "guarantee": "native objects and immutable fields preserved"},
    "docx": {"adapter": "office", "output": "docx", "guarantee": "native objects and immutable fields preserved"},
    "pdf": {"adapter": "pdf", "output": "pdf", "guarantee": "translated reconstruction; visual review required"},
    **{kind: {"adapter": "image", "output": "md", "guarantee": "text extraction, not image replication"}
       for kind in ("png", "jpg", "jpeg", "webp")},
    **{kind: {"adapter": "structured_text", "output": kind, "guarantee": "native syntax and protected fields validated"}
       for kind in ("txt", "md", "csv", "json", "html", "htm")},
}


def inspect_document(data: bytes, extension: str) -> Manifest:
    claimed = extension.lower().lstrip(".")
    if claimed not in CAPABILITIES:
        raise ValueError(f"Unsupported format: {claimed or 'unknown'}. Original input is retained unchanged.")
    kind = claimed
    manifest = Manifest(kind, hashlib.sha256(data).hexdigest())
    if data.startswith(b"\xd0\xcf\x11\xe0"):
        raise ValueError("Encrypted or legacy binary Office files require conversion/unlocking before translation.")
    if data.startswith(b"PK"):
        try:
            with ZipFile(io.BytesIO(data)) as package:
                entries = package.infolist()
                names = package.namelist()
                if len(names) != len(set(names)):
                    raise ValueError("Duplicate Office package members are not supported.")
                if sum(i.file_size for i in entries) > 512 * 1024 * 1024 or len(entries) > 20000:
                    raise ValueError("Office package exceeds the inspected-content limit.")
                if any(i.flag_bits & 1 for i in entries):
                    raise ValueError("Encrypted ZIP members are not supported.")
                signatures = {"xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml", "docx": "word/document.xml"}
                detected = [key for key, name in signatures.items() if name in names]
                if len(detected) != 1 or "[Content_Types].xml" not in names:
                    raise ValueError("Unrecognized Office package structure.")
                kind = detected[0]
                if any(name.lower().endswith("vbaproject.bin") for name in names):
                    raise ValueError("Macro-enabled packages need a dedicated adapter; they are not rendered as ordinary Office files.")
                if claimed != kind:
                    raise ValueError(f"File contents are {kind}, but the filename claims {claimed}.")
                parser = etree.XMLParser(resolve_entities=False, no_network=True)
                features = {"diagrams": 0, "tables": 0, "hyperlinks": 0, "opaque_assets": 0, "charts": 0, "legacy_shapes": 0}
                for entry in entries:
                    name = entry.filename
                    if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
                        raise ValueError("Invalid package member path.")
                    raw = package.read(entry)
                    manifest.assets[name] = hashlib.sha256(raw).hexdigest()
                    if "/media/" in name or "/embeddings/" in name:
                        features["opaque_assets"] += 1
                        manifest.components.append({'id': name, 'part': name,
                            'category': 'image_unknown' if '/media/' in name else 'embedded_object',
                            'text_status': 'unclassified'})
                    if "/diagrams/" in name or "/drawings/" in name:
                        features["diagrams"] += 1
                    if "/charts/" in name and name.endswith(".xml"):
                        features["charts"] += 1
                    if name.endswith(".vml"):
                        features["legacy_shapes"] += 1
                    if name.endswith(".xml") or name.endswith(".rels"):
                        root = etree.fromstring(raw, parser)
                        for node in root.xpath("//*[local-name()='tbl' or local-name()='table' or local-name()='pic' or local-name()='sp']"):
                            category = {'tbl': 'table', 'table': 'table', 'pic': 'image_unknown', 'sp': 'shape'}[etree.QName(node).localname]
                            manifest.components.append({'part': name, 'location': root.getroottree().getelementpath(node), 'category': category})
                        if root.getroottree().docinfo.doctype:
                            raise ValueError("Office XML with a DTD is not supported.")
                        features["tables"] += len(root.xpath("//*[local-name()='tbl' or local-name()='table']"))
                        features["hyperlinks"] += len(root.xpath("//*[local-name()='hyperlink' or local-name()='hlinkClick']"))
                        if name.endswith(".rels"):
                            base = posixpath.dirname(posixpath.dirname(name))
                            for relation in root:
                                if relation.get("TargetMode") == "External":
                                    continue
                                target = unquote(urlsplit(relation.get("Target", "")).path)
                                destination = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join(base, target))
                                if destination not in names:
                                    raise ValueError(f"Broken package relationship in {name}: {target}")
                manifest.features = features
                if features["opaque_assets"]:
                    manifest.limitations.append("Embedded objects and raster assets are preserved unchanged; their internal text is not translated.")
                if features["charts"]:
                    manifest.limitations.append("Chart data caches and embedded chart workbooks are preserved; cached labels may require review or refresh in Office.")
                if features["legacy_shapes"]:
                    manifest.limitations.append("Legacy VML shapes are preserved; text inside those shapes is not translated.")
        except BadZipFile as exc:
            raise ValueError("Invalid Office ZIP package.") from exc
    elif claimed in ("xlsx", "pptx", "docx"):
        raise ValueError("The file does not contain an Office ZIP package.")
    elif data.startswith(b"%PDF-"):
        if claimed != "pdf":
            raise ValueError("PDF content does not match the filename extension.")
        import fitz
        with fitz.open(stream=data, filetype="pdf") as document:
            if document.needs_pass:
                raise ValueError("Password-protected PDF requires unlocking first.")
            manifest.features = {"pages": len(document), "scanned": any(not page.get_text().strip() for page in document)}
        manifest.limitations.append("PDF reconstruction requires rendered comparison; original editability is not guaranteed.")
    elif claimed == "pdf":
        raise ValueError("The file does not contain a PDF signature.")
    elif claimed in ("png", "jpg", "jpeg", "webp"):
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            expected = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP"}[claimed]
            if image.format != expected:
                raise ValueError("Image content does not match the filename extension.")
            manifest.features = {"width": image.width, "height": image.height, "scanned": True}
            manifest.components.append({'id': 'image', 'category': 'image_unknown', 'text_status': 'unclassified'})
            image.verify()
        manifest.limitations.append("Image translation produces Markdown, not a replica of the source bitmap.")
    else:
        text = data.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("Binary content cannot be translated as text.")
        if claimed == "json":
            json.loads(text)
        manifest.features = {"characters": len(text)}
    return manifest
