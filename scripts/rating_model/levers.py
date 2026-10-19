import sys, json
sys.argv=[sys.argv[0], 'rtd.json']
exec(open('calc.py').read().split("base = dict")[0])
bmfl=dict(maxcars=8,em=10,im=5,nm=10,lim=1)
hyb=dict(maxcars=6,em=0,im=0,nm=0,lim=0)
b=dict(avg=35,max=60,time=110,drops=9,dropH=40,inv=6,cars=8,prox=300,scen=235,helix=5,banked3=4,sloped=(4,6,6,7),posG=350,negG=-30,latG=150,len=900,shLen=0,shSec=0,shBank=0,shRot=0,air=0)
def r(name,veh,**kw):
    s=dict(b); s.update(kw); E,I,N,_,pen=rate(name,s,veh); return E,I,N,pen
E0,I0,N0,_=r('TwisterRollerCoaster',bmfl)
print('baseline twister bmfl',E0,I0,N0)
tests={
 'shelter 11sec+bank+rot+220m':dict(shSec=11,shBank=1,shRot=1,shLen=220),
 'shelter 11sec only, 50m':dict(shSec=11,shLen=50),
 'loop prox +180':dict(prox=480),'loop prox +370':dict(prox=670),
 'path +160':dict(prox=460),'path +305':dict(prox=605),'water +97':dict(prox=397),
 'reversed trains':dict(rev=1),
 'helix 9':dict(helix=9),
 'air 296 ticks':dict(air=296),'air 150':dict(air=150),
 'avg +5mph':dict(avg=40),'max +10mph':dict(max=70),
 'time 150':dict(time=150),
 '2 laps (time220, drops18, inv12, helix10)':dict(time=220,drops=18,inv=12,helix=10),
 '2 laps of half-content (time 150)':dict(time=150),
 'dropH +20 (15m)':dict(dropH=60),
 'latG 1.0':dict(latG=100),
 'cars 6':dict(cars=6),
 'inv 7':dict(inv=7),'drops 10':dict(drops=10),
}
for k,kw in tests.items():
    E,I,N,pen=r('TwisterRollerCoaster',bmfl,**kw)
    print(f"{k:45s} dE={(E-E0)/100:+.2f} dI={(I-I0)/100:+.2f} dN={(N-N0)/100:+.2f} pen={pen}")
Eh,Ih,Nh,_=r('HybridCoaster',hyb,inv=6,cars=6,air=200)
print('hybrid same stats air200', Eh, Ih, Nh, 'dE', (Eh-E0)/100)
Eh,Ih,Nh,_=r('HybridCoaster',hyb,inv=6,cars=6,air=200,avg=31)
print('hybrid -4mph avg', Eh, Ih, Nh, 'dE', (Eh-E0)/100)
# all levers stacked on twister
E,I,N,pen=r('TwisterRollerCoaster',bmfl,shSec=11,shBank=1,shRot=1,shLen=220,prox=300+180+160+50,helix=9,time=150,avg=38)
print('stack twister', E,I,N,pen)
E,I,N,pen=r('TwisterRollerCoaster',bmfl,shSec=11,shBank=1,shRot=1,shLen=220,prox=300+180+160+50,helix=9,time=150,avg=38,rev=1)
print('stack twister +rev', E,I,N,pen)
E,I,N,pen=r('HybridCoaster',hyb,cars=6,air=200,shSec=11,shBank=1,shRot=1,shLen=220,prox=300+160+50,helix=9,time=150,avg=35)
print('stack hybrid', E,I,N,pen)
