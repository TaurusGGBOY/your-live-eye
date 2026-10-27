"""Keep valid results and retry missing IDs; extracted from Hinome."""
import collections

def validate_pairs(payload,rows,allow_partial=False):
    pairs=payload['items'];expected={r['content_id'] for r in rows};seen=set();labels={}
    if not isinstance(pairs,list) or len(pairs)>len(rows) or (not allow_partial and len(pairs)!=len(rows)):raise ValueError('Output count differs')
    for pair in pairs:
        if not isinstance(pair,list) or len(pair)!=2 or any(type(x) is not int for x in pair):raise ValueError('Invalid ID/topic pair')
        cid,topic=pair
        if cid not in expected or cid in seen or topic not in range(8):raise ValueError('Missing/duplicate/invalid ID or topic')
        seen.add(cid);labels[cid]=topic
    if not allow_partial and seen!=expected:raise ValueError('Incomplete output IDs')
    return labels

def salvage_pairs(payload,rows,max_value=7,min_value=0):
    """Keep only unambiguous valid expected pairs; never infer or repair IDs."""
    pairs=payload['items']
    if not isinstance(pairs,list):raise ValueError('Output items must be a list')
    expected={r['content_id'] for r in rows}
    appearances=collections.Counter(pair[0] for pair in pairs if isinstance(pair,list) and pair and type(pair[0]) is int)
    duplicate=sorted(cid for cid,count in appearances.items() if count>1)
    unexpected=sorted(set(appearances)-expected)
    invalid_topic=set();malformed=0;labels={}
    for pair in pairs:
        if not isinstance(pair,list) or len(pair)!=2 or type(pair[0]) is not int:
            malformed+=1;continue
        cid,topic=pair
        if type(topic) is not int or not min_value<=topic<=max_value:
            if cid in expected:invalid_topic.add(cid)
            continue
        if cid in expected and appearances[cid]==1:labels[cid]=topic
    audit={'unexpected_ids':unexpected,'duplicate_ids':duplicate,'invalid_topic_ids':sorted(invalid_topic),
           'malformed_items':malformed,'missing_ids':sorted(expected-set(labels)),
           'salvaged_count':len(labels),'response_items':len(pairs)}
    return labels,audit

def salvage_scored(payload,rows):
    """Review returns category and strength in one response; keep only valid complete triples."""
    items=payload['items']
    if not isinstance(items,list):raise ValueError('Output items must be a list')
    expected={r['content_id'] for r in rows}
    appearances=collections.Counter(r[0] for r in items if isinstance(r,list) and r and type(r[0]) is int)
    labels={}
    for row in items:
        if not isinstance(row,list) or len(row)!=3 or any(type(x) is not int for x in row):continue
        cid,topic,score=row
        if cid not in expected or appearances[cid]!=1 or not 0<=topic<=7 or not 0<=score<=100:continue
        if topic!=5 and score!=0:continue
        labels[cid]={'topic':topic,'severity_score':score}
    return labels,{'missing_ids':sorted(expected-set(labels)),'salvaged_count':len(labels),'response_items':len(items)}
