#!/usr/bin/env python3
"""Normalize observable Claude Code/Codex JSONL records; never infer solution states."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

PRIVATE = {'thinking', 'redacted_thinking', 'reasoning', 'analysis', 'encrypted_content'}
MEDIA = {'image', 'image_url', 'input_image', 'audio', 'input_audio', 'video', 'document'}
CLAUDE_META = {'mode', 'permission-mode', 'file-history-snapshot', 'file-history-delta',
               'api-request-shape', 'api-request-blob', 'api-request', 'atis-latch',
               'last-prompt', 'ai-title', 'summary', 'queue-operation', 'progress',
               'custom-title', 'agent-name', 'agent-color', 'system', 'pr-link'}
CODEX_META = {'session_meta', 'turn_context', 'event_msg', 'compacted', 'world_state',
              'token_usage_record', 'inter_agent_communication_metadata'}
ATTACHMENT_META = {'environment', 'model', 'deferred_tools_delta', 'agent_listing_delta',
                   'skill_listing', 'session_context', 'date', 'remote_session_change',
                   'prompt_snapshot', 'deferred_tools_record'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def normalize(paths, fmt='auto', max_chars=16000):
    out = {'schema_version': 'trace-events/1.0', 'sources': [], 'events': [],
           'evidence': [], 'excluded': [], 'issues': []}
    calls = {}; messages = {}; pending = []

    def exclude(sid, line, block, reason):
        out['excluded'].append({'source_id': sid, 'line': line, 'block': block, 'reason': reason})

    def clean(value):
        if isinstance(value, str) and re.fullmatch(r'gAAAAA[A-Za-z0-9_=-]{70,}',value):
            return '[opaque encrypted payload omitted]'
        if isinstance(value, dict):
            if value.get('type') in PRIVATE | MEDIA:
                return {'omitted_block_type': value['type']}
            return {k: clean(v) for k, v in value.items() if k not in PRIVATE | {'signature'}}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    def bounded(value):
        value = clean(value)
        encoded = canonical(value)
        if len(encoded) <= max_chars:
            return value, False
        return {'preview': encoded[:max_chars], 'total_chars': len(encoded)}, True

    def evidence(sid, line, block, timestamp, summary):
        eid = f'{sid}.L{line}.B{block}'
        out['evidence'].append({'id': eid, 'source_id': sid, 'line': line,
                                'output_line': None, 'timestamp': timestamp, 'summary': summary})
        return eid

    def event(sid, line, block, record, kind, payload, eid):
        content, truncated = bounded(payload)
        ev = {'id': f'event.{sid}.L{line}.B{block}', 'kind': kind, 'source_id': sid,
              'line': line, 'block': block, 'session_id': record.get('sessionId', record.get('session_id')),
              'uuid': record.get('uuid'), 'parent_uuid': record.get('parentUuid'),
              'is_sidechain': record.get('isSidechain'), 'timestamp': record.get('timestamp'),
              'payload': content, 'truncated': truncated, 'evidence_refs': [eid]}
        out['events'].append(ev)
        return ev

    for number, path in enumerate(paths, 1):
        path = Path(path).expanduser().resolve(); sid = f'src{number}'
        digest = hashlib.sha256(); line_count = 0; detected = None if fmt == 'auto' else fmt
        with path.open('rb') as handle:
            for line, raw in enumerate(handle, 1):
                line_count = line; digest.update(raw)
                if not raw.strip():
                    exclude(sid, line, 0, 'blank_line'); continue
                try:
                    record = json.loads(raw)
                    if not isinstance(record, dict):
                        raise ValueError('record is not an object')
                except (ValueError, UnicodeError):
                    eid = evidence(sid, line, 0, None, 'Unparsed JSONL record')
                    event(sid, line, 0, {}, 'unparsed', {'reason': 'invalid_json_or_non_object'}, eid)
                    out['issues'].append({'source_id': sid, 'line': line, 'reason': 'invalid_record'})
                    continue
                rtype = record.get('type', '')
                if detected is None:
                    if rtype in {'session_meta', 'response_item', 'turn_context', 'event_msg'}:
                        detected = 'codex'
                    elif rtype in CLAUDE_META | {'user', 'assistant', 'attachment'}:
                        detected = 'claude'
                timestamp = record.get('timestamp')
                if not isinstance(timestamp, str): timestamp = None
                blocks = None; role = None
                if detected == 'claude':
                    if rtype in CLAUDE_META:
                        exclude(sid, line, 0, 'metadata:' + rtype); continue
                    if rtype == 'attachment' and isinstance(record.get('attachment'), dict):
                        atype = record['attachment'].get('type')
                        if atype in ATTACHMENT_META:
                            exclude(sid, line, 0, 'metadata:attachment:' + atype); continue
                    if rtype in {'user', 'assistant'} and isinstance(record.get('message'), dict):
                        msg = record['message']; role = msg.get('role', rtype); blocks = msg.get('content')
                elif detected == 'codex':
                    if rtype in CODEX_META:
                        exclude(sid, line, 0, 'metadata:' + rtype); continue
                    if rtype == 'response_item' and isinstance(record.get('payload'), dict):
                        item = record['payload']; itype = item.get('type')
                        if itype in PRIVATE or item.get('channel') == 'analysis':
                            exclude(sid, line, 0, 'private_reasoning'); continue
                        if itype == 'additional_tools':
                            exclude(sid, line, 0, 'metadata:additional_tools'); continue
                        if itype == 'agent_message':
                            role = 'collaborator'; blocks = item.get('content')
                        elif itype == 'message':
                            role = item.get('role'); blocks = item.get('content')
                        elif itype in {'function_call', 'custom_tool_call'}:
                            args = item.get('arguments', item.get('input'))
                            if isinstance(args, str):
                                try: args = json.loads(args)
                                except ValueError: pass
                            blocks = [{'type': 'tool_use', 'id': item.get('call_id'),
                                       'name': item.get('name'), 'input': args}]
                        elif itype in {'function_call_output', 'custom_tool_call_output'}:
                            blocks = [{'type': 'tool_result', 'tool_use_id': item.get('call_id'),
                                       'content': item.get('output')}]
                if isinstance(blocks, str): blocks = [{'type': 'text', 'text': blocks}]
                if not isinstance(blocks, list):
                    eid = evidence(sid, line, 0, timestamp, 'Unsupported record: ' + str(rtype))
                    event(sid, line, 0, record, 'unsupported', {'record_type': rtype, 'keys': sorted(record)}, eid)
                    out['issues'].append({'source_id': sid, 'line': line, 'reason': 'unsupported_record'})
                    continue
                if not blocks: exclude(sid, line, 0, 'empty_message')
                for bindex, block in enumerate(blocks):
                    if not isinstance(block, dict):
                        block = {'type': 'unsupported_block'}
                    btype = block.get('type', '')
                    if btype in PRIVATE | MEDIA:
                        exclude(sid, line, bindex, 'private_reasoning' if btype in PRIVATE else 'non_text_media'); continue
                    eid = evidence(sid, line, bindex, timestamp, str(btype) + (': ' + str(block.get('name')) if btype == 'tool_use' else ''))
                    session = record.get('sessionId', record.get('session_id'))
                    if btype == 'tool_use':
                        cid = block.get('id'); key = (sid, session, cid)
                        payload = {'call_id': cid, 'tool': block.get('name'), 'input': block.get('input')}
                        fingerprint = hashlib.sha256(canonical(clean(payload)).encode()).hexdigest()
                        previous = calls.get(key, []) if cid else []
                        same = next((e for e in previous if e['input_fingerprint'] == fingerprint), None)
                        if same:
                            same['evidence_refs'].append(eid)
                            same.setdefault('snapshot_refs', []).append(eid)
                            continue
                        ev = event(sid, line, bindex, record, 'tool', payload, eid)
                        ev.update(call_id=cid, input_fingerprint=fingerprint, results=[], pairing='missing_result')
                        if cid:
                            calls.setdefault(key, []).append(ev)
                            if previous: out['issues'].append({'event_id': ev['id'], 'reason': 'conflicting_call_id'})
                        else: out['issues'].append({'event_id': ev['id'], 'reason': 'missing_call_id'})
                    elif btype == 'tool_result':
                        pending.append((sid, line, bindex, record, block, eid))
                    elif btype in {'text', 'input_text', 'output_text'}:
                        payload = {'role': role, 'text': block.get('text', '')}
                        # Only stable UUID-identical snapshots are deduplicated. Same words are not enough.
                        key = (sid, session, record.get('uuid'), bindex, canonical(payload))
                        if record.get('uuid') and key in messages:
                            messages[key]['evidence_refs'].append(eid); continue
                        ev = event(sid, line, bindex, record, 'message', payload, eid)
                        if record.get('uuid'): messages[key] = ev
                    else:
                        event(sid, line, bindex, record, 'unsupported', {'block_type': btype, 'keys': sorted(block)}, eid)
                        out['issues'].append({'source_id': sid, 'line': line, 'block': bindex, 'reason': 'unsupported_block'})
        out['sources'].append({'id': sid, 'path': str(path), 'sha256': digest.hexdigest(),
                               'line_count': line_count, 'format': detected or 'unknown'})

    for sid, line, bindex, record, block, eid in pending:
        cid = block.get('tool_use_id'); session = record.get('sessionId', record.get('session_id'))
        options = calls.get((sid, session, cid), []) if cid else []
        payload = {'call_id': cid, 'content': block.get('content'), 'is_error': block.get('is_error')}
        if len(options) != 1:
            ev = event(sid, line, bindex, record, 'orphan_result', payload, eid)
            ev['pairing'] = 'ambiguous' if options else 'missing_call'
            out['issues'].append({'event_id': ev['id'], 'reason': ev['pairing']}); continue
        ev = options[0]; value, truncated = bounded(payload)
        fingerprint = hashlib.sha256(canonical(clean(payload)).encode()).hexdigest()
        same = next((r for r in ev['results'] if r['fingerprint'] == fingerprint), None)
        if same: same['evidence_refs'].append(eid)
        else: ev['results'].append({'payload': value, 'truncated': truncated, 'fingerprint': fingerprint, 'evidence_refs': [eid]})
        ev['evidence_refs'].append(eid); ev['pairing'] = 'paired'; ev['truncated'] |= truncated
    for ev in out['events']:
        if ev['kind'] == 'tool' and ev['pairing'] == 'missing_result':
            out['issues'].append({'event_id': ev['id'], 'reason': 'missing_result'})
    out['events'].sort(key=lambda e: (int(e['source_id'][3:]), e['line'], e['block']))
    out['counts'] = {'events': len(out['events']), 'event_kinds': dict(Counter(e['kind'] for e in out['events'])),
                     'excluded': dict(Counter(e['reason'] for e in out['excluded'])),
                     'truncated_events': sum(e['truncated'] for e in out['events']), 'issues': len(out['issues'])}
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('inputs', nargs='+', type=Path)
    p.add_argument('--format', choices=['auto', 'claude', 'codex'], default='auto')
    p.add_argument('--max-chars', type=int, default=16000)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.max_chars < 1: p.error('--max-chars must be positive')
    if len({p.expanduser().resolve() for p in args.inputs}) != len(args.inputs): p.error('Duplicate input file')
    if args.output.resolve() in {p.expanduser().resolve() for p in args.inputs}: p.error('Output must not replace a source')
    result = normalize(args.inputs, args.format, args.max_chars)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), **result['counts']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
