/*
 * rct2loop: game-judge plugin for rct2-close-the-loop.
 *
 * Newline-delimited JSON over a localhost TCP socket. Each request is
 * {"id": n, "cmd": "...", "args": {...}} and gets exactly one reply
 * {"id": n, "ok": true, "result": ...} or {"id": n, "ok": false, "error": "..."}.
 *
 * The heavy command is `evaluate`: create a ride, place every piece at the
 * coordinates the client computed, add entrance/exit, run a test, wait until
 * the game has rated the ride, collect stats, demolish. One round trip per track.
 *
 * Written in ES5 for the Duktape engine.
 */

var NAME = 'rct2loop';
var VERSION = '0.1.0';
var PORT_BASE = 21000;
var LC_TESTED = 1 << 1;
var LC_CRASHED = 1 << 10;
var STATUS_TESTING = 2;
var HYPER_SPEED = 8;
var MAX_TRACK_TYPE = 1024;

function log(msg) {
    console.log('[' + NAME + '] ' + msg);
}

function errText(res) {
    var parts = [];
    if (res.errorTitle) parts.push(res.errorTitle);
    if (res.errorMessage) parts.push(res.errorMessage);
    if (parts.length === 0) parts.push('error ' + res.error);
    return parts.join(': ');
}

// Run step(i, next) for i in [0, n) one after another. Works whether the game
// invokes action callbacks synchronously or later, without deep recursion.
function sequence(n, step, done) {
    var i = 0;
    var finished = false;
    function loop() {
        while (i < n && !finished) {
            var idx = i;
            var sync = true;
            var completed = false;
            step(idx, function (err) {
                if (finished) return;
                if (err) {
                    finished = true;
                    done(err, idx);
                    return;
                }
                completed = true;
                i = idx + 1;
                if (!sync) loop();
            });
            sync = false;
            if (!completed) return;
        }
        if (!finished && i >= n) {
            finished = true;
            done(null);
        }
    }
    loop();
}

function setPaused(paused, cb) {
    if (context.paused === paused) {
        cb();
        return;
    }
    context.executeAction('pausetoggle', {}, function () {
        cb();
    });
}

// ---------------------------------------------------------------- commands

function cmdPing(args, reply) {
    reply(true, {
        name: NAME,
        version: VERSION,
        apiVersion: context.apiVersion,
        paused: context.paused,
        gameSpeed: context.gameSpeed,
        ticks: date.ticksElapsed,
        mapSize: { x: map.size.x, y: map.size.y }
    });
}

var wantedSpeed = HYPER_SPEED;

function cmdSetup(args, reply) {
    // sandbox, build while paused, no breakdowns, no money, objective "have fun".
    // Without "have fun" the scenario deadline passes after enough hyper-speed
    // ticks and ScenarioEnd() resets the game speed to normal.
    // args.sandbox === false keeps land ownership rules: track only on owned land or with construction rights.
    // Guests are removed so a loaded scenario's crowd does not slow down every tick, and
    // research status is ignored so any coaster type can be built (money is out of scope too).
    var sandbox = args.sandbox === false ? 0 : 1;
    var cheats = [[0, sandbox], [11, 1], [9, 1], [15, 1], [38, 0], [21, 0], [44, 1]];
    sequence(cheats.length, function (i, next) {
        context.executeAction('cheatset', { type: cheats[i][0], param1: cheats[i][1], param2: 0 }, function (res) {
            next(res.error ? 'cheat ' + cheats[i][0] + ': ' + errText(res) : null);
        });
    }, function (err) {
        if (err) return reply(false, err);
        wantedSpeed = args.speed || HYPER_SPEED;
        ensureSpeed(function (err) {
            if (err) return reply(false, err);
            setPaused(true, function () {
                reply(true, { speed: context.gameSpeed, paused: context.paused });
            });
        });
    });
}

function ensureSpeed(cb) {
    if (context.gameSpeed === wantedSpeed) return cb(null);
    context.executeAction('gamesetspeed', { speed: wantedSpeed }, function (res) {
        cb(res.error ? 'gamesetspeed: ' + errText(res) : null);
    });
}

