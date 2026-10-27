#!/usr/bin/env python3
"""Render a validated solution-state graph with the compact routed visual preset."""
import argparse,copy,hashlib,json,re,subprocess
from pathlib import Path
from graph_protocol import validate,view_model,canonical
HERE=Path(__file__).resolve().parent
ASSETS=HERE.parent/'assets'/'routed'


def display_label(label):
    # Hide legacy presentation IDs, without changing the canonical record.
    return re.sub(r'^[sSmM][0-9₀₁₂₃₄₅₆₇₈₉]+\s*[·:：]\s*', '', label)


def prepare(graph):
    validate(graph)
    vm=view_model(graph); states={s['id']:s for s in graph['states']}
    nodes=[];edges=[]
    for sid in vm['state_order']:
        s=states[sid];c=s['content'];out=[t for t in graph['transitions'] if t['source']==sid and t['effect']=='changed']
        tone='success' if s['acceptance']=='passed' else 'failed' if s['acceptance']=='failed' else 'neutral' if out else 'unknown'
        observations=[o for o in graph['observations'] if o['subject_type']=='state' and o['subject_id']==sid]
        refs=list(dict.fromkeys(s['evidence_refs']+[r for o in observations for r in o['evidence_refs']]))
        nodes.append({'id':'state:'+sid,'canonical_id':sid,'role':'state','label':display_label(s['label']),'body':c['candidate'] or (c['established'][-1] if c['established'] else ''),'preview':'' if sid==graph['initial_state_id'] else None,'tone':tone,'goals':c['open_goals'],'content':c,'evidence_refs':refs,'observations':observations})
    for order,g in enumerate(vm['action_groups']):
        aid='action:'+g['id'];unchanged=g['effect']=='unchanged';unknown=g['effect']=='unknown'
        tone='unknown' if unknown or g['outcome']=='unknown' else 'failed' if unchanged and g['outcome']!='progress' else 'unknown' if unchanged else 'neutral'
        siblings=[x for x in vm['action_groups'] if x['source']==g['source']]
        nodes.append({'id':aid,'canonical_id':g['id'],'role':'action','label':g['action']['label'],'body':g['action']['method'],'tone':tone,'source':'state:'+g['source'],'target':None if g['target'] is None else 'state:'+g['target'],'effect':g['effect'],'outcome':g['outcome'],'count':len(g['transition_ids']),'transition_ids':g['transition_ids'],'parameters':g['action']['parameters'],'inline':len(siblings)==1 and not unchanged and not unknown,'display_order':order,'evidence_refs':list(dict.fromkeys(r for t in graph['transitions'] if t['id'] in g['transition_ids'] for r in t['evidence_refs'])),'observations':[o for o in graph['observations'] if o['subject_type']=='transition' and o['subject_id'] in g['transition_ids']]})
        edges.append({'id':g['id']+'.start','source':'state:'+g['source'],'target':aid,'kind':'attempt','transition_ids':g['transition_ids']})
        if not unchanged and not unknown:
            edges.append({'id':g['id']+'.result','source':aid,'target':'state:'+g['target'],'kind':'transition','transition_ids':g['transition_ids']})
        # Optional explicit assembly metadata is not another action instance.
        required=g['action']['parameters'].get('requires_states',g['action']['parameters'].get('merge_requires',[]))
        if required and (unchanged or unknown):raise ValueError('Assembly metadata requires a known changed target')
        for sid in required:
            if sid not in states:
                matches=[x for x in states if x.endswith('.'+sid)]
                if len(matches)!=1:raise ValueError('Ambiguous/missing required state: '+sid)
                sid=matches[0]
            if sid==g['target']:continue
            if not any(t['source']==sid and t['target']==g['target'] and t['effect']=='changed' for t in graph['transitions']):
                edges.append({'id':g['id']+'.requires.'+sid,'source':'state:'+sid,'target':'state:'+g['target'],'kind':'requires','basis':'explicit action parameters','transition_ids':g['transition_ids']})
    # Identical assembly dependencies need only one display line.
    seen=set();edges=[e for e in edges if (e['source'],e['target'],e['kind']) not in seen and not seen.add((e['source'],e['target'],e['kind']))]
    return {'schema_version':'trace2graph-view/1.0','semantic_model':'state_action','graph_id':graph['graph_id'],'nodes':nodes,'edges':edges,'source_graph':graph,'scope':graph['coverage']}


