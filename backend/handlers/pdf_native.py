"""Translate a PDF text layer while keeping its original artwork and geometry."""
from __future__ import annotations

import io
import re
from collections import Counter

import fitz

from backend.quality.inspection import inspect_document
from backend.quality.models import Finding, QualityFailure, Segment, stable_id
from backend.quality.supervisor import Supervisor
from backend.quality.validation import review_rendered
from backend.quality.pdf_rendering import checked_text_box


def translate_native_pdf(translator, data: bytes) -> io.BytesIO:
    manifest = inspect_document(data, 'pdf')
    bindings = {}
    with fitz.open(stream=data, filetype='pdf') as document:
        image_pages = []
        for index, page in enumerate(document):
            translator.check_cancelled()
            if page.get_images():
                image_pages.append(index + 1)
            from backend.quality.components import pdf_regions
            regions, components = pdf_regions(page)
            manifest.components.extend({**item, 'part': f'page:{index + 1}'} for item in components)
            context = page.get_text()[:12000]
            for region, text, block in regions:
                # Keep isolated folios in their original position and typeface.
                box = fitz.Rect(block['bbox'])
                if block['category'] == 'text' and (box.y1 < page.rect.height * .1 or box.y0 > page.rect.height * .9) and re.fullmatch(r'(?:\[Page:\s*\d+\]|(?:Page\s+)?\d+)', text.strip(), re.I):
                    continue
                spans = block['spans']
                location = f'page:{index + 1}/{region}'
                identifier = stable_id('pdf', location)
                manifest.segments.append(Segment(identifier, text, f'page:{index + 1}', location, context,
                                                  {'bbox': block['bbox']}, block['category']))
                styles = Counter((span['font'], span['size'], span['color']) for span in spans)
                dominant = styles.most_common(1)[0][0]
                primary = next(span for span in spans if (span['font'], span['size'], span['color']) == dominant)
                primary = {**primary, 'redactions':[span['bbox'] for span in spans],
                           'mixed_styles':len({(s['font'],s['size'],s['color']) for s in spans}) > 1}
                box = fitz.Rect(block['bbox'])
                if block['category'] == 'table_cell' and box.width > 4 and box.height > 4:
                    box = box + (2, 2, -2, -2)
                bindings[identifier] = (index, box, primary)
        manifest.features['tables'] = sum(item['category'] == 'table' for item in manifest.components)
        supervisor = Supervisor(translator, manifest)
        if supervisor.model:
            from backend.quality.components import classify_image
            for number in image_pages:
                classify_image(supervisor, document[number - 1].get_pixmap(dpi=110).tobytes('png'), 'image/png', f'page:{number}')
        values = supervisor.run()
        segments = {segment.id: segment for segment in manifest.segments}
        report = supervisor.report
        translator.quality_report = report
        if report.status == 'failed':
            raise QualityFailure(report)
        # Establish a document style target from fitted peers, then cap local
        # variation without forcing every box down to the densest outlier.
        fitted = {}
        style_scales = {}
        def style_key(primary, category):
            return (primary['font'], round(primary['size'], 1), primary['color'], category)
        for key, (_, rect, primary) in bindings.items():
            translator.check_cancelled()
            if values[key] == segments[key].source:
                continue
            try:
                _, scale = checked_text_box(values[key], rect.width, rect.height, primary['size'],
                                            primary['color'], bool(primary.get('flags', 0) & 16))
                fitted[key] = scale
                style_scales.setdefault(style_key(primary, segments[key].category), []).append(scale)
            except ValueError:
                pass
        from statistics import median
        targets = {key: median(scales) for key, scales in style_scales.items()}
        for index, page in enumerate(document):
            translator.check_cancelled()
            selected = [(key, info) for key, info in bindings.items() if info[0] == index]
            changed = [(key, info) for key, info in selected if values[key] != segments[key].source]
            for _, (_, rect, primary) in changed:
                for span_rect in primary['redactions']:
                    page.add_redact_annot(span_rect, fill=False, cross_out=False)
            if changed:
                # Removing text must not erase intersecting photos or vector diagrams.
                page.apply_redactions(images=0, graphics=0)
            for key, (_, rect, primary) in changed:
                rendered = None
                target = targets.get(style_key(primary, segments[key].category), 1)
                local = [fitted[key2] for key2, (_, _, peer) in changed
                         if key2 in fitted and style_key(peer, segments[key2].category) == style_key(primary, segments[key].category)]
                preferred = min(target, median(local)) if local else target
                # A single dense box must not make all other text unreadably small.
                preferred = max(preferred, .8)
                for attempt in range(3):
                    try:
                        rendered, scale = checked_text_box(values[key], rect.width, rect.height, primary['size'] * preferred,
                                                           primary['color'], bool(primary.get('flags',0) & 16))
                        break
                    except ValueError:
                        if attempt == 2 or supervisor.model is None:
                            break
                        feedback = Finding('text_fit',
                            'The translation does not fit this fixed text box. Use concise equivalent wording, preserving all facts, '
                            'numbers and identifiers. Preserve separate list items and paragraph boundaries. Do not summarize or omit content.',
                            segment_id=key, location=segments[key].location)
                        try:
                            repaired = supervisor.translate([segments[key]], [feedback])
                            checks = supervisor.check_entities([segments[key]], repaired)
                            checks.extend(supervisor.review([segments[key]], repaired))
                            report.repairs += 1
                            if any(f.severity != 'info' for f in checks):
                                break
                            values.update(repaired)
                            report.findings.extend(checks)
                        except InterruptedError:
                            raise
                        except Exception:
                            break
                if rendered is None:
                    report.findings.append(Finding('text_fit', 'Translated PDF text did not fit its original box.', 'error', key, f'page:{index + 1}'))
                    continue
                with fitz.open(stream=rendered,filetype='pdf') as text_page:
                    page.show_pdf_page(rect,text_page,0)
                scale *= preferred
                if scale < .55:
                    report.findings.append(Finding('small_text', f'Text required scaling to {scale:.2f}.', segment_id=key, location=f'page:{index + 1}'))
                if primary['mixed_styles']:
                    report.findings.append(Finding('pdf_inline_styles', 'A mixed-style text block uses its dominant font and color; inspect inline emphasis.', segment_id=key, location=f'page:{index + 1}'))
        report.checks['native_text_rendering'] = 'failed' if any(f.code == 'text_fit' for f in report.findings) else 'passed'
        if image_pages:
            report.findings.append(Finding('raster_text', 'Original images are preserved. Text embedded in those images requires visual review.', location=','.join(map(str,image_pages))))
        output = document.tobytes(garbage=4, deflate=True)
    if report.finish().status == 'failed':
        raise QualityFailure(report)
    report.findings.extend(review_rendered(supervisor, data, output, 'pdf'))
    translator.quality_report = report.finish()
    if report.status == 'failed':
        raise QualityFailure(report)
    return io.BytesIO(output)