function segmentInfo(seg) {
    var elements = [];
    for (var i = 0; i < seg.elements.length; i++) {
        var e = seg.elements[i];
        elements.push([e.x, e.y, e.z]);
    }
    return {
        type: seg.type,
        description: seg.description,
        beginZ: seg.beginZ,
        endZ: seg.endZ,
        endX: seg.endX,
        endY: seg.endY,
        beginDirection: seg.beginDirection,
        endDirection: seg.endDirection,
        beginSlope: seg.beginSlope,
        endSlope: seg.endSlope,
        beginBank: seg.beginBank,
        endBank: seg.endBank,
        length: seg.length,
        elements: elements,
        trackGroup: seg.trackGroup,
        turnDirection: seg.turnDirection,
        slopeDirection: seg.slopeDirection,
        allowsChainLift: seg.allowsChainLift,
        isBanked: seg.isBanked,
        isInversion: seg.isInversion,
        onlyAllowedUnderwater: seg.onlyAllowedUnderwater,
        onlyAllowedAboveGround: seg.onlyAllowedAboveGround,
        startsHalfHeightUp: seg.startsHalfHeightUp,
        mirrorSegment: seg.mirrorSegment,
        priceModifier: seg.priceModifier
    };
}

function cmdSegments(args, reply) {
    var out = [];
    for (var t = 0; t < MAX_TRACK_TYPE; t++) {
        var seg = context.getTrackSegment(t);
        if (seg) out.push(segmentInfo(seg));
    }
    reply(true, out);
}

function cmdLoadObject(args, reply) {
    var obj = objectManager.load(args.identifier);
    if (!obj) return reply(false, 'could not load ' + args.identifier);
    var info = { identifier: obj.identifier, name: obj.name, index: obj.index, type: obj.type };
    if (obj.type === 'ride') {
        var ro = objectManager.getObject('ride', obj.index);
        info.rideType = ro.rideType;
        info.maxHeight = ro.maxHeight;
        info.excitementMultiplier = ro.excitementMultiplier;
        info.intensityMultiplier = ro.intensityMultiplier;
        info.nauseaMultiplier = ro.nauseaMultiplier;
    }
    reply(true, info);
}

function cmdInstalledRides(args, reply) {
    var out = [];
    var all = objectManager.installedObjects;
    for (var i = 0; i < all.length; i++) {
        if (all[i].type === 'ride') {
            out.push({ identifier: all[i].identifier, name: all[i].name, sourceGames: all[i].sourceGames });
        }
    }
    reply(true, out);
}

// Clearance of every element of each track piece, measured by placing the piece in the air:
// args = {rideType, rideObject, types: [...], x, y, z} -> {type: [[dx, dy, baseDz, clearanceDz]]}.
// (The plugin's track segment API gives element offsets but not their clearance heights.)
function cmdMeasureClearance(args, reply) {
    var out = {};
    sequence(args.types.length, function (i, next) {
        var t = args.types[i];
        createRide(args, function (err, rideId) {
            if (err) { out[t] = 'create: ' + err; return next(null); }
            context.executeAction('trackplace', trackArgs(rideId, args.rideType, [t, args.x * 32, args.y * 32, args.z, 0, 0, 0]), function (res) {
                if (res.error) {
                    out[t] = errText(res);
                } else {
                    var els = [];
                    for (var dx = -6; dx <= 6; dx++) {
                        for (var dy = -6; dy <= 6; dy++) {
                            var tile = map.getTile(args.x + dx, args.y + dy);
                            for (var k = 0; k < tile.numElements; k++) {
                                var e = tile.getElement(k);
                                if (e.type === 'track' && e.ride === rideId) {
                                    els.push([dx, dy, e.baseZ - args.z, e.clearanceZ - args.z]);
                                }
                            }
                        }
                    }
                    out[t] = els;
                }
                demolish(rideId, function () { next(null); });
            });
        });
    }, function () {
        reply(true, out);
    });
}