def validate_view(v):
    if v.get('schema_version')!='trace2graph-view/1.0':raise ValueError('Unsupported display contract')
    if v.get('semantic_model') not in ['state_action','method_dependency']:raise ValueError('Declare display semantics')
    ids=[n['id'] for n in v['nodes']]
    if len(ids)!=len(set(ids)) or not ids:raise ValueError('Invalid display node IDs')
    edgeids=[e['id'] for e in v['edges']]
    if len(edgeids)!=len(set(edgeids)):raise ValueError('Duplicate display edge IDs')
    for e in v['edges']:
        if e['source'] not in ids or e['target'] not in ids:raise ValueError('Dangling display edge')
    for n in v['nodes']:
        if n.get('role') not in ['state','action','method','task']:raise ValueError('Invalid display role')
        if n.get('tone') not in ['neutral','success','failed','unknown']:raise ValueError('Invalid display tone')
        if n.get('tone')=='success' and not n.get('evidence_refs'):raise ValueError('Green node requires explicit acceptance evidence')
    if v['semantic_model']=='state_action':
        if 'source_graph' not in v:raise ValueError('State-action views require the validated source graph')
        expected=prepare(v['source_graph'])
        if {n['id'] for n in expected['nodes']}!=set(ids) or {(e['id'],e['source'],e['target']) for e in expected['edges']}!={(e['id'],e['source'],e['target']) for e in v['edges']}:raise ValueError('Display topology differs from the formal graph')
        expected_nodes={n['id']:n for n in expected['nodes']}
        for n in v['nodes']:
            for key in ['role','tone','canonical_id','source','target','effect','outcome','transition_ids','parameters','content']:
                if n.get(key)!=expected_nodes[n['id']].get(key):raise ValueError('Display semantics differ from formal graph: '+key)
        expected_edges={e['id']:e for e in expected['edges']}
        for e in v['edges']:
            for key in ['kind','transition_ids']:
                if e.get(key)!=expected_edges[e['id']].get(key):raise ValueError('Display edge semantics differ from formal graph: '+key)
    else:
        if any(e['kind'] not in ['decomposition','dependency','requires','probe'] for e in v['edges']):raise ValueError('Method views must identify decomposition/dependency edges')
        if any(n['role'] in ['state','action'] for n in v['nodes']):raise ValueError('Do not relabel method modules as solution states')
        for n in v['nodes']:
            if n['tone']=='success' and (n.get('acceptance_scope')!='complete_task' or not n.get('validation_evidence_refs')):raise ValueError('Green method node must represent the complete accepted result, with validation evidence')
    json.dumps(v,allow_nan=False)


def write_page(v,out):
    template=(ASSETS/'graph.html').read_text()
    encoded=json.dumps(v,ensure_ascii=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    out.write_text(template.replace('__SCRIPT__',(ASSETS/'client.js').read_text()).replace('__DATA__',encoded),encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--view',action='store_true',help='Explicit legacy/curated display contract; never infer states from a dependency graph')
    p.add_argument('--node',default='node');p.add_argument('--node-modules',type=Path);p.add_argument('--browser-channel',default='chrome');p.add_argument('--browser-executable');p.add_argument('--layout',type=Path,help='Replay saved coordinates after checking display content hash');a=p.parse_args()
    raw=a.input.read_bytes();data=json.loads(raw);v=copy.deepcopy(data) if a.view else prepare(data);validate_view(v)
    v.pop('layout',None);v['input_sha256']=hashlib.sha256(raw).hexdigest();v['renderer_version']='routed-1.0';v['display_sha256']=hashlib.sha256(canonical(v).encode()).hexdigest()
    out=a.output.resolve()
    if out.suffix!='.html':p.error('--output must end with .html')
    if out==a.input.resolve():p.error('Output must not overwrite input')
    out.parent.mkdir(parents=True,exist_ok=True)
    v['json_url']=out.with_suffix('.source.json').name
    out.with_suffix('.source.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    out.with_suffix('.display.json').write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
    write_page(v,out)
    cmd=[a.node,str(HERE/'render_routed.cjs'),str(out),'--channel',a.browser_channel]
    if a.node_modules:cmd+=['--node-modules',str(a.node_modules.resolve())]
    if a.browser_executable:cmd+=['--executable',a.browser_executable]
    if a.layout:cmd+=['--layout',str(a.layout.resolve())]
    subprocess.run(cmd,check=True)
    # The layout is embedded by the browser driver; no runtime file fetches required.
    if hashlib.sha256(a.input.read_bytes()).hexdigest()!=v['input_sha256']:raise ValueError('Input changed during rendering')
    print(json.dumps({'html':str(out),'png':str(out.with_suffix('.png')),'audit':str(out.with_suffix('.render-audit.json'))},ensure_ascii=False))
if __name__=='__main__':main()
