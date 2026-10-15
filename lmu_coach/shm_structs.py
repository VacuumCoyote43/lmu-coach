"""Estructuras ctypes de la memoria compartida nativa de LMU ("LMU_Data").

Traducidas a mano de Support/SharedMemoryInterface/*.hpp del juego.
Los structs de InternalsPlugin.hpp usan #pragma pack(4); los de
SharedMemoryInterface.hpp usan el empaquetado por defecto (8 en x64).
"""
import ctypes as C

SME_MAX = 16
MAX_PATH = 260
MAX_VEHICLES = 104


class Vec3(C.Structure):
    _pack_ = 4
    _fields_ = [("x", C.c_double), ("y", C.c_double), ("z", C.c_double)]


class TelemWheelV01(C.Structure):
    _pack_ = 4
    _fields_ = [
        ("mSuspensionDeflection", C.c_double),
        ("mRideHeight", C.c_double),
        ("mSuspForce", C.c_double),
        ("mBrakeTemp", C.c_double),
        ("mBrakePressure", C.c_double),
        ("mRotation", C.c_double),
        ("mLateralPatchVel", C.c_double),
        ("mLongitudinalPatchVel", C.c_double),
        ("mLateralGroundVel", C.c_double),
        ("mLongitudinalGroundVel", C.c_double),
        ("mCamber", C.c_double),
        ("mLateralForce", C.c_double),
        ("mLongitudinalForce", C.c_double),
        ("mTireLoad", C.c_double),
        ("mGripFract", C.c_double),
        ("mPressure", C.c_double),
        ("mTemperature", C.c_double * 3),
        ("mWear", C.c_double),
        ("mTerrainName", C.c_char * 16),
        ("mSurfaceType", C.c_ubyte),
        ("mFlat", C.c_bool),
        ("mDetached", C.c_bool),
        ("mStaticUndeflectedRadius", C.c_ubyte),
        ("mVerticalTireDeflection", C.c_double),
        ("mWheelYLocation", C.c_double),
        ("mToe", C.c_double),
        ("mTireCarcassTemperature", C.c_double),
        ("mTireInnerLayerTemperature", C.c_double * 3),
        ("mOptimalTemp", C.c_float),
        ("mCompoundIndex", C.c_ubyte),
        ("mCompoundType", C.c_ubyte),
        ("mExpansion", C.c_ubyte * 18),
    ]