// Rating multipliers and train specs of every installed ride object (args.prefix filters identifiers).
// Objects not already in the park are loaded only to read them, then unloaded again.
function cmdRideObjects(args, reply) {
    var loaded = {};
    var have = objectManager.getAllObjects('ride');
    for (var i = 0; i < have.length; i++) loaded[have[i].identifier] = true;
    var all = objectManager.installedObjects;
    var out = [];
    for (var j = 0; j < all.length; j++) {
        var info = all[j];
        if (info.type !== 'ride') continue;
        if (args.prefix && info.identifier.indexOf(args.prefix) !== 0) continue;
        var obj = loaded[info.identifier] ? null : objectManager.load(info.identifier);
        var ro = null;
        var cur = objectManager.getAllObjects('ride');
        for (var k = 0; k < cur.length; k++) if (cur[k].identifier === info.identifier) ro = cur[k];
        if (ro) {
            var v = ro.vehicles[ro.defaultVehicle] || ro.vehicles[0] || {};
            out.push({
                identifier: info.identifier, name: ro.name, rideType: ro.rideType,
                excitement: ro.excitementMultiplier, intensity: ro.intensityMultiplier, nausea: ro.nauseaMultiplier,
                maxHeight: ro.maxHeight, minCars: ro.minCarsInTrain, maxCars: ro.maxCarsInTrain,
                carMass: v.carMass, numSeats: v.numSeats, spacing: v.spacing,
                poweredAcceleration: v.poweredAcceleration, poweredMaxSpeed: v.poweredMaxSpeed,
                flags: ro.flags, vehicleFlags: v.flags
            });
        }
        if (obj && !loaded[info.identifier]) objectManager.unload(info.identifier);
    }
    reply(true, out);
}

function createRide(args, cb) {
    context.executeAction('ridecreate', {
        rideType: args.rideType,
        rideObject: args.rideObject,
        entranceObject: args.entranceObject || 0,
        colour1: 0,
        colour2: 0,
        inspectionInterval: 0
    }, function (res) {
        if (res.error) return cb(errText(res));
        cb(null, res.ride);
    });
}

function demolish(rideId, cb) {
    context.executeAction('ridedemolish', { ride: rideId, modifyType: 0 }, function (res) {
        cb(res.error ? errText(res) : null);
    });
}

function trackArgs(rideId, rideType, p) {
    // p = [trackType, x, y, z, direction, flags, brakeSpeed]
    return {
        x: p[1], y: p[2], z: p[3], direction: p[4],
        ride: rideId, trackType: p[0], rideType: rideType,
        brakeSpeed: p[6] || 0, colour: 0, seatRotation: 4,
        trackPlaceFlags: p[5] || 0, isFromTrackDesign: false
    };
}

// Which track types can this ride type place at all? Queries each type at a
// spot in the air; the per-type error text tells "not allowed" from other causes.
function cmdAllowed(args, reply) {
    createRide(args, function (err, rideId) {
        if (err) return reply(false, 'ridecreate: ' + err);
        var types = [];
        for (var t = 0; t < MAX_TRACK_TYPE; t++) {
            if (context.getTrackSegment(t)) types.push(t);
        }
        var results = [];
        sequence(types.length, function (i, next) {
            var p = [types[i], args.x, args.y, args.z, 0, 0, 0];
            context.queryAction('trackplace', trackArgs(rideId, args.rideType, p), function (res) {
                results.push([types[i], res.error, res.error ? errText(res) : '']);
                next(null);
            });
        }, function () {
            demolish(rideId, function () {
                reply(true, results);
            });
        });
    });
}

function rideStats(ride) {
    return {
        excitement: ride.excitement,
        intensity: ride.intensity,
        nausea: ride.nausea,
        maxSpeed: ride.maxSpeed,
        averageSpeed: ride.averageSpeed,
        rideTime: ride.rideTime,
        rideLength: ride.rideLength,
        maxPositiveVerticalGs: ride.maxPositiveVerticalGs,
        maxNegativeVerticalGs: ride.maxNegativeVerticalGs,
        maxLateralGs: ride.maxLateralGs,
        totalAirTime: ride.totalAirTime,
        numDrops: ride.numDrops,
        numLiftHills: ride.numLiftHills,
        highestDropHeight: ride.highestDropHeight,
        lifecycleFlags: ride.lifecycleFlags,
        status: ride.status,
        cars: carsPerTrain(ride),
        trains: ride.vehicles.length
    };
}

function cmdEvaluate(args, reply) {
    var speedBefore = context.gameSpeed;
    // Track placement silently removes trees in its way, and demolishing the ride
    // does not bring them back. Report it so the caller can discard the instance.
    var sceneryBefore = args.sceneryRect ? countScenery(args.sceneryRect) : null;
    ensureSpeed(function (err) {
        if (err) return reply(false, err);
        evaluate(args, function (ok, result) {
            if (ok) {
                result.speedBefore = speedBefore;
                // A kept ride keeps its trees, so the count only means something when everything was undone.
                if (sceneryBefore !== null && !args.keep) result.sceneryLost = sceneryBefore - countScenery(args.sceneryRect);
            }
            reply(ok, result);
        });
    });
}

