"""Validate the versioned contract and render a data-driven reference SVG.

This module never infers mathematical equivalence, edits the source graph, or reads
referenced traces. Grouping changes presentation only; action instances remain in JSON.
"""
import argparse
from collections import OrderedDict, deque
import html
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent
try:
    from jsonschema import Draft202012Validator
except ImportError:
    raise SystemExit('Missing jsonschema. Install scripts/requirements.txt in a task-local Python environment.')
SCHEMA=HERE.parent/'references/exploration-graph.schema.json'

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def validate(data,schema_path=SCHEMA):
    json.dumps(data,allow_nan=False)  # Reject non-JSON NaN/Infinity, including in arbitrary parameters.
    schema=json.loads(Path(schema_path).read_text())
    Draft202012Validator.check_schema(schema)
    errors=[f"{'.'.join(map(str,e.absolute_path)) or '$'}: {e.message}" for e in Draft202012Validator(schema).iter_errors(data)]
    if errors:raise ValueError('\n'.join(errors))
    def index(items,key='id'):
        result={}
        for item in items:
            if item[key] in result:raise ValueError(f'Duplicate {key}: {item[key]}')
            result[item[key]]=item
        return result
    states=index(data['states']); transitions=index(data['transitions']); sources=index(data['sources']); evidence=index(data['evidence'])
    index(data['observations']);aliases=index(data['state_aliases'],'original_id')
    if data['initial_state_id'] not in states:raise ValueError('Initial state does not exist')
    for item in data['states']+data['transitions']+data['observations']+data['state_aliases']:
        for eid in item['evidence_refs']:
            if eid not in evidence:raise ValueError(f'Unknown evidence: {eid}')
    for item in evidence.values():
        if item['source_id'] not in sources:raise ValueError('Unknown evidence source: '+item['source_id'])
        if item['output_line'] is not None and item['output_line']<item['line']:raise ValueError('Output precedes call line')
    action_types={};batch_positions=set()
    for t in transitions.values():
        if t['source'] not in states:raise ValueError('Unknown source state: '+t['source'])
        if t['target'] is not None and t['target'] not in states:raise ValueError('Unknown target state: '+t['target'])
        if t['effect']=='unknown':
            if t['target'] is not None:raise ValueError('Unknown effect requires an unresolved target (null)')
        elif t['target'] is None:raise ValueError('Known effect requires a target state')
        elif (t['effect']=='unchanged')!=(t['source']==t['target']):raise ValueError('Effect conflicts with state identity: '+t['id'])
        tid=t['action']['type_id'];signature=canonical(t['action'])
        if tid in action_types and action_types[tid]!=signature:raise ValueError('Action type has conflicting definitions: '+tid)
        action_types[tid]=signature
        order=t['order']
        if bool(order.get('batch_id'))!=('position' in order):raise ValueError('Batch id and position must be supplied together')
        if order:
            key=(order['batch_id'],order['position'])
            if key in batch_positions:raise ValueError('Duplicate position in one batch')
            batch_positions.add(key)
    for observation in data['observations']:
        targets=states if observation['subject_type']=='state' else transitions
        if observation['subject_id'] not in targets:raise ValueError('Unknown observation subject: '+observation['subject_id'])
    for state in states.values():
        if state['acceptance']=='passed' and state['content']['open_goals']:raise ValueError('Accepted terminal state still has open goals: '+state['id'])
        if state['acceptance'] in ['passed','failed']:
            supported=any(o['subject_type']=='state' and o['subject_id']==state['id'] and o['kind']=='validation' and
                          o['verdict']==state['acceptance'] and o['evidence_refs'] for o in data['observations'])
            if not supported:raise ValueError('Acceptance requires a referenced validation observation: '+state['id'])
    for original,a in aliases.items():
        if original in states or a['canonical_id'] not in states:raise ValueError('Alias must map a noncanonical id directly to a canonical state')
    return {'states':len(states),'action_instances':len(transitions),'action_types':len(action_types),
            'unchanged_instances':sum(t['effect']=='unchanged' for t in transitions.values()),
            'unresolved_instances':sum(t['target'] is None for t in transitions.values()),
            'observations':len(data['observations']),'evidence':len(evidence),
            'checks':'schema and referential/structural consistency only; mathematical equivalence is not certified'}

