import json, glob, sys, os
D = sys.argv[1]
rows = []
for f in glob.glob(D + '/**/ride/*.json', recursive=True):
    try: d = json.load(open(f))
    except Exception as e: continue
    p = d.get('properties', {})
    if p.get('category') not in ('rollercoaster', ['rollercoaster']): continue
    t = p.get('type'); t = t if isinstance(t, str) else ','.join(t)
    rm = p.get('ratingMultiplier', {})
    cars = p.get('cars', [])
    if isinstance(cars, dict): cars = [cars]
    cm = [(c.get('mass'), c.get('numSeats'), c.get('poweredAcceleration'), c.get('poweredMaxSpeed')) for c in cars]
    flags = [k for k in ('limitAirTimeBonus','hasShelter','noInversions','noBanking','playSplashSoundSlide') if p.get(k)]
    rows.append((t, d['id'], rm.get('excitement',0), rm.get('intensity',0), rm.get('nausea',0), p.get('minCarsPerTrain'), p.get('maxCarsPerTrain'), p.get('tabCar'), p.get('defaultCar'), p.get('headCars'), p.get('tailCars'), cm, flags))
rows.sort(key=lambda r: (r[0], -r[2]))
for r in rows: print('\t'.join(map(str, r)))