// Lower the land on the given tiles ([[tileX, tileY, heightUnits]]) and remember
// what was there, so restoreLand can put it back after the evaluation.
function cutLand(cuts, cb) {
    var saved = [];
    sequence(cuts.length, function (i, next) {
        var c = cuts[i];
        var tile = map.getTile(c[0], c[1]);
        var surf = null;
        for (var k = 0; k < tile.numElements; k++) {
            if (tile.getElement(k).type === 'surface') surf = tile.getElement(k);
        }
        if (!surf) return next('no surface at ' + c);
        saved.push([c[0], c[1], surf.baseHeight, surf.slope]);
        context.executeAction('landsetheight', { x: c[0] * 32, y: c[1] * 32, height: c[2], style: 0 }, function (res) {
            next(res.error ? 'cut ' + c + ': ' + errText(res) : null);
        });
    }, function (err) {
        cb(err, saved);
    });
}

function restoreLand(saved, cb) {
    sequence(saved.length, function (i, next) {
        var s = saved[i];
        context.executeAction('landsetheight', { x: s[0] * 32, y: s[1] * 32, height: s[2], style: s[3] }, function () {
            next(null);
        });
    }, function () {
        cb();
    });
}

function evaluate(args, reply) {
    var t0 = Date.now();
    var timing = {};
    cutLand(args.cuts || [], function (err, saved) {
        if (err) {
            return restoreLand(saved, function () {
                reply(true, { stage: 'terraform', error: err });
            });
        }
        var done = function (result) {
            if (args.keep) return reply(true, result);
            restoreLand(saved, function () {
                reply(true, result);
            });
        };
        evaluateOnLand(args, t0, timing, done);
    });
}

function evaluateOnLand(args, t0, timing, reply) {
    createRide(args, function (err, rideId) {
        if (err) return reply({ stage: 'create', error: err });
        var planted = [];
        var finish = function (result) {
            result.ride = rideId;
            result.timing = timing;
            result.decor = planted.length;
            if (args.keep) return reply(result);
            removeDecor(args.decor, planted, function () {
                demolish(rideId, function () {
                    reply(result);
                });
            });
        };
        sequence(args.pieces.length, function (i, next) {
            context.executeAction('trackplace', trackArgs(rideId, args.rideType, args.pieces[i]), function (res) {
                next(res.error ? errText(res) : null);
            });
        }, function (err, failedIndex) {
            timing.buildMs = Date.now() - t0;
            if (err) return finish({ stage: 'build', error: err, index: failedIndex });
            var access = [args.entrance, args.exit];
            sequence(access.length, function (i, next) {
                var a = access[i];
                context.executeAction('rideentranceexitplace', {
                    x: a[0], y: a[1], direction: a[2], ride: rideId, station: 0, isExit: i === 1
                }, function (res) {
                    next(res.error ? errText(res) : null);
                });
            }, function (err, failedIndex) {
                if (err) return finish({ stage: failedIndex === 0 ? 'entrance' : 'exit', error: err });
                setCars(rideId, args.cars, function (err) {
                    if (err) return finish({ stage: 'cars', error: err });
                    setCircuits(rideId, args.circuits, function (err) {
                        if (err) return finish({ stage: 'circuits', error: err });
                        plantDecor(args.decor, planted, function () {
                            startTest(rideId, args, timing, t0, finish);
                        });
                    });
                });
            });
        });
    });
}

// Theme the ride before it is rated: a tree on each planned tile the game accepts
// (args.decor = {identifier, tiles: [[tileX, tileY]]}). Scenery around the station
// and beside the track adds excitement only. `planted` collects [x, y, z] to undo.
var decorObjects = {};

function plantDecor(decor, planted, cb) {
    if (!decor || !decor.tiles || !decor.tiles.length) return cb();
    var index = decorObjects[decor.identifier];
    if (index === undefined) {
        var obj = objectManager.load(decor.identifier);
        index = decorObjects[decor.identifier] = obj ? obj.index : null;
    }
    if (index === null) return cb();
    sequence(decor.tiles.length, function (i, next) {
        var p = decor.tiles[i];
        context.executeAction('smallsceneryplace', {
            x: p[0] * 32, y: p[1] * 32, z: 0, direction: 0, object: index, quadrant: 0,
            primaryColour: 0, secondaryColour: 0, tertiaryColour: 0
        }, function (res) {
            if (!res.error) planted.push([p[0] * 32, p[1] * 32, res.position ? res.position.z : surfaceZ(p[0], p[1])]);
            next(null);
        });
    }, function () {
        cb();
    });
}

