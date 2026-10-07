"""Bounded, read-only history projection; search always covers the full archive."""
import json

PAGE_SIZE = 300


def history_window(rows, query='', limit=PAGE_SIZE):
    needle=query.strip().casefold()
    selected=[];total=0
    for row in reversed(rows):
        if row.get('role') not in ('user','assistant') or row.get('kind')=='memory_summary':
            continue
        if needle and needle not in row.get('text','').casefold():
            continue
        total+=1
        if len(selected)<limit:selected.append(row)
    selected.reverse()
    return selected,total


def history_packets(rows,offset,notices,metadata,max_bytes):
    """Split expanded pages without exceeding the stdio protocol's byte limit."""
    def packet(start,values):
        return dict(type='history',offset=start,rows=values,notices=notices,**metadata)
    def size(value):
        return len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8'))
    # Leave room for the offset gaining digits as later chunks are appended.
    overhead=size(packet(offset,[]))+32
    available=max_bytes-overhead
    if available<=0:raise ValueError('通知内容超过窗口传输限制')
    target=min(1024*1024,available)
    batch=[];used=0;start=offset
    for row in rows:
        amount=size(row)+1
        if amount>available:raise ValueError('单条记录超过窗口传输限制')
        if batch and used+amount>target:
            yield packet(start,batch)
            start+=len(batch);batch=[];used=0
        batch.append(row);used+=amount
    # An empty suffix still tells the receiver to truncate deleted records.
    if batch or start==offset:yield packet(start,batch)