class TelemInfoV01(C.Structure):
    _pack_ = 4
    _fields_ = [
        ("mID", C.c_long),
        ("mDeltaTime", C.c_double),
        ("mElapsedTime", C.c_double),
        ("mLapNumber", C.c_long),
        ("mLapStartET", C.c_double),
        ("mVehicleName", C.c_char * 64),
        ("mTrackName", C.c_char * 64),
        ("mPos", Vec3),
        ("mLocalVel", Vec3),
        ("mLocalAccel", Vec3),
        ("mOri", Vec3 * 3),
        ("mLocalRot", Vec3),
        ("mLocalRotAccel", Vec3),
        ("mGear", C.c_long),
        ("mEngineRPM", C.c_double),
        ("mEngineWaterTemp", C.c_double),
        ("mEngineOilTemp", C.c_double),
        ("mClutchRPM", C.c_double),
        ("mUnfilteredThrottle", C.c_double),
        ("mUnfilteredBrake", C.c_double),
        ("mUnfilteredSteering", C.c_double),
        ("mUnfilteredClutch", C.c_double),
        ("mFilteredThrottle", C.c_double),
        ("mFilteredBrake", C.c_double),
        ("mFilteredSteering", C.c_double),
        ("mFilteredClutch", C.c_double),
        ("mSteeringShaftTorque", C.c_double),
        ("mFront3rdDeflection", C.c_double),
        ("mRear3rdDeflection", C.c_double),
        ("mFrontWingHeight", C.c_double),
        ("mFrontRideHeight", C.c_double),
        ("mRearRideHeight", C.c_double),
        ("mDrag", C.c_double),
        ("mFrontDownforce", C.c_double),
        ("mRearDownforce", C.c_double),
        ("mFuel", C.c_double),
        ("mEngineMaxRPM", C.c_double),
        ("mScheduledStops", C.c_ubyte),
        ("mOverheating", C.c_bool),
        ("mDetached", C.c_bool),
        ("mHeadlights", C.c_bool),
        ("mDentSeverity", C.c_ubyte * 8),
        ("mLastImpactET", C.c_double),
        ("mLastImpactMagnitude", C.c_double),
        ("mLastImpactPos", Vec3),
        ("mEngineTorque", C.c_double),
        ("mCurrentSector", C.c_long),
        ("mSpeedLimiter", C.c_ubyte),
        ("mMaxGears", C.c_ubyte),
        ("mFrontTireCompoundIndex", C.c_ubyte),
        ("mRearTireCompoundIndex", C.c_ubyte),
        ("mFuelCapacity", C.c_double),
        ("mFrontFlapActivated", C.c_ubyte),
        ("mRearFlapActivated", C.c_ubyte),
        ("mRearFlapLegalStatus", C.c_ubyte),
        ("mIgnitionStarter", C.c_ubyte),
        ("mFrontTireCompoundName", C.c_char * 18),
        ("mRearTireCompoundName", C.c_char * 18),
        ("mSpeedLimiterAvailable", C.c_ubyte),
        ("mAntiStallActivated", C.c_ubyte),
        ("mUnused", C.c_ubyte * 2),
        ("mVisualSteeringWheelRange", C.c_float),
        ("mRearBrakeBias", C.c_double),
        ("mTurboBoostPressure", C.c_double),
        ("mPhysicsToGraphicsOffset", C.c_float * 3),
        ("mPhysicalSteeringWheelRange", C.c_float),
        ("mDeltaBest", C.c_double),
        ("mBatteryChargeFraction", C.c_double),
        ("mElectricBoostMotorTorque", C.c_double),
        ("mElectricBoostMotorRPM", C.c_double),
        ("mElectricBoostMotorTemperature", C.c_double),
        ("mElectricBoostWaterTemperature", C.c_double),
        ("mElectricBoostMotorState", C.c_ubyte),
        ("mLapInvalidated", C.c_bool),
        ("mABSActive", C.c_bool),
        ("mTCActive", C.c_bool),
        ("mSpeedLimiterActive", C.c_bool),
        ("mWiperState", C.c_uint8),
        ("mTC", C.c_uint8),
        ("mTCMax", C.c_uint8),
        ("mTCSlip", C.c_uint8),
        ("mTCSlipMax", C.c_uint8),
        ("mTCCut", C.c_uint8),
        ("mTCCutMax", C.c_uint8),
        ("mABS", C.c_uint8),
        ("mABSMax", C.c_uint8),
        ("mMotorMap", C.c_uint8),
        ("mMotorMapMax", C.c_uint8),
        ("mMigration", C.c_uint8),
        ("mMigrationMax", C.c_uint8),
        ("mFrontAntiSway", C.c_uint8),
        ("mFrontAntiSwayMax", C.c_uint8),
        ("mRearAntiSway", C.c_uint8),
        ("mRearAntiSwayMax", C.c_uint8),
        ("mLiftAndCoastProgress", C.c_uint8),
        ("mTrackLimitsSteps", C.c_uint8),
        ("mRegen", C.c_float),
        ("mSoC", C.c_float),
        ("mVirtualEnergy", C.c_float),
        ("mTimeGapCarAhead", C.c_float),
        ("mTimeGapCarBehind", C.c_float),
        ("mTimeGapPlaceAhead", C.c_float),
        ("mTimeGapPlaceBehind", C.c_float),
        ("mVehicleModel", C.c_char * 30),
        ("mVehicleClass", C.c_uint8),
        ("mVehicleChampionship", C.c_uint8),
        ("mExpansion", C.c_ubyte * 20),
        ("mWheel", TelemWheelV01 * 4),
    ]


class VehicleScoringInfoV01(C.Structure):
    _pack_ = 4
    _fields_ = [
        ("mID", C.c_long),
        ("mDriverName", C.c_char * 32),
        ("mVehicleName", C.c_char * 64),
        ("mTotalLaps", C.c_short),
        ("mSector", C.c_byte),
        ("mFinishStatus", C.c_byte),
        ("mLapDist", C.c_double),
        ("mPathLateral", C.c_double),
        ("mTrackEdge", C.c_double),
        ("mBestSector1", C.c_double),
        ("mBestSector2", C.c_double),
        ("mBestLapTime", C.c_double),
        ("mLastSector1", C.c_double),
        ("mLastSector2", C.c_double),
        ("mLastLapTime", C.c_double),
        ("mCurSector1", C.c_double),
        ("mCurSector2", C.c_double),
        ("mNumPitstops", C.c_short),
        ("mNumPenalties", C.c_short),
        ("mIsPlayer", C.c_bool),
        ("mControl", C.c_byte),
        ("mInPits", C.c_bool),
        ("mPlace", C.c_ubyte),
        ("mVehicleClass", C.c_char * 32),
        ("mTimeBehindNext", C.c_double),
        ("mLapsBehindNext", C.c_long),
        ("mTimeBehindLeader", C.c_double),
        ("mLapsBehindLeader", C.c_long),
        ("mLapStartET", C.c_double),
        ("mPos", Vec3),
        ("mLocalVel", Vec3),
        ("mLocalAccel", Vec3),
        ("mOri", Vec3 * 3),
        ("mLocalRot", Vec3),
        ("mLocalRotAccel", Vec3),
        ("mHeadlights", C.c_ubyte),
        ("mPitState", C.c_ubyte),
        ("mServerScored", C.c_ubyte),
        ("mIndividualPhase", C.c_ubyte),
        ("mQualification", C.c_long),
        ("mTimeIntoLap", C.c_double),
        ("mEstimatedLapTime", C.c_double),
        ("mPitGroup", C.c_char * 24),
        ("mFlag", C.c_ubyte),
        ("mUnderYellow", C.c_bool),
        ("mCountLapFlag", C.c_ubyte),
        ("mInGarageStall", C.c_bool),
        ("mUpgradePack", C.c_ubyte * 16),
        ("mPitLapDist", C.c_float),
        ("mBestLapSector1", C.c_float),
        ("mBestLapSector2", C.c_float),
        ("mSteamID", C.c_ulonglong),
        ("mVehFilename", C.c_char * 32),
        ("mAttackMode", C.c_short),
        ("mFuelFraction", C.c_ubyte),
        ("mDRSState", C.c_bool),
        ("mExpansion", C.c_ubyte * 4),
    ]