function removeDecor(decor, planted, cb) {
    if (!planted.length) return cb();
    var index = decorObjects[decor.identifier];
    sequence(planted.length, function (i, next) {
        var p = planted[i];
        context.executeAction('smallsceneryremove', { x: p[0], y: p[1], z: p[2], object: index, quadrant: 0 }, function () {
            next(null);
        });
    }, function () {
        cb();
    });
}

// Longer trains earn the train-length bonus ((cars - 1) * 2.86 excitement points).
function setCars(rideId, cars, cb) {
    if (!cars) return cb(null);
    context.executeAction('ridesetvehicle', { ride: rideId, type: 1, value: cars, colour: 0 }, function (res) {
        cb(res.error ? errText(res) : null);
    });
}

// Laps per ride: length counts on the first lap only, while time, drops, turns,
// air time and shelter add up over every lap (Vehicle.cpp UpdateMeasurements).
function setCircuits(rideId, circuits, cb) {
    if (!circuits || circuits === 1) return cb(null);
    context.executeAction('ridesetsetting', { ride: rideId, setting: 9, value: circuits }, function (res) {
        cb(res.error ? errText(res) : null);
    });
}

function carsPerTrain(ride) {
    if (!ride.vehicles.length) return 0;
    var n = 0;
    var id = ride.vehicles[0];
    while (id !== null && id !== undefined && n < 100) {
        var car = map.getEntity(id);
        if (!car) break;
        n++;
        id = car.nextCarOnTrain;
    }
    return n;
}

function startTest(rideId, args, timing, t0, finish) {
    context.executeAction('ridesetstatus', { ride: rideId, status: STATUS_TESTING }, function (res) {
        if (res.error) return finish({ stage: 'test_start', error: errText(res) });
        runTest(rideId, args.maxTicks || 20000, function (outcome) {
            timing.totalMs = Date.now() - t0;
            finish(outcome);
        });
    });
}

// A train that cannot clear a hill rolls back and forth over track it has
// already covered. If the lead car reaches no new track tile for this many
// ticks, the test is called off instead of running to maxTicks.
var STALL_TICKS = 1500;

function runTest(rideId, maxTicks, cb) {
    var start = date.ticksElapsed;
    var sub = null;
    var done = false;
    var visited = {};
    var lastNew = start;
    var stop = function (stage) {
        if (done) return;
        done = true;
        if (sub) sub.dispose();
        setPaused(true, function () {
            var ride = map.getRide(rideId);
            var out = { stage: stage, ticks: date.ticksElapsed - start, stats: rideStats(ride) };
            cb(out);
        });
    };
    sub = context.subscribe('interval.tick', function () {
        var ride = map.getRide(rideId);
        if (!ride) return stop('vanished');
        if ((ride.lifecycleFlags & LC_TESTED) && ride.excitement >= 0) return stop('rated');
        if (ride.lifecycleFlags & LC_CRASHED) return stop('crashed');
        if (date.ticksElapsed - start >= maxTicks) return stop('timeout');
        if ((date.ticksElapsed & 15) === 0 && ride.vehicles.length > 0) {
            var car = map.getEntity(ride.vehicles[0]);
            if (car && car.trackLocation) {
                var loc = car.trackLocation;
                // A multi-lap ride covers the same track again after each station pass.
                if (loc.trackType >= 1 && loc.trackType <= 3) visited = {};
                var key = loc.x + ',' + loc.y + ',' + loc.z;
                if (!visited[key]) {
                    visited[key] = true;
                    lastNew = date.ticksElapsed;
                }
            }
        }
        if (date.ticksElapsed - lastNew > STALL_TICKS) return stop('stalled');
    });
    setPaused(false, function () {});
}

function cmdCapture(args, reply) {
    try {
        context.captureImage({
            filename: args.filename,
            width: args.width,
            height: args.height,
            position: args.position,
            zoom: args.zoom || 0,
            rotation: args.rotation || 0,
            transparent: !!args.transparent
        });
        reply(true, { filename: args.filename });
    } catch (e) {
        reply(false, 'captureImage: ' + e);
    }
}

// A hosted (network) game only lets plugins mutate game state inside a game
// action, so saving goes through a custom action.
var SAVE_ACTION = 'rct2loop_save';