def view_model(data):
    """No ID- or domain-specific logic. Never merge different outcomes/endpoints."""
    groups=OrderedDict()
    for t in data['transitions']:
        key=canonical([t['source'],t['target'],t['action'],t['effect'],t['outcome']])
        if key not in groups:
            groups[key]={'id':f'action-group-{len(groups)+1}','source':t['source'],'target':t['target'],
                         'action':t['action'],'effect':t['effect'],'outcome':t['outcome'],'transition_ids':[]}
        groups[key]['transition_ids'].append(t['id'])
    # Reachability order is a layout choice, never a claim about execution order.
    state_ids={s['id'] for s in data['states']};order=[];seen=set();queue=deque([data['initial_state_id']])
    while queue:
        sid=queue.popleft()
        if sid in seen:continue
        seen.add(sid);order.append(sid)
        queue.extend(t['target'] for t in data['transitions'] if t['source']==sid and t['target'] in state_ids and t['target'] not in seen)
    order.extend(s['id'] for s in data['states'] if s['id'] not in seen)
    return {'state_order':order,'action_groups':list(groups.values()),'unreachable_states':sorted(state_ids-seen)}

def render_svg(data,width=840):
    vm=view_model(data);state_map={s['id']:s for s in data['states']};positions={};group_pos={};headings=[];y=76
    # One state per band supports cycles, merges and disconnected states without DAG assumptions.
    for sid in vm['state_order']:
        positions[sid]=(width/2-180,y,360,76);y+=108
        outgoing=[g for g in vm['action_groups'] if g['source']==sid]
        families=OrderedDict()
        for g in outgoing:families.setdefault(g['action']['group'],[]).append(g)
        for family,groups in families.items():
            headings.append((44,y+10,family));y+=28
            for start in range(0,len(groups),3):
                chunk=groups[start:start+3];card_w=(width-112)/3
                for col,g in enumerate(chunk):group_pos[g['id']]=(44+col*(card_w+12),y,card_w,88)
                y+=128
        y+=30
    height=y+8
    ns='http://www.w3.org/2000/svg';ET.register_namespace('',ns)
    root=ET.Element('{'+ns+'}svg',{'viewBox':f'0 0 {width} {height}','width':str(width),'height':str(height),'role':'img','aria-label':data['title']})
    def el(parent,tag,attrs=None,text=None):
        n=ET.SubElement(parent,'{'+ns+'}'+tag,{k:str(v) for k,v in (attrs or {}).items()})
        if text is not None:n.text=str(text)
        return n
    el(root,'style',text='text{font-family:system-ui,sans-serif;font-size:13px;fill:#243044}.small{font-size:12px;fill:#637084}.title{font-size:18px;font-weight:500}')
    el(root,'rect',{'width':width,'height':height,'fill':'#fff'})
    el(root,'text',{'x':28,'y':28,'class':'title'},data['title'])
    el(root,'text',{'x':28,'y':51,'class':'small'},f"{len(data['states'])} 个状态 · {len(data['transitions'])} 次动作记录 · {len(vm['action_groups'])} 组展示；布局不代表时间顺序")
    defs=el(root,'defs')
    for name,color in [('arrow','#8793a3'),('progress','#348564')]:
        marker=el(defs,'marker',{'id':name,'viewBox':'0 0 10 10','refX':9,'refY':5,'markerWidth':5,'markerHeight':5,'orient':'auto'})
        el(marker,'path',{'d':'M0 0 L10 5 L0 10 Z','fill':color})
    for g in vm['action_groups']:
        x,gy,cw,ch=group_pos[g['id']];sx,sy,sw,sh=positions[g['source']]
        el(root,'path',{'d':f'M {sx} {sy+sh/2} H 20 V {gy-12} H {x+cw/2} V {gy}','fill':'none','stroke':'#b5bec8','stroke-width':1,'marker-end':'url(#arrow)'})
        if g['target'] is not None and g['target']!=g['source']:
            tx,ty,tw,th=positions[g['target']];lane=width-16
            el(root,'path',{'d':f'M {x+cw/2} {gy+ch} V {gy+ch+12} H {lane} V {ty+th/2} H {tx+tw}','fill':'none','stroke':'#348564','stroke-width':1.3,'marker-end':'url(#progress)'})
    for x,hy,label in headings:el(root,'text',{'x':x,'y':hy,'class':'small'},label)
    def wrap(value,limit):
        rows=[];row='';used=0
        for c in value:
            size=13 if ord(c)>0x2e80 else 7
            if used+size>limit and row:rows.append(row);row='';used=0
            row+=c;used+=size
        if row:rows.append(row)
        return rows
    for sid,(x,sy,sw,sh) in positions.items():
        state=state_map[sid];n=el(root,'g',{'data-state-id':sid,'tabindex':0,'role':'button','aria-label':state['label']})
        el(n,'title',text=canonical(state));el(n,'rect',{'x':x,'y':sy,'width':sw,'height':sh,'rx':12,'fill':'#edf5fc' if state['acceptance']!='passed' else '#edf7f1','stroke':'#d6e1eb'})
        for i,line in enumerate(wrap(state['label'],sw-24)[:2]):el(n,'text',{'x':x+12,'y':sy+24+i*18},line)
        el(n,'text',{'x':x+12,'y':sy+sh-13,'class':'small'},sid+(' · 已验核' if state['acceptance']=='passed' else ''))
    for g in vm['action_groups']:
        x,gy,cw,ch=group_pos[g['id']];n=el(root,'g',{'data-action-group-id':g['id'],'tabindex':0,'role':'button','aria-label':g['action']['label']})
        el(n,'title',text=canonical(g));el(n,'rect',{'x':x,'y':gy,'width':cw,'height':ch,'rx':2,'fill':'#fdf5ee' if g['outcome']=='not_found' else '#f4f7fa','stroke':'#e5e8ec'})
        label=g['action']['label']+(f" ×{len(g['transition_ids'])}" if len(g['transition_ids'])>1 else '')
        for i,line in enumerate(wrap(label,cw-20)[:3]):el(n,'text',{'x':x+10,'y':gy+20+i*16},line)
        outcome={'not_found':'未找到','progress':'有进展','counterexample':'得到反例','error':'执行错误','abandoned':'已放弃','unknown':'结果未知'}[g['outcome']]
        effect='状态不变' if g['effect']=='unchanged' else '去向未知' if g['target'] is None else '→ '+g['target']
        el(n,'text',{'x':x+10,'y':gy+ch-13,'class':'small'},outcome+' · '+effect)
    return ET.tostring(root,encoding='unicode')+'\n',vm

