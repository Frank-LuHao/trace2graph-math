#!/usr/bin/env python3
"""Check event accounting and provenance. This does not judge semantic annotations."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from graph_protocol import validate


def audit(events, graph, coverage):
    structure = validate(graph)
    errors = []
    if events.get('schema_version') != 'trace-events/1.0':
        raise ValueError('Unsupported normalized events version')
    if coverage.get('schema_version') != 'trace-coverage/1.0' or not isinstance(coverage.get('items'), list):
        raise ValueError('Unsupported coverage format')
    evs = {e['id']: e for e in events['events']}
    if len(evs) != len(events['events']): errors.append('Duplicate normalized event ID')
    ge = {e['id']: e for e in graph['evidence']}
    normalized_evidence = {e['id']: e for e in events['evidence']}
    gs = {s['id']: s for s in graph['sources']}
    for src in events['sources']:
        expected = {k: src[k] for k in ['id', 'path', 'sha256']}
        if gs.get(src['id']) != expected: errors.append('Source identity differs: ' + src['id'])
        try:
            digest = hashlib.sha256()
            with Path(src['path']).open('rb') as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b''): digest.update(chunk)
            if digest.hexdigest() != src['sha256']: errors.append('Source changed: ' + src['id'])
        except OSError:
            errors.append('Cannot verify source file: ' + src['id'])
    for eid, ev in ge.items():
        if eid in normalized_evidence:
            for field in ['source_id', 'line', 'output_line', 'timestamp']:
                if ev[field] != normalized_evidence[eid][field]:
                    errors.append(f'Evidence location changed: {eid}.{field}')
    records = {'state': {s['id']: s for s in graph['states']},
               'transition': {t['id']: t for t in graph['transitions']},
               'observation': {o['id']: o for o in graph['observations']}}
    counts = Counter(); seen = set(); unresolved = []; excluded = []
    for row in coverage['items']:
        if not isinstance(row, dict):
            errors.append('Coverage row must be an object'); continue
        eid = row.get('event_id')
        if not isinstance(eid, str) or eid not in evs:
            errors.append('Unknown coverage event: ' + str(eid)); continue
        if eid in seen: errors.append('Duplicate coverage event: ' + eid)
        seen.add(eid); disposition = row.get('disposition'); refs = row.get('refs')
        if disposition not in ['mapped', 'excluded', 'unresolved']:
            errors.append('Invalid disposition: ' + eid); continue
        counts[disposition] += 1
        if not isinstance(row.get('reason'), str) or not row['reason'].strip():
            errors.append('Missing coverage reason: ' + eid)
        if not isinstance(refs, list):
            errors.append('Coverage refs must be an array: ' + eid); continue
        if disposition == 'mapped':
            if not refs: errors.append('Mapped event without refs: ' + eid)
            for ref in refs:
                obj = records.get(ref.get('kind'), {}).get(ref.get('id')) if isinstance(ref, dict) else None
                if obj is None: errors.append('Unknown graph ref: ' + eid)
                elif not set(obj['evidence_refs']) & set(evs[eid]['evidence_refs']):
                    errors.append('Mapped ref has no matching event evidence: ' + eid)
        else:
            if refs: errors.append('Unmapped event must have empty refs: ' + eid)
            (unresolved if disposition == 'unresolved' else excluded).append(eid)
    missing = sorted(set(evs) - seen)
    if missing: errors.append('Unaccounted events: ' + ', '.join(missing))
    return {'structure': structure, 'accounting_valid': not errors, 'errors': errors,
            'counts': {k: counts[k] for k in ['mapped', 'excluded', 'unresolved']},
            'missing_event_ids': missing, 'unresolved_event_ids': unresolved, 'excluded_event_ids': excluded,
            'normalizer_issues': events['issues'], 'normalizer_counts': events['counts'],
            'semantic_review': 'required; accounting does not prove complete reconstruction or mathematical equivalence'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['events', 'graph', 'coverage', 'output']: p.add_argument('--' + name, type=Path, required=True)
    args = p.parse_args()
    if args.output.resolve() in {args.events.resolve(), args.graph.resolve(), args.coverage.resolve()}:
        p.error('Output must not replace an input')
    result = audit(*(json.loads(path.read_text(encoding='utf-8')) for path in [args.events, args.graph, args.coverage]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'accounting_valid': result['accounting_valid'], 'counts': result['counts'],
                      'errors': result['errors'], 'normalizer_issues': len(result['normalizer_issues'])}, ensure_ascii=False))
    if not result['accounting_valid']: raise SystemExit(1)


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError) as error: raise SystemExit(str(error))