function registerActions() {
    context.registerAction(SAVE_ACTION, function () {
        return {};
    }, function (e) {
        context.saveGame({ filename: e.args.filename });
        return {};
    });
}

function cmdSave(args, reply) {
    context.executeAction(SAVE_ACTION, { filename: args.filename }, function (res) {
        if (res.error) return reply(false, 'save: ' + errText(res));
        reply(true, { filename: args.filename });
    });
}

function cmdDemolishAll(args, reply) {
    var ids = [];
    var rides = map.rides;
    for (var i = 0; i < rides.length; i++) ids.push(rides[i].id);
    sequence(ids.length, function (i, next) {
        demolish(ids[i], function () { next(null); });
    }, function () {
        reply(true, { demolished: ids.length });
    });
}

// Shape an experiment area: set flat land heights per tile and plant trees.
// args.tiles = [[tileX, tileY, height]] (height in land units of 8 z),
// args.trees = {identifier, at: [[tileX, tileY]]}.
function cmdTerraform(args, reply) {
    var tiles = args.tiles || [];
    var errors = [];
    sequence(tiles.length, function (i, next) {
        var t = tiles[i];
        context.executeAction('landsetheight', { x: t[0] * 32, y: t[1] * 32, height: t[2], style: 0 }, function (res) {
            if (res.error) errors.push('land ' + t + ': ' + errText(res));
            next(null);
        });
    }, function () {
        setWaterAndOwnership(args, errors, function () {
            plantTrees(args, tiles, errors, reply);
        });
    });
}

// args.water = [[tileX, tileY, heightUnits]], args.ownership = [[tileX, tileY, flags]]
// (flags: 1 construction rights, 2 land owned; 0 unowned).
function setWaterAndOwnership(args, errors, cb) {
    var water = args.water || [];
    var own = args.ownership || [];
    sequence(water.length, function (i, next) {
        var w = water[i];
        context.executeAction('watersetheight', { x: w[0] * 32, y: w[1] * 32, height: w[2] }, function (res) {
            if (res.error) errors.push('water ' + w + ': ' + errText(res));
            next(null);
        });
    }, function () {
        sequence(own.length, function (i, next) {
            var o = own[i];
            context.executeAction('landsetrights', {
                x1: o[0] * 32, y1: o[1] * 32, x2: o[0] * 32, y2: o[1] * 32, setting: 4, ownership: o[2]
            }, function (res) {
                if (res.error) errors.push('ownership ' + o + ': ' + errText(res));
                next(null);
            });
        }, function () {
            cb();
        });
    });
}

function plantTrees(args, tiles, errors, reply) {
    var trees = args.trees;
    if (!trees || !trees.at || !trees.at.length) return reply(true, { tiles: tiles.length, trees: 0, errors: errors });
    var obj = objectManager.load(trees.identifier);
    if (!obj) return reply(false, 'could not load ' + trees.identifier);
    var planted = 0;
    sequence(trees.at.length, function (i, next) {
        var p = trees.at[i];
        context.executeAction('smallsceneryplace', {
            x: p[0] * 32, y: p[1] * 32, z: surfaceZ(p[0], p[1]), direction: 0, object: obj.index, quadrant: 0,
            primaryColour: 0, secondaryColour: 0, tertiaryColour: 0
        }, function (res) {
            if (res.error) errors.push('tree ' + p + ': ' + errText(res));
            else planted++;
            next(null);
        });
    }, function () {
        reply(true, { tiles: tiles.length, trees: planted, errors: errors });
    });
}

function surfaceZ(tx, ty) {
    var tile = map.getTile(tx, ty);
    for (var i = 0; i < tile.numElements; i++) {
        var e = tile.getElement(i);
        if (e.type === 'surface') return e.baseZ;
    }
    return 0;
}

function countScenery(rect) {
    var n = 0;
    for (var x = rect[0]; x < rect[2]; x++) {
        for (var y = rect[1]; y < rect[3]; y++) {
            var tile = map.getTile(x, y);
            for (var i = 0; i < tile.numElements; i++) {
                var type = tile.getElement(i).type;
                if (type === 'small_scenery' || type === 'large_scenery') n++;
            }
        }
    }
    return n;
}

