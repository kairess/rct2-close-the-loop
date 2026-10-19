import re, sys, glob, os, json
d = sys.argv[1]
def val(s):
    s = s.strip()
    m = re.match(r'RideRating::make\((\d+),\s*(\d+)\)', s)
    if m: return int(m.group(1))*100+int(m.group(2))
    m = re.match(r'MakeFixed16_2dp\((\d+),\s*(\d+)\)', s)
    if m: return int(m.group(1))*100+int(m.group(2))
    m = re.match(r'kRideRating\w*', s)
    return int(s, 0)
out = {}
for f in sorted(glob.glob(d + '/*.h')):
    t = open(f).read()
    i = t.find('.RatingsData')
    if i < 0: continue
    blk = t[i:]
    base = re.search(r'\{\s*(RideRating::make\([^)]*\)),\s*(RideRating::make\([^)]*\)),\s*(RideRating::make\([^)]*\))\s*\}', blk)
    after = blk[base.end():]
    m = re.match(r'\s*,\s*(\d+)\s*,\s*([\w-]+)\s*,\s*(true|false)', after)
    X=r'((?:RideRating::make\([^)]*\)|MakeFixed16_2dp\([^)]*\)|[^,}])+)'
    mods = re.findall(r'\{\s*RatingsModifierType::(\w+),\s*'+X+r',\s*'+X+r',\s*'+X+r',\s*'+X+r'\}', blk)
    name = os.path.basename(f)[:-2]
    out[name] = dict(base=[val(base.group(k)) for k in (1,2,3)], unrel=int(m.group(1)), shelter=m.group(2), relax=m.group(3)=='true',
        mods=[(a, val(b), val(c), val(dd), val(e)) for a,b,c,dd,e in mods])
json.dump(out, open(sys.argv[2],'w'), indent=0)
for n,v in out.items():
    print(n, v['base'], 'relax' if v['relax'] else '', ' '.join(f"{a[0].replace('bonus','b').replace('requirement','R').replace('penalty','P')}:{a[1]}/{a[2]}/{a[3]}/{a[4]}" for a in v['mods']))
