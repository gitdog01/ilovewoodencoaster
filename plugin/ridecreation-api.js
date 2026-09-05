function main() {
    "use strict";

    // Configuration flags - Edit these to change behavior
    const DEFAULT_PORT = 8080;        // The port this instance serves. See the bind block below.

    // Create TCP listener
    const server = network.createListener();

    server.on("connection", conn => {
        let buffer = "";

        // Handle incoming data on this connection.
        conn.on("data", data => {
            buffer += data;
            // Split messages on newline; we assume one JSON blob per line.
            const lines = buffer.split("\n");
            // If the last element is not empty, it means the last line is incomplete.
            if (lines[lines.length - 1] !== "") {
                buffer = lines.pop();
            } else {
                // All lines complete; clear the buffer.
                buffer = "";
                // Remove the empty string after the trailing newline.
                lines.pop();
            }

            // Process each complete JSON message.
            for (const line of lines) {
                let request;
                try {
                    request = JSON.parse(line);
                } catch (e) {
                    conn.write(JSON.stringify({
                        success: false,
                        error: "Invalid JSON"
                    }) + "\n");
                    continue;
                }

                processRequest(request, response => {
                    // Send the response as a JSON blob followed by a newline.
                    conn.write(JSON.stringify(response) + "\n");
                });
            }
        });
    });

    // Bind the API port. DEFAULT_PORT is pinned per instance instead of being
    // probed, because on Windows a collision is undetectable from inside the
    // game:
    //   - OpenRCT2 sets SO_REUSEADDR on the listening socket, and Windows then
    //     lets several processes bind the SAME port with no error at all. A
    //     "try 8080, catch EADDRINUSE, move to 8081" loop therefore never
    //     advances -- every instance silently lands on 8080 and connections go
    //     to an arbitrary one of them (measured: 3 instances, all on 8080).
    //   - Probing with a client socket first does not work either:
    //     network.createSocket()'s connect callback never fires in this build.
    // To run several instances in parallel, give each its own --user-data-path
    // with a different DEFAULT_PORT here; scripts/setup_instances.py in the
    // ilovewoodencoaster repo generates those copies and a launcher.
    try {
        server.listen(DEFAULT_PORT);
    } catch (e) {
        console.log(`Ride API server could not bind port ${DEFAULT_PORT} (${e}).`);
        return;
    }
    console.log(`Ride API server listening on port ${DEFAULT_PORT}.`);

    // Promise-wrapped context.executeAction. Rejects on result.error so
    // failed actions surface as exceptions in async handlers.
    function executeAction(action, args) {
        return new Promise((resolve, reject) => {
            context.executeAction(action, args, result => {
                if (!result || (result.error && result.error !== "")) {
                    reject(new Error((result && result.error) || "Unknown error"));
                } else {
                    resolve(result);
                }
            });
        });
    }

    // Run an async handler and convert its resolved value / thrown error
    // into the standard {success, payload|error} response shape.
    function runHandler(handlerPromise, callback) {
        handlerPromise
            .then(payload => callback({ success: true, payload }))
            .catch(e => callback({ success: false, error: e && e.message ? e.message : String(e) }));
    }

    // Track state storage (ride ID -> RideState)
    const rideTrackStates = new Map();

    function serializeTrackSegment(s) {
        return {
            type: s.type,
            description: s.description,
            trackGroup: s.trackGroup,
            length: s.length,
            beginZ: s.beginZ,
            endZ: s.endZ,
            beginSlope: s.beginSlope,
            endSlope: s.endSlope,
            beginBank: s.beginBank,
            endBank: s.endBank,
            beginDirection: s.beginDirection,
            endDirection: s.endDirection,
            turnDirection: s.turnDirection,
            slopeDirection: s.slopeDirection,
        };
    }

    // Valid follow-on pieces for a placed piece. Shared by getValidNextPieces
    // and placeTrackPiece so their wire shapes can't drift. Backed by the
    // native ride-type-aware segment.getNextValidSegments(rideId).
    function computeValidNextPieces(rideId, lastPiece) {
        const segment = context.getTrackSegment(lastPiece.trackType);
        if (!segment) throw new Error(`Unknown track segment type: ${lastPiece.trackType}`);
        // getNextValidSegments is missing on some OpenRCT2 builds despite the
        // declared targetApiVersion; degrade to an empty valid-piece list
        // instead of failing the whole call, since `position` below doesn't
        // depend on it and is what placeTrackPiece callers actually need.
        let follows = [];
        if (typeof segment.getNextValidSegments === "function") {
            follows = segment.getNextValidSegments(rideId);
        }
        return {
            validPieces: follows.map(s => s.type),
            validSegments: follows.map(serializeTrackSegment),
            lastTrackType: lastPiece.trackType,
            stateCategory: null,
            position: {
                x: lastPiece.nextX,
                y: lastPiece.nextY,
                z: lastPiece.nextZ,
                direction: lastPiece.nextDirection,
            },
        };
    }

    const endpoints = new Map([
        ["listAllRides",         () => handleListAllRides()],
        ["getAllTrackSegments",  () => handleGetAllTrackSegments()],
        ["deleteAllRides",       () => handleDeleteAllRides()],
        ["startRideTest",        params => handleStartRideTest(params)],
        ["getRideStats",         params => handleGetRideStats(params)],
        ["getRideMeasurements",  params => handleGetRideMeasurements(params)],
        ["setRideVehicles",      params => handleSetRideVehicles(params)],
        ["placeTrackPiece",      params => handlePlaceTrackPiece(params)],
        ["getValidNextPieces",   params => handleGetValidNextPieces(params)],
        ["placeEntranceExit",    params => handlePlaceEntranceExit(params)],
        ["deleteLastTrackPiece", params => handleDeleteLastTrackPiece(params)],
        ["createRide",           params => handleCreateRide(params)],
        ["resetEpisode",         params => handleResetEpisode(params)],
        ["listLoadedRideObjects", () => handleListLoadedRideObjects()],
        ["setGameSpeed",         params => handleSetGameSpeed(params)],
        // Sim-liveness diagnostic: ticks advance ~40/s when the sim runs; frozen
        // ticks mean a paused/never-started park (headless triage, Jul-31).
        ["getTick",              async () => ({ ticks: date.ticksElapsed, monthProgress: date.monthProgress })],
        // Ops bridge: run an in-game console command (e.g. "save_park name") over
        // HTTP -- the stdin REPL needs a TTY that headless/nohup setups lack.
        ["execLegacy",           async params => {
            if (!params || typeof params.command !== "string") throw new Error("Missing parameter: command");
            console.executeLegacy(params.command);
            return { executed: params.command };
        }],
        ["captureImage",         params => handleCaptureImage(params)],
    ]);

    /**
     * Dispatches a JSON request to its endpoint handler.
     * Looks up endpoint by name in the `endpoints` Map and calls
     * the matching async handler. Resolved values become
     * {success: true, payload}; thrown errors become {success: false, error}.
     */
    function processRequest(request, callback) {
        if (!request.endpoint) {
            callback({ success: false, error: "Missing endpoint" });
            return;
        }
        const handler = endpoints.get(request.endpoint);
        if (!handler) {
            callback({ success: false, error: `Unknown endpoint: ${request.endpoint}` });
            return;
        }
        runHandler(handler(request.params), callback);
    }

    /**
     * Sets the game simulation speed via the built-in "gamesetspeed" action.
     * Ride ratings need ~35s of SIM time on a small circuit; the RL trainer requests
     * speed 8 so ride tests resolve in ~4-5s of wall clock. speed: 1..4, or 8 (hyper).
     */
    async function handleSetGameSpeed(params) {
        const speed = params && params.speed ? Number(params.speed) : 1;
        context.executeAction("gamesetspeed", { speed: speed }, () => {});
        return { speed: speed };
    }

    /**
     * Renders the current map to a screenshot file via context.captureImage().
     * The 114 scripting API has no park-save function, headless instances have
     * no writable stdin, and this plugin speaks raw TCP JSON rather than HTTP --
     * so there is no other way to see what a headless instance built. This is
     * the escape hatch a human uses to inspect an agent's gallery park.
     *
     * COORDINATE-UNIT DECISION: `tileX`/`tileY` here are TILE coordinates, the
     * same units every other endpoint in this file takes (e.g.
     * placeTrackPiece's tileCoordinateX/Y) -- NOT the map units
     * CaptureOptions.position expects natively (32 map units per tile; see
     * CoordsXY in openrct2.d.ts). We convert by *32 below so callers use one
     * consistent unit across the whole API; a silent factor-of-32 miss would
     * centre the shot on empty land and look like a broken feature rather than
     * a units bug.
     *
     * `zoom` and `rotation` are both REQUIRED by the native binding
     * (ScContext::captureImage throws "Invalid options." if either is missing,
     * matching openrct2.d.ts where neither field carries a `?`) -- both are
     * defaulted below so an omission never reaches the engine as undefined.
     * The same native binding also only honours `position` when `width` and
     * `height` are supplied alongside it (position without both throws
     * "Invalid options." there too), so that pairing is validated here for a
     * clearer error than the engine gives.
     */
    async function handleCaptureImage(params) {
        const p = params || {};

        const options = {
            zoom: typeof p.zoom === "number" ? p.zoom : 0, // 0 = 1:1
            rotation: typeof p.rotation === "number" ? p.rotation : 0,
        };
        if (typeof p.transparent === "boolean") options.transparent = p.transparent;

        if (typeof p.tileX === "number" && typeof p.tileY === "number") {
            if (typeof p.width !== "number" || typeof p.height !== "number") {
                throw new Error("captureImage: width and height are required together with tileX/tileY");
            }
            options.width = p.width;
            options.height = p.height;
            options.position = { x: p.tileX * 32, y: p.tileY * 32 }; // tiles -> map units
        }

        // Always pick the filename ourselves (rather than relying on the
        // engine's own auto-naming) so the response can tell the caller
        // exactly which file to look for.
        options.filename = (typeof p.filename === "string" && p.filename)
            ? p.filename
            : `capture_${Date.now()}.png`;

        try {
            context.captureImage(options);
        } catch (e) {
            throw new Error(`Failed to capture image: ${e.message}`);
        }
        return { filename: options.filename };
    }

    async function handleListAllRides() {
        const ridesArray = [];
        map.rides.forEach(ride => {
            ridesArray.push({ id: ride.id, name: ride.name, type: ride.type });
        });
        return ridesArray;
    }

    async function handleListLoadedRideObjects() {
        const all = objectManager.getAllObjects("ride");
        return all.map(o => ({
            index: o.index,
            identifier: o.identifier,
            name: o.name,
            rideType: o.rideType,
        }));
    }

    async function handleGetAllTrackSegments() {
        return context.getAllTrackSegments().map(serializeTrackSegment);
    }

    async function handleGetRideStats(params) {
        const { rideId } = params || {};
        if (typeof rideId !== "number") throw new Error("Missing or invalid parameter: rideId");
        const ride = map.getRide(rideId);
        if (!ride) throw new Error("Ride not found");
        return {
            excitement: ride.excitement / 100,
            intensity: ride.intensity / 100,
            nausea: ride.nausea / 100,
        };
    }

    /**
     * Test-run measurements for the RL reward's rating-cap ramps. All values come from
     * the scripting bindings' registered Ride properties (already unit-converted there:
     * speeds in display mph, rideLength in metres, G's in g, totalAirTime in seconds,
     * highestDropHeight in raw z-steps). Turn counts and shelteredLength are NOT
     * registered on ScRide, hence absent here (env-side static counters cover turns).
     */
    async function handleGetRideMeasurements(params) {
        const { rideId } = params || {};
        if (typeof rideId !== "number") throw new Error("Missing or invalid parameter: rideId");
        const ride = map.getRide(rideId);
        if (!ride) throw new Error("Ride not found");
        return {
            excitement: ride.excitement / 100,
            intensity: ride.intensity / 100,
            nausea: ride.nausea / 100,
            maxSpeed: ride.maxSpeed,
            averageSpeed: ride.averageSpeed,
            rideTime: ride.rideTime,
            rideLength: ride.rideLength,
            maxPositiveVerticalGs: ride.maxPositiveVerticalGs,
            maxNegativeVerticalGs: ride.maxNegativeVerticalGs,
            maxLateralGs: ride.maxLateralGs,
            totalAirTime: ride.totalAirTime,
            numDrops: ride.numDrops,
            highestDropHeight: ride.highestDropHeight,
        };
    }

    /**
     * Sets the test train's consist via the built-in "ridesetvehicle" action.
     * type: 0 = number of trains, 1 = cars per train. The rating's BonusTrainLength
     * pays excitement per extra car, the largest track-independent term left once
     * template geometry saturates (measured E ceiling ~5.86 on Jul-12).
     */
    async function handleSetRideVehicles(params) {
        const { rideId, numCarsPerTrain, numTrains } = params || {};
        if (typeof rideId !== "number") throw new Error("Missing or invalid parameter: rideId");
        if (typeof numCarsPerTrain === "number") {
            await executeAction("ridesetvehicle", { ride: rideId, type: 1, value: numCarsPerTrain });
        }
        if (typeof numTrains === "number") {
            await executeAction("ridesetvehicle", { ride: rideId, type: 0, value: numTrains });
        }
        const ride = map.getRide(rideId);
        return { rideId: rideId, applied: true,
                 vehicles: ride && ride.vehicles ? ride.vehicles.length : null };
    }

    async function handleStartRideTest(params) {
        const { rideId } = params || {};
        if (typeof rideId !== "number") throw new Error("Missing or invalid parameter: rideId");
        try {
            await executeAction("ridesetstatus", { ride: rideId, status: 2 });
        } catch (e) {
            throw new Error(`Failed to start ride test: ${e.message}`);
        }
        return `Ride ${rideId} started in test mode.`;
    }

    async function handleCreateRide(params) {
        if (!params
            || typeof params.rideType !== "number"
            || typeof params.rideObject !== "number"
            || typeof params.entranceObject !== "number"
            || typeof params.colour1 !== "number"
            || typeof params.colour2 !== "number") {
            throw new Error("Missing or invalid parameters for createRide");
        }
        let result;
        try {
            result = await executeAction("ridecreate", {
                rideType: params.rideType,
                rideObject: params.rideObject,
                entranceObject: params.entranceObject,
                colour1: params.colour1,
                colour2: params.colour2,
                inspectionInterval: typeof params.inspectionInterval === "number" ? params.inspectionInterval : 2,
            });
        } catch (e) {
            throw new Error(`Failed to create ride: ${e.message}`);
        }
        if (typeof result.ride !== "number") throw new Error("Failed to create ride: no ride id returned");
        rideTrackStates.set(result.ride, { history: [] });
        console.log(`Initialized fresh track state for ride ${result.ride}`);
        return { rideId: result.ride };
    }

    // One-round-trip episode reset: clean slate + fresh ride + full station build, returning the
    // post-station head and the valid follow-on pieces. The station is built by calling
    // handlePlaceTrackPiece per piece -- the SAME path the client used for its N separate calls --
    // so state.history, state.firstPiece, isComplete and validNextPieces are recorded identically
    // (keeping getValidNextPieces, deleteLastTrackPiece and circuit-completion correct). This just
    // moves the per-piece loop from the client (N network round-trips) to the server (one).
    async function handleResetEpisode(params) {
        const p = params || {};
        const stationLength = (typeof p.stationLength === "number" && p.stationLength > 0) ? p.stationLength : 6;
        const startX = (typeof p.startX === "number") ? p.startX : 61;
        const startY = (typeof p.startY === "number") ? p.startY : 66;
        const startZ = (typeof p.startZ === "number") ? p.startZ : 14;
        const startDir = (typeof p.startDir === "number") ? p.startDir : 0;
        const rideType = (typeof p.rideType === "number") ? p.rideType : 52;

        // 1) Clean slate (also clears rideTrackStates for the demolished rides).
        await handleDeleteAllRides();

        // 2) Fresh ride.
        // rideObject is an INDEX into the loaded-object list and scan order is
        // machine-dependent (on one host index 0 was a Balloon Stall: rides built
        // but no train could dispatch, so nothing ever rated). The client resolves
        // the right index via listLoadedRideObjects and passes it here.
        const created = await handleCreateRide({
            rideType: rideType,
            rideObject: (typeof p.rideObject === "number") ? p.rideObject : 0,
            entranceObject: 0,
            colour1: 0,
            colour2: 1,
        });
        const rideId = created.rideId;

        // 3) Build the station through the normal placeTrackPiece path, chaining each piece off
        //    the previous nextEndpoint exactly as the legacy client did.
        let curX = startX, curY = startY, curZ = startZ, curDir = startDir;
        let lastPlaced = null;
        for (let i = 0; i < stationLength; i++) {
            const trackType = (i === 0) ? 2 : (i === stationLength - 1) ? 1 : 3; // Begin / Middle / End
            lastPlaced = await handlePlaceTrackPiece({
                tileCoordinateX: curX,
                tileCoordinateY: curY,
                tileCoordinateZ: curZ,
                direction: curDir,
                ride: rideId,
                trackType: trackType,
                rideType: rideType,
                brakeSpeed: 0,
                colour: 0,
                seatRotation: 0,
                trackPlaceFlags: 0,
                isFromTrackDesign: true,
                hasChainLift: false,
            });
            const ep = lastPlaced.nextEndpoint;
            curX = ep.x; curY = ep.y; curZ = ep.z; curDir = ep.direction;
        }

        return {
            rideId: rideId,
            finalEndpoint: { x: curX, y: curY, z: curZ, direction: curDir },
            validNextPieces: lastPlaced ? lastPlaced.validNextPieces : null,
        };
    }

    async function handleDeleteAllRides() {
        const rides = [];
        map.rides.forEach(r => rides.push(r));
        if (rides.length === 0) return "No rides to delete.";
        for (const ride of rides) {
            try {
                await executeAction("ridedemolish", { ride: ride.id, modifyType: 0 });
                rideTrackStates.delete(ride.id);
                console.log(`Cleared track state for deleted ride ${ride.id}`);
            } catch (e) {
                console.log(`Error demolishing ride ${ride.id}: ${e.message}`);
            }
        }
        return "Deleted all rides.";
    }

    async function handleGetValidNextPieces(params) {
        const { rideId } = params || {};
        if (typeof rideId !== "number") throw new Error("Missing or invalid parameter: rideId");
        if (!map.getRide(rideId)) throw new Error(`Ride ${rideId} not found`);

        const state = rideTrackStates.get(rideId);
        if (!state || !state.history || state.history.length === 0) {
            // Conservative fresh-start list: Flat, EndStation, BeginStation, MiddleStation.
            // context.getAllTrackSegments() is not ride-type-filtered, so we cannot
            // safely widen this without a dedicated upstream API.
            const initialTypes = [0, 1, 2, 3];
            const initialSegments = initialTypes
                .map(t => context.getTrackSegment(t))
                .filter(s => s)
                .map(serializeTrackSegment);
            return {
                validPieces: initialTypes,
                validSegments: initialSegments,
                lastTrackType: null,
                stateCategory: null,
                position: null,
            };
        }

        const lastPiece = state.history[state.history.length - 1];
        return computeValidNextPieces(rideId, lastPiece);
    }

    async function handleDeleteLastTrackPiece(params) {
        const { rideId } = params || {};
        if (typeof rideId !== "number") throw new Error("Missing or invalid parameter: rideId");
        const state = rideTrackStates.get(rideId);
        if (!state || !state.history || state.history.length === 0) {
            throw new Error(`No track pieces to delete for ride ${rideId}`);
        }
        const lastPiece = state.history[state.history.length - 1];
        console.log(
            `Attempting to remove track piece at tile: ${lastPiece.placedTileX} ${lastPiece.placedTileY} ` +
            `element index: ${lastPiece.elementIndex} trackType: ${lastPiece.trackType}`
        );
        try {
            await executeAction("trackremove", {
                x: lastPiece.placedTileX * 32,
                y: lastPiece.placedTileY * 32,
                z: lastPiece.z * 8,
                direction: lastPiece.direction,
                trackType: lastPiece.trackType,
                sequence: 0,
            });
        } catch (e) {
            console.log(`Failed to remove track piece: ${e.message}`);
            throw new Error(`Failed to remove track piece: ${e.message}`);
        }
        console.log("Successfully removed track piece");
        state.history.pop();
        if (state.history.length === 0) {
            state.firstPiece = null;
            state.isComplete = false;
        }
        const response = {
            message: `Track piece removed from ride ${rideId}`,
            piecesRemaining: state.history.length,
            nextEndpoint: null,
            lastTrackType: null,
        };
        if (state.history.length > 0) {
            const newLast = state.history[state.history.length - 1];
            response.nextEndpoint = {
                x: newLast.nextX,
                y: newLast.nextY,
                z: newLast.nextZ,
                direction: newLast.nextDirection,
            };
            response.lastTrackType = newLast.trackType;
            // Fold valid follow-on pieces into the delete response (mirrors placeTrackPiece) so the
            // client keeps its valid-piece cache warm and skips a getValidNextPieces round-trip
            // after every remove.
            response.validNextPieces = computeValidNextPieces(rideId, newLast);
        } else {
            // No pieces left: hand back the same conservative fresh-start list as
            // getValidNextPieces' empty-history branch, so the cache still stays warm.
            const initialTypes = [0, 1, 2, 3];
            response.validNextPieces = {
                validPieces: initialTypes,
                validSegments: initialTypes
                    .map(t => context.getTrackSegment(t))
                    .filter(s => s)
                    .map(serializeTrackSegment),
                lastTrackType: null,
                stateCategory: null,
                position: null,
            };
        }
        return response;
    }

    // Search for the just-placed track element. First checks the central tile
    // with tolerance 8, then falls back to all 9 surrounding tiles (including
    // the center) with tolerance 16. Matches on ride id AND the freshly
    // requested trackType / direction / sequence===0 so we lock onto the
    // newly placed origin tile rather than a stale neighbour element on
    // dense or self-overlapping track. Returns { tile, element, elementIndex,
    // tileX, tileY } or null.
    // OpenRCT2 stores all station segment types (BeginStation=2,
    // MiddleStation=3, EndStation=1) as a single canonical station element
    // type (1). Other track types are stored unchanged. We canonicalize both
    // sides before comparing so a freshly placed BeginStation still matches.
    function canonicalTrackType(t) {
        return (t === 1 || t === 2 || t === 3) ? 1 : t;
    }

    function findPlacedTrackElement(rideId, trackType, direction, resultPosition) {
        const placedTileZ = resultPosition.z;
        const baseX = Math.floor(resultPosition.x / 32);
        const baseY = Math.floor(resultPosition.y / 32);
        const wantType = canonicalTrackType(trackType);

        const offsets = [
            [0, 0], [-1, 0], [1, 0], [0, -1], [0, 1],
            [-1, -1], [-1, 1], [1, -1], [1, 1],
        ];

        function matches(elem, tolerance) {
            if (elem.type !== "track" || elem.ride !== rideId) return false;
            if (Math.abs(elem.baseZ - placedTileZ) > tolerance) return false;
            if (canonicalTrackType(elem.trackType) !== wantType) return false;
            if (elem.direction !== direction) return false;
            // sequence may be undefined on older API versions; when present it
            // must be 0 to lock onto the origin tile of a multi-tile piece.
            if (typeof elem.sequence === "number" && elem.sequence !== 0) return false;
            return true;
        }

        function scan(tolerance, onlyCenter) {
            const list = onlyCenter ? [[0, 0]] : offsets;
            for (const [dx, dy] of list) {
                const tx = baseX + dx;
                const ty = baseY + dy;
                const tile = map.getTile(tx, ty);
                if (!tile) continue;
                for (let i = 0; i < tile.numElements; i++) {
                    if (matches(tile.elements[i], tolerance)) {
                        return { tile, element: tile.elements[i], elementIndex: i, tileX: tx, tileY: ty };
                    }
                }
            }
            return null;
        }

        return scan(8, true) || scan(16, false);
    }

    async function handlePlaceTrackPiece(params) {
        const requiredParams = [
            "tileCoordinateX", "tileCoordinateY", "tileCoordinateZ", "direction", "ride",
            "trackType", "rideType", "brakeSpeed", "colour",
            "seatRotation", "trackPlaceFlags", "isFromTrackDesign",
        ];
        if (!params) throw new Error("Missing parameters for placeTrackPiece");
        for (const key of requiredParams) {
            if (typeof params[key] === "undefined") throw new Error(`Missing parameter: ${key}`);
        }

        // Continuity check: a placement must chain off the previous piece's
        // nextEndpoint. The trackplace action's z is the segment's base z,
        // but nextEndpoint.z is the train's entry z (high edge for descending
        // pieces). We translate via segment.beginZ (game units, 8 per tileZ)
        // so the comparison is apples-to-apples.
        const requestedSegment = context.getTrackSegment(params.trackType);
        if (!requestedSegment) throw new Error(`Unknown trackType: ${params.trackType}`);
        const requestedTrainEntryZ = params.tileCoordinateZ + (requestedSegment.beginZ / 8);
        const existingState = rideTrackStates.get(params.ride);
        if (existingState && existingState.history && existingState.history.length > 0) {
            const last = existingState.history[existingState.history.length - 1];
            if (params.tileCoordinateX !== last.nextX
                || params.tileCoordinateY !== last.nextY
                || requestedTrainEntryZ !== last.nextZ
                || params.direction !== last.nextDirection) {
                throw new Error(
                    `Placement does not continue from previous piece: `
                    + `train entry would be (${params.tileCoordinateX},${params.tileCoordinateY},${requestedTrainEntryZ}) dir=${params.direction}, `
                    + `previous piece ends at (${last.nextX},${last.nextY},${last.nextZ}) dir=${last.nextDirection}`,
                );
            }
        }

        const pixelCoordinateX = params.tileCoordinateX * 32;
        const pixelCoordinateY = params.tileCoordinateY * 32;
        const pixelCoordinateZ = params.tileCoordinateZ * 8;
        let flags = params.trackPlaceFlags;
        if (params.hasChainLift === true) flags = flags | 1;

        const isStationPiece = (params.trackType === 1 || params.trackType === 2 || params.trackType === 3);
        if (isStationPiece) {
            console.log(`Station piece placed - Type: ${params.trackType} for ride ${params.ride}`);
            console.log("Note: Use placeEntranceExit endpoint to add entrance/exit after station is complete");
        }

        let result;
        try {
            result = await executeAction("trackplace", {
                x: pixelCoordinateX,
                y: pixelCoordinateY,
                z: pixelCoordinateZ,
                direction: params.direction,
                ride: params.ride,
                trackType: params.trackType,
                rideType: params.rideType,
                brakeSpeed: params.brakeSpeed,
                colour: params.colour,
                seatRotation: params.seatRotation,
                trackPlaceFlags: flags,
                isFromTrackDesign: params.isFromTrackDesign,
            });
        } catch (e) {
            throw new Error(`Failed to place track piece: ${e.message}`);
        }

        console.log(`Track placed successfully at result position: ${JSON.stringify(result.position)}`);

        const placedTileX = Math.floor(result.position.x / 32);
        const placedTileY = Math.floor(result.position.y / 32);
        if (!map.getTile(placedTileX, placedTileY)) {
            throw new Error("Tile not found at placed position");
        }

        const placed = findPlacedTrackElement(params.ride, params.trackType, params.direction, result.position);
        if (!placed) throw new Error("Could not find track element on any nearby tile");
        console.log(`Found track element at index: ${placed.elementIndex} on tile: ${placed.tileX} ${placed.tileY}`);

        const iteratorPos = { x: placed.tileX * 32, y: placed.tileY * 32 };
        const iterator = map.getTrackIterator(iteratorPos, placed.elementIndex);
        if (!iterator) throw new Error("Track iterator not available");

        if (!iterator.nextPosition) {
            console.log("WARNING: Iterator exists but nextPosition is null. Track type:", placed.element.trackType);
            if (typeof iterator.next === "function") {
                iterator.next();
                if (!iterator.nextPosition) throw new Error("Track has no valid next position");
            } else {
                throw new Error("Track has no next position available");
            }
        }

        const nextTileX = Math.round(iterator.nextPosition.x / 32);
        const nextTileY = Math.round(iterator.nextPosition.y / 32);
        const nextTileZ = iterator.nextPosition.z / 8;
        const nextDirection = iterator.nextPosition.direction;

        // Initialize state if missing (e.g. ride created outside our flow).
        let state = rideTrackStates.get(params.ride);
        if (!state) {
            state = { history: [] };
            rideTrackStates.set(params.ride, state);
        }
        // Record first piece's canonical input position, for circuit detection.
        // We use iterator.position (the placed segment's canonical input from
        // the engine) rather than the raw request params so direction masking
        // / coord normalization done by the engine can't cause subtle
        // mismatches against future nextEndpoint comparisons.
        if (!state.firstPiece) {
            state.firstPiece = {
                x: Math.round(iterator.position.x / 32),
                y: Math.round(iterator.position.y / 32),
                z: iterator.position.z / 8,
                direction: iterator.position.direction,
            };
        }

        const isCircuitComplete = (
            state.firstPiece
            && nextTileX === state.firstPiece.x
            && nextTileY === state.firstPiece.y
            && nextTileZ === state.firstPiece.z
            && nextDirection === state.firstPiece.direction
        );

        if (isCircuitComplete) {
            console.log("CIRCUIT COMPLETE! Track successfully connects back to station.");
        }

        state.history.push({
            x: params.tileCoordinateX,
            y: params.tileCoordinateY,
            z: params.tileCoordinateZ,
            direction: params.direction,
            trackType: params.trackType,
            nextX: nextTileX,
            nextY: nextTileY,
            nextZ: nextTileZ,
            nextDirection,
            elementIndex: placed.elementIndex,
            placedTileX: placed.tileX,
            placedTileY: placed.tileY,
        });
        state.isComplete = isCircuitComplete;

        const responsePayload = {
            message: `Track piece placed for ride ${params.ride}`,
            nextEndpoint: { x: nextTileX, y: nextTileY, z: nextTileZ, direction: nextDirection },
            isCircuitComplete,
            circuitMessage: isCircuitComplete
                ? "Circuit complete! Track connects back to station - ready for testing!"
                : "Continue building...",
            debug: {
                placedAt: { x: placed.tileX, y: placed.tileY, z: result.position.z },
                trackType: params.trackType,
                elemDirection: placed.element.direction,
            },
        };
        // Fold the valid follow-on pieces into the place response so clients can
        // chain construction without a separate getValidNextPieces round-trip.
        // The just-placed piece is the new history tail.
        const justPlaced = state.history[state.history.length - 1];
        responsePayload.validNextPieces = computeValidNextPieces(params.ride, justPlaced);
        if (isStationPiece) responsePayload.stationDetected = true;
        return responsePayload;
    }

    function findStationPieces(rideId) {
        const stationPieces = [];
        for (let x = 0; x < map.size.x; x++) {
            for (let y = 0; y < map.size.y; y++) {
                const tile = map.getTile(x, y);
                if (!tile) continue;
                for (let i = 0; i < tile.numElements; i++) {
                    const elem = tile.elements[i];
                    if (elem.type === "track" && elem.ride === rideId
                        && (elem.trackType === 1 || elem.trackType === 2 || elem.trackType === 3)) {
                        stationPieces.push({
                            x, y,
                            z: elem.baseZ,
                            direction: elem.direction,
                            trackType: elem.trackType,
                        });
                        console.log(`Found station piece at ${x} ${y} direction: ${elem.direction} type: ${elem.trackType}`);
                    }
                }
            }
        }
        return stationPieces;
    }

    function entranceExitPositionsFor(stationTile) {
        const dir = stationTile.direction;
        if (dir === 0 || dir === 2) {
            // Track runs east-west, place perpendicular north-south
            return {
                entrance: { x: stationTile.x, y: stationTile.y - 1, direction: 3 },
                exit:     { x: stationTile.x, y: stationTile.y + 1, direction: 1 },
            };
        }
        // Track runs north-south, place perpendicular east-west
        return {
            entrance: { x: stationTile.x - 1, y: stationTile.y, direction: 2 },
            exit:     { x: stationTile.x + 1, y: stationTile.y, direction: 0 },
        };
    }

    async function tryPlaceEntranceOrExit(rideId, position, isExit) {
        try {
            await executeAction("rideentranceexitplace", {
                x: position.x * 32,
                y: position.y * 32,
                direction: position.direction,
                ride: rideId,
                station: 0,
                isExit,
            });
            console.log(`Successfully placed ${isExit ? "exit" : "entrance"} at ${position.x} ${position.y}`);
            return { x: position.x, y: position.y, direction: position.direction };
        } catch (e) {
            console.log(`Failed to place ${isExit ? "exit" : "entrance"} at ${position.x} ${position.y}: ${e.message}`);
            return null;
        }
    }

    async function handlePlaceEntranceExit(params) {
        const { rideId } = params || {};
        if (typeof rideId !== "number") throw new Error("Missing or invalid parameter: rideId");

        if (!map.getRide(rideId)) throw new Error(`Ride ${rideId} not found`);

        const stationPieces = findStationPieces(rideId);
        if (stationPieces.length === 0) throw new Error(`No station pieces found for ride ${rideId}`);
        console.log(`Found ${stationPieces.length} station pieces total`);

        let entrance = null, exit = null;
        for (let i = 0; i < stationPieces.length; i++) {
            const positions = entranceExitPositionsFor(stationPieces[i]);
            if (!entrance) entrance = await tryPlaceEntranceOrExit(rideId, positions.entrance, false);
            if (!exit)     exit     = await tryPlaceEntranceOrExit(rideId, positions.exit, true);
            if (entrance && exit) break;
        }

        if (entrance && exit) {
            return { entrance, exit, message: "Successfully placed entrance and exit" };
        }
        if (entrance || exit) {
            return {
                entrance, exit,
                warning: "Only partially successful - "
                    + (!entrance ? "Could not place entrance. " : "")
                    + (!exit ? "Could not place exit." : ""),
            };
        }
        throw new Error("Failed to place entrance and exit. No valid positions found near any station piece.");
    }
}

// Register the plugin
registerPlugin({
    name: "Ride Creation API Plugin",
    version: "0.6",
    authors: ["Markus"],
    type: "intransient",
    licence: "MIT",
    minApiVersion: 114,
    targetApiVersion: 114,
    main: main
});
