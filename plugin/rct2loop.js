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
    var cheats = [[0, 1], [11, 1], [9, 1], [15, 1], [38, 0]];
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
        status: ride.status
    };
}

function cmdEvaluate(args, reply) {
    var speedBefore = context.gameSpeed;
    ensureSpeed(function (err) {
        if (err) return reply(false, err);
        evaluate(args, function (ok, result) {
            if (ok) result.speedBefore = speedBefore;
            reply(ok, result);
        });
    });
}

function evaluate(args, reply) {
    var t0 = Date.now();
    var timing = {};
    createRide(args, function (err, rideId) {
        if (err) return reply(true, { stage: 'create', error: err });
        var finish = function (result) {
            result.ride = rideId;
            result.timing = timing;
            if (args.keep) return reply(true, result);
            demolish(rideId, function () {
                reply(true, result);
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
                context.executeAction('ridesetstatus', { ride: rideId, status: STATUS_TESTING }, function (res) {
                    if (res.error) return finish({ stage: 'test_start', error: errText(res) });
                    runTest(rideId, args.maxTicks || 20000, function (outcome) {
                        timing.totalMs = Date.now() - t0;
                        finish(outcome);
                    });
                });
            });
        });
    });
}

function runTest(rideId, maxTicks, cb) {
    var start = date.ticksElapsed;
    var sub = null;
    var done = false;
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
    allowed: cmdAllowed,
    evaluate: cmdEvaluate,
    capture: cmdCapture,
    save: cmdSave,
    demolish_all: cmdDemolishAll,
    tile: cmdTile
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