class ScoringInfoV01(C.Structure):
    _pack_ = 4
    _fields_ = [
        ("mTrackName", C.c_char * 64),
        ("mSession", C.c_long),
        ("mCurrentET", C.c_double),
        ("mEndET", C.c_double),
        ("mMaxLaps", C.c_long),
        ("mLapDist", C.c_double),
        ("mResultsStream", C.c_void_p),
        ("mNumVehicles", C.c_long),
        ("mGamePhase", C.c_ubyte),
        ("mYellowFlagState", C.c_byte),
        ("mSectorFlag", C.c_byte * 3),
        ("mStartLight", C.c_ubyte),
        ("mNumRedLights", C.c_ubyte),
        ("mInRealtime", C.c_bool),
        ("mPlayerName", C.c_char * 32),
        ("mPlrFileName", C.c_char * 64),
        ("mDarkCloud", C.c_double),
        ("mRaining", C.c_double),
        ("mAmbientTemp", C.c_double),
        ("mTrackTemp", C.c_double),
        ("mWind", Vec3),
        ("mMinPathWetness", C.c_double),
        ("mMaxPathWetness", C.c_double),
        ("mGameMode", C.c_ubyte),
        ("mIsPasswordProtected", C.c_bool),
        ("mServerPort", C.c_ushort),
        ("mServerPublicIP", C.c_ulong),
        ("mMaxPlayers", C.c_long),
        ("mServerName", C.c_char * 32),
        ("mStartET", C.c_float),
        ("mAvgPathWetness", C.c_double),
        ("mSessionTimeRemaining", C.c_float),
        ("mTimeOfDay", C.c_float),
        ("mIsFixedSetup", C.c_bool),
        ("mTrackGripLevel", C.c_uint8),
        ("mCloudCoverage", C.c_uint8),
        ("mTrackLimitsStepsPerPenalty", C.c_uint8),
        ("mTrackLimitsStepsPerPoint", C.c_uint8),
        ("mExpansion", C.c_ubyte * 187),
        ("mVehicle", C.c_void_p),
    ]


class ApplicationStateV01(C.Structure):
    _pack_ = 4
    _fields_ = [
        ("mAppWindow", C.c_void_p),
        ("mWidth", C.c_ulong),
        ("mHeight", C.c_ulong),
        ("mRefreshRate", C.c_ulong),
        ("mWindowed", C.c_ulong),
        ("mOptionsLocation", C.c_ubyte),
        ("mOptionsPage", C.c_char * 31),
        ("mExpansion", C.c_ubyte * 204),
    ]


# --- SharedMemoryInterface.hpp (empaquetado por defecto) ---

class SharedMemoryGeneric(C.Structure):
    _fields_ = [
        ("events", C.c_uint32 * SME_MAX),
        ("gameVersion", C.c_long),
        ("FFBTorque", C.c_float),
        ("appInfo", ApplicationStateV01),
    ]


class SharedMemoryPathData(C.Structure):
    _fields_ = [
        ("userData", C.c_char * MAX_PATH),
        ("customVariables", C.c_char * MAX_PATH),
        ("stewardResults", C.c_char * MAX_PATH),
        ("playerProfile", C.c_char * MAX_PATH),
        ("pluginsFolder", C.c_char * MAX_PATH),
    ]


class SharedMemoryScoringData(C.Structure):
    _fields_ = [
        ("scoringInfo", ScoringInfoV01),
        ("scoringStreamSize", C.c_size_t),
        ("vehScoringInfo", VehicleScoringInfoV01 * MAX_VEHICLES),
        ("scoringStream", C.c_char * 65536),
    ]


class SharedMemoryTelemetryData(C.Structure):
    _fields_ = [
        ("activeVehicles", C.c_uint8),
        ("playerVehicleIdx", C.c_uint8),
        ("playerHasVehicle", C.c_bool),
        ("telemInfo", TelemInfoV01 * MAX_VEHICLES),
    ]


class SharedMemoryObjectOut(C.Structure):
    _fields_ = [
        ("generic", SharedMemoryGeneric),
        ("paths", SharedMemoryPathData),
        ("scoring", SharedMemoryScoringData),
        ("telemetry", SharedMemoryTelemetryData),
    ]


def offset_of(struct, *path):
    """Desplazamiento en bytes de un campo anidado, p.ej. offset_of(SharedMemoryObjectOut, "scoring", "vehScoringInfo")."""
    off = 0
    cur = struct
    for name in path:
        field = getattr(cur, name)
        off += field.offset
        cur = dict(cur._fields_)[name]
    return off
