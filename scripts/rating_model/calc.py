import json, sys
R = json.load(open(sys.argv[1]))
def clamp(v): return max(0, min(32767, v))
def mph2v(m): return int(m * 262144 / 9)
def turns(s):
    e=i=n=0
    # helix
    h=s['helix']; e += (min(h,9)*254862)>>16; i += (min(h,11)*148945)>>16; n += (max(0,min(h-5,10))*0x140000)>>16
    # banked 3+ turns
    b=s['banked3']; e += (b*0x3C000)>>16; i += (b*0x14000)>>16; n += (b*0x50000)>>16
    s4,s3,s2,s1 = s['sloped']
    e += (min(s4,4)*0x78000)>>16; e += (min(s3,6)*273066)>>16; e += (min(s2,6)*0x3AAAA)>>16; e += (min(s1,7)*187245)>>16
    n += (min(s4,8)*0x78000)>>16
    inv=s['inv']; e += (min(inv,6)*0x1AAAAA)>>16; i += (inv*0x320000)>>16; n += (inv*0x15AAAA)>>16
    return e,i,n
def gforce(s):
    p,ng,l = s['posG'], s['negG'], s['latG']
    e = (p*5242)>>16; i=(p*52428)>>16; n=(p*17039)>>16
    e += (max(-250,min(0,ng))*-15728)>>16; i += ((ng-100)*-52428)>>16; n += ((ng-100)*-14563)>>16
    e += (min(150,l)*26214)>>16; i += l; n += (l*21845)>>16
    return e,i,n
def drops(s):
    d=s['drops']; h=s['dropH']
    e=(min(9,d)*728177)>>16; i=(d*928426)>>16; n=(d*655360)>>16
    e+=((h*2)*16000)>>16; i+=((h*2)*32000)>>16; n+=((h*2)*10240)>>16
    return e,i,n
def shelt(s):
    L=s['shLen']; e=(min(L,1000)*9175)>>16; i=(min(L,2000)*0x2666)>>16; n=(min(L,1000)*0x4000)>>16
    if s['shBank']: e+=20; n+=15
    if s['shRot']: e+=20; n+=15
    e += (min(s['shSec'],11)*774516)>>16
    return e,i,n