// Describe every tile of a rectangle for the search's pre-filter:
// [tx, ty, surfaceBaseZ, surfaceClearanceZ, slope, waterZ, owned, rights, edge, [[type, baseZ, clearanceZ, ride]]]
function cmdScan(args, reply) {
    var r = args.rect;
    var out = [];
    var sx = map.size.x, sy = map.size.y;
    for (var x = Math.max(0, r[0]); x < Math.min(sx, r[2]); x++) {
        for (var y = Math.max(0, r[1]); y < Math.min(sy, r[3]); y++) {
            var tile = map.getTile(x, y);
            var surf = null;
            var others = [];
            for (var i = 0; i < tile.numElements; i++) {
                var e = tile.getElement(i);
                if (e.type === 'surface') {
                    surf = e;
                } else {
                    others.push([e.type, e.baseZ, e.clearanceZ, e.type === 'track' ? e.ride : -1]);
                }
            }
            var edge = (x <= 1 || y <= 1 || x >= sx - 2 || y >= sy - 2) ? 1 : 0;
            if (!surf) {
                out.push([x, y, 0, 0, 0, 0, 0, 0, 1, others]);
                continue;
            }
            out.push([x, y, surf.baseZ, surf.clearanceZ, surf.slope, surf.waterHeight,
                surf.hasOwnership ? 1 : 0, surf.hasConstructionRights ? 1 : 0, edge, others]);
        }
    }
    reply(true, { mapSize: [sx, sy], tiles: out });
}

function cmdSceneryCount(args, reply) {
    reply(true, { count: countScenery(args.rect) });
}

function cmdTile(args, reply) {
    var tile = map.getTile(args.x, args.y);
    var out = [];
    for (var i = 0; i < tile.numElements; i++) {
        var e = tile.getElement(i);
        var info = { type: e.type, baseZ: e.baseZ, clearanceZ: e.clearanceZ };
        if (e.type === 'surface') info.waterHeight = e.waterHeight;
        if (e.type === 'track') {
            info.trackType = e.trackType;
            info.ride = e.ride;
            info.direction = e.direction;
            info.sequence = e.sequence;
        }
        out.push(info);
    }
    reply(true, out);
}

var COMMANDS = {
    ping: cmdPing,
    setup: cmdSetup,
    segments: cmdSegments,
    load_object: cmdLoadObject,
    installed_rides: cmdInstalledRides,
    ride_objects: cmdRideObjects,
    measure_clearance: cmdMeasureClearance,
    allowed: cmdAllowed,
    evaluate: cmdEvaluate,
    capture: cmdCapture,
    save: cmdSave,
    demolish_all: cmdDemolishAll,
    tile: cmdTile,
    terraform: cmdTerraform,
    scenery_count: cmdSceneryCount,
    scan: cmdScan
};

// ---------------------------------------------------------------- transport

function handle(line, write) {
    var req;
    try {
        req = JSON.parse(line);
    } catch (e) {
        write({ id: null, ok: false, error: 'parse: ' + e });
        return;
    }
    var fn = COMMANDS[req.cmd];
    if (!fn) {
        write({ id: req.id, ok: false, error: 'unknown command: ' + req.cmd });
        return;
    }
    var replied = false;
    try {
        fn(req.args || {}, function (ok, payload) {
            if (replied) return;
            replied = true;
            write(ok ? { id: req.id, ok: true, result: payload } : { id: req.id, ok: false, error: payload });
        });
    } catch (e) {
        if (!replied) {
            replied = true;
            write({ id: req.id, ok: false, error: 'exception: ' + e });
        }
    }
}

function listen() {
    for (var port = PORT_BASE; port < PORT_BASE + 1000; port++) {
        var server = network.createListener();
        try {
            server.listen(port, '127.0.0.1');
        } catch (e) {
            continue;
        }
        server.on('connection', function (socket) {
            var buffer = '';
            socket.setNoDelay(true);
            socket.on('data', function (chunk) {
                buffer += chunk;
                var lines = buffer.split('\n');
                buffer = lines.pop();
                for (var i = 0; i < lines.length; i++) {
                    if (lines[i].length === 0) continue;
                    handle(lines[i], function (msg) {
                        socket.write(JSON.stringify(msg) + '\n');
                    });
                }
            });
            socket.on('error', function () {});
        });
        log('listening on port ' + port);
        return;
    }
    log('ERROR: no free port');
}

registerPlugin({
    name: NAME,
    version: VERSION,
    authors: ['rct2-close-the-loop'],
    type: 'intransient',
    licence: 'MIT',
    targetApiVersion: 110,
    main: function () {
        registerActions();
        listen();
    }
});