def render_html(data,svg,vm):
    template=(HERE.parent/'assets/viewer.html').read_text(encoding='utf-8')
    payload=json.dumps({'graph':data,'view':vm},ensure_ascii=False,allow_nan=False)
    payload=payload.replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    values={'<!--TITLE-->':html.escape(data['title']),'<!--GRAPH-->':svg,'/*PAYLOAD*/':payload}
    return re.sub(r'<!--TITLE-->|<!--GRAPH-->|/\*PAYLOAD\*/',lambda m:values[m.group(0)],template)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['validate','render']);p.add_argument('input',type=Path)
    p.add_argument('--schema',type=Path,default=SCHEMA);p.add_argument('--output',type=Path);args=p.parse_args()
    data=json.loads(args.input.read_text(encoding='utf-8'));result=validate(data,args.schema)
    if args.command=='render':
        if args.output is None:p.error('render requires --output')
        if args.output.suffix.lower() not in ['.svg','.html']:p.error('Output extension must be .svg or .html')
        destinations={args.output.resolve(),args.output.with_suffix('.view.json').resolve(),args.output.with_suffix('.svg').resolve()}
        if args.input.resolve() in destinations:p.error('Output must not overwrite the input graph')
        args.output.parent.mkdir(parents=True,exist_ok=True)
        svg,vm=render_svg(data)
        args.output.with_suffix('.svg').write_text(svg,encoding='utf-8')
        if args.output.suffix.lower()=='.html':args.output.write_text(render_html(data,svg,vm),encoding='utf-8')
        args.output.with_suffix('.view.json').write_text(json.dumps(vm,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        result.update(output=str(args.output),display_action_groups=len(vm['action_groups']))
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as error:raise SystemExit(str(error))