def prox(s): return s['prox']
def rate(name, s, veh, trace=False):
    d=R[name]; E,I,N = d['base']; br=[]
    seen=set()
    for (t,th,me,mi,mn) in d['mods']:
        if t in seen: continue  # duplicate alt descriptor
        seen.add(t)
        E0=E
        sub=None
        if t=='bonusLength': E=clamp(E+((min(s['len'],th)*me)>>16))
        elif t=='bonusTrainLength': E=clamp(E+(((min(s['cars'],veh['maxcars'])-1)*me)>>16))
        elif t=='bonusMaxSpeed':
            m=mph2v(s['max'])>>16; E=clamp(E+((m*me)>>16)); I=clamp(I+((m*mi)>>16)); N=clamp(N+((m*mn)>>16))
        elif t=='bonusAverageSpeed':
            m=mph2v(s['avg'])>>16; E=clamp(E+((m*me)>>16)); I=clamp(I+((m*mi)>>16))
        elif t=='bonusDuration': E=clamp(E+((min(s['time'],th)*me)>>16))
        elif t in ('bonusGForces','bonusTurns','bonusDrops','bonusSheltered'):
            se,si,sn={'bonusGForces':gforce,'bonusTurns':turns,'bonusDrops':drops,'bonusSheltered':shelt}[t](s)
            E=clamp(E+((se*me)>>16)); I=clamp(I+((si*mi)>>16)); N=clamp(N+((sn*mn)>>16))
        elif t=='bonusReversedTrains':
            if s.get('rev'): E=clamp(E+((E*me)>>7)); I=clamp(I+((I*mi)>>7)); N=clamp(N+((N*mn)>>7))
        elif t=='bonusProximity': E=clamp(E+((s['prox']*me)>>16))
        elif t=='bonusScenery': E=clamp(E+((s['scen']*me)>>16))
        elif t=='bonusSynchronisation': pass
        if trace and E!=E0: br.append((t,E-E0))
    # requirements assumed satisfied; lateral penalty none (lat<=2.8)
    E0=E
    for b in (1000,1100,1200,1320,1450):
        if I>=b: E-=E//4
    pen=E0-E
    E=clamp(E+((E*veh['em'])>>7)); I=clamp(I+((I*veh['im'])>>7)); N=clamp(N+((N*veh['nm'])>>7))
    air=s['air']
    if veh['lim']: E=clamp(E-(min(max(0,air-96),200)//8))
    else: E=clamp(E+(min(air,200)//8))
    N=clamp(N+(max(0,air-96 if veh['lim'] else air)//16))
    return E,I,N,br,pen
base = dict(avg=40,max=70,time=150,drops=9,dropH=40,inv=6,cars=10,prox=300,scen=235,helix=9,banked3=4,sloped=(4,6,6,7),
            posG=350,negG=-30,latG=150,len=1500,shLen=0,shSec=0,shBank=0,shRot=0,air=0)
cands = [
 ('TwisterRollerCoaster','bmfl',dict(maxcars=8,em=10,im=5,nm=10,lim=1),True),
 ('TwisterRollerCoaster','bmsd',dict(maxcars=9,em=0,im=0,nm=0,lim=1),True),
 ('FlyingRollerCoaster','bmair',dict(maxcars=8,em=0,im=0,nm=0,lim=1),True),
 ('LayDownRollerCoaster','vekst',dict(maxcars=6,em=0,im=0,nm=0,lim=1),True),
 ('MultiDimensionRollerCoaster','arrx',dict(maxcars=7,em=0,im=0,nm=0,lim=1),True),
 ('LSMLaunchedRollerCoaster','modern_twister',dict(maxcars=6,em=0,im=0,nm=0,lim=0),True),
 ('HybridCoaster','hybrid',dict(maxcars=6,em=0,im=0,nm=0,lim=0),True),
 ('SingleRailRollerCoaster','single_rail',dict(maxcars=12,em=0,im=0,nm=0,lim=0),True),
 ('InvertedRollerCoaster','nemt',dict(maxcars=9,em=0,im=0,nm=0,lim=1),True),
 ('VerticalDropCoaster','bmvd',dict(maxcars=3,em=0,im=0,nm=0,lim=1),True),
 ('LIMLaunchedRollerCoaster','premt1',dict(maxcars=7,em=0,im=0,nm=0,lim=1),True),
 ('CorkscrewRollerCoaster','arrt1',dict(maxcars=9,em=0,im=10,nm=0,lim=1),True),
 ('LoopingRollerCoaster','scht1',dict(maxcars=8,em=0,im=0,nm=0,lim=0),True),
 ('HyperTwister','bmrb',dict(maxcars=10,em=15,im=3,nm=0,lim=0),False),
 ('Hypercoaster','arrt2',dict(maxcars=8,em=15,im=0,nm=0,lim=0),False),
 ('GigaCoaster','intst',dict(maxcars=9,em=0,im=0,nm=0,lim=0),False),
 ('WoodenRollerCoaster','mft',dict(maxcars=12,em=4,im=0,nm=2,lim=0),True),
 ('StandUpRollerCoaster','togst',dict(maxcars=9,em=0,im=0,nm=0,lim=1),True),
 ('CompactInvertedCoaster','slcfo',dict(maxcars=7,em=8,im=12,nm=10,lim=1),True),
 ('SpiralRollerCoaster','spdrcr',dict(maxcars=4,em=0,im=0,nm=0,lim=0),False),
]
res=[]
for name,veh,v,hasinv in cands:
    s=dict(base); 
    if not hasinv: s['inv']=0
    s['air'] = 0 if v['lim'] else 200
    E,I,N,br,pen=rate(name,s,v,trace=True)
    res.append((E,name,veh,I,N,pen,br))
for E,name,veh,I,N,pen,br in sorted(res,reverse=True):
    print(f"{name:28s} {veh:14s} E={E/100:5.2f} I={I/100:5.2f} N={N/100:5.2f} pen={pen}")
    if '-v' in sys.argv: print('   ', br)
