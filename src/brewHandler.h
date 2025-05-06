/**
 * @file brewHandler.h
 *
 * @brief Handler for brewing
 *
 */

#pragma once

#include <hardware/pinmapping.h>
#include "pumpHandler.h"

enum BrewSwitchState {
    kBrewSwitchIdle = 10,
    kBrewSwitchBrew = 20,
    kBrewSwitchBrewAbort = 30,
    kBrewSwitchFlushOff = 31,
    kBrewSwitchReset = 40
};

enum BackflushState {
    kBackflushWaitBrewswitchOn = 10,
    kBackflushFillingStart = 20,
    kBackflushFilling = 21,
    kBackflushFlushingStart = 30,
    kBackflushFlushing = 31,
    kBackflushWaitBrewswitchOff = 43
};

// Normal Brew
BrewState currBrewState = kBrewIdle;

uint8_t currStateBrewSwitch = LOW;
uint8_t currBrewSwitchStateMomentary = LOW;
int brewSwitchState = kBrewSwitchIdle;
boolean brewSwitchWasOff = false;

double totalBrewTime = 0;        // total brewtime set in software
unsigned long timeBrewed = 0;           // total brewed time
double lastBrewTimeMillis = 0;   // for shottimer delay after disarmed button
double lastBrewTime = 0;
unsigned long startingTime = 0;  // start time of brew
boolean brewPIDDisabled = false; // is PID disabled for delay after brew has started?

// Shot timer with or without scale
#if FEATURE_SCALE == 1
boolean scaleCalibrationOn = 0;
boolean scaleTareOn = 0;
int shottimerCounter = 10;
float calibrationValue = SCALE_CALIBRATION_FACTOR; // use calibration example to get value
float weight = 0;                                  // value from HX711
float flowRate = 0;                                // flow rate of brew g/s
float targetFlowRate = 0;                          // target flow rate of brew g/s
float startOfPreinfusionWeight = 0;                // weight value of preinfusion
int preinfusionFinishTime = 0;                     // time when preinfusion is finished
float weightPreBrew = 0;                           // value of scale before wrew started
float weightBrew = 0;                              // weight value of brew
float scaleDelayValue = 2.5;                       // value in gramm that takes still flows onto the scale after brew is stopped
bool scaleFailure = false;
const unsigned long intervalWeight = 100;          // weight scale
unsigned long previousMillisScale;                 // initialisation at the end of init()
HX711_ADC LoadCell(PIN_HXDAT, PIN_HXCLK);

#if SCALE_TYPE == 0
HX711_ADC LoadCell2(PIN_HXDAT2, PIN_HXCLK);
#endif
#endif

/**
 * @brief Toggle or momentary input for Brew Switch
 */
void checkbrewswitch() {
    uint8_t brewSwitchReading = brewSwitch->isPressed();

    if (BREWSWITCH_TYPE == Switch::TOGGLE) {
        currStateBrewSwitch = brewSwitchReading;
    }
    else if (BREWSWITCH_TYPE == Switch::MOMENTARY) {
        if (currBrewSwitchStateMomentary != brewSwitchReading) {
            currBrewSwitchStateMomentary = brewSwitchReading;
        }

        // Convert momentary brew switch input to brew switch state
        switch (brewSwitchState) {
            case kBrewSwitchIdle:
                if (currBrewSwitchStateMomentary == HIGH && machineState != kWaterEmpty) {
                    brewSwitchState = kBrewSwitchBrew;
                    LOG(DEBUG, "brewSwitchState = kBrewSwitchIdle; waiting for brew switch input");
                }
                break;

            case kBrewSwitchBrew:
                // Brew switch short pressed - start brew
                if (currBrewSwitchStateMomentary == LOW) {
                    // Brew trigger
                    currStateBrewSwitch = HIGH;
                    brewSwitchState = kBrewSwitchBrewAbort;
                    LOG(DEBUG, "brewSwitchState = kBrewSwitchBrew; brew switch short pressed - start Brew");
                }

                // Brew switch more than brewSwitchMomentaryLongPress pressed - start flushing
                if (currBrewSwitchStateMomentary == HIGH && brewSwitch->longPressDetected() && machineState != kWaterEmpty) {
                    brewSwitchState = kBrewSwitchFlushOff;
                    valveRelay.on();
                    pumpRelay.on();
                    startingTime = millis();
                    LOG(DEBUG, "brewSwitchState = kBrewSwitchBrew: brew switch long pressed - start flushing");
                }
                break;

            case kBrewSwitchBrewAbort:
                // Brew switch got short pressed while brew is running - abort brew
                if ((currBrewSwitchStateMomentary == HIGH && currStateBrewSwitch == HIGH) || (machineState == kShotTimerAfterBrew) || (backflushState == kBackflushWaitBrewswitchOff)) {
                    currStateBrewSwitch = LOW;
                    brewSwitchState = kBrewSwitchReset;
                    LOG(DEBUG, "brewSwitchState = kBrewSwitchBrewAbort: brew switch short pressed - stop brew");
                }
                break;

            case kBrewSwitchFlushOff:
                // Brew switch got released - stop flushing
                if (currBrewSwitchStateMomentary == LOW && currStateBrewSwitch == LOW) {
                    brewSwitchState = kBrewSwitchReset;
                    LOG(DEBUG, "brewswitchTriggerCase = kBrewSwitchFlushOff: brew switch long press released - stop flushing");
                    valveRelay.off();
                    pumpRelay.off();
                    timeBrewed = 0;
                }
                break;

            case kBrewSwitchReset:
                // Brew switch is released - go back to start and wait for next brew switch input
                if (currBrewSwitchStateMomentary == LOW) {
                    brewSwitchState = kBrewSwitchIdle;
                    LOG(DEBUG, "brewSwitchState = kBrewSwitchReset: brew switch released - go to kBrewSwitchIdle ");
                }
                break;
        }
    }
}

/**
 * @brief Backflush
 */
void backflush() {
    if (backflushState != kBackflushWaitBrewswitchOn && backflushOn == 0) {
        backflushState = kBackflushWaitBrewswitchOff; // Force reset in case backflushOn is reset during backflush!
        LOG(INFO, "Backflush: Disabled via Webinterface");
    }
    else if (offlineMode == 1 || currBrewState > kBrewIdle || backflushCycles <= 0 || backflushOn == 0) {
        return;
    }

    if (bPID.GetMode() == 1) { // Deactivate PID
        bPID.SetMode(0);
        pidOutput = 0;
    }

    heaterRelay.off(); // Stop heating

    checkbrewswitch();

    if (currStateBrewSwitch == LOW && backflushState != kBackflushWaitBrewswitchOn) { // Abort function for state machine from every state
        backflushState = kBackflushWaitBrewswitchOff;
    }

    // State machine for backflush
    switch (backflushState) {
        case kBackflushWaitBrewswitchOn:
            if (currStateBrewSwitch == HIGH && backflushOn) {
                startingTime = millis();
                backflushState = kBackflushFillingStart;
            }

            break;

        case kBackflushFillingStart:
            LOG(INFO, "Backflush: Portafilter filling...");
            valveRelay.on();
            pumpRelay.on();
            backflushState = kBackflushFilling;

            break;

        case kBackflushFilling:
            if (millis() - startingTime > (backflushFillTime * 1000)) {
                startingTime = millis();
                backflushState = kBackflushFlushingStart;
            }

            break;

        case kBackflushFlushingStart:
            LOG(INFO, "Backflush: Flushing to drip tray...");
            valveRelay.off();
            pumpRelay.off();
            currBackflushCycles++;
            backflushState = kBackflushFlushing;

            break;

        case kBackflushFlushing:
            if (millis() - startingTime > (backflushFlushTime * 1000) && currBackflushCycles < backflushCycles) {
                startingTime = millis();
                backflushState = kBackflushFillingStart;
            }
            else if (currBackflushCycles >= backflushCycles) {
                backflushState = kBackflushWaitBrewswitchOff;
            }

            break;

        case kBackflushWaitBrewswitchOff:
            if (currStateBrewSwitch == LOW) {
                LOG(INFO, "Backflush: Finished!");
                valveRelay.off();
                pumpRelay.off();
                currBackflushCycles = 0;
                backflushState = kBackflushWaitBrewswitchOn;
            }

            break;
    }
}

#if (FEATURE_BREWCONTROL == 1)
/**
 * @brief Time base brew mode
 */
void brew() {
    unsigned long currentMillisTemp = millis();
    checkbrewswitch();

    if (currStateBrewSwitch == LOW && currBrewState > kBrewIdle) {
        // abort function for state machine from every state
        LOG(INFO, "Brew stopped manually");
        currBrewState = kWaitBrewOff;
    }

    if (currBrewState > kBrewIdle && currBrewState < kBrewFinished || brewSwitchState == kBrewSwitchFlushOff) {
        timeBrewed = currentMillisTemp - startingTime;
    }

    if (currStateBrewSwitch == LOW) {
        // check if brewswitch was turned off at least once, last time,
        brewSwitchWasOff = true;
    }

    if (brewTime != 0) {
        totalBrewTime = (preinfusion * 1000) + (preinfusionPause * 1000) + (abs(brewTime) * 1000); // running every cycle, in case changes are done during brew
    } else {
        // Stop by time deactivated --> brewTime = 0
        totalBrewTime = 0;
    }

    if (currBrewState != kBrewIdle) {
        // Update brew statistics every 50ms
        static unsigned long lastBrewStatsUpdate = 0;
        if (millis() - lastBrewStatsUpdate >= 1000 / BREW_STATISTICS_HISTORY_FREQUENCY) {
            brewStatistics.update(currBrewState, temperature, flowRate, weightBrew, pumpHandler.getPower());
            lastBrewStatsUpdate = millis();
        }
    }

    // state machine for brew
    switch (currBrewState) {
        case kBrewIdle: // waiting step for brew switch turning on
            if (currStateBrewSwitch == HIGH && backflushState == 10 && backflushOn == 0 && brewSwitchWasOff && machineState != kWaterEmpty) {
                startingTime = millis();

                if (preinfusionPause == 0 && preinfusion == 0) {
                    currBrewState = kBrewRunning;
                }
                else {
                    currBrewState = kPreinfusion;
                }

                // Initialize brew statistics
                brewStatistics.initNewBrew(brewSetpoint, weightSetpoint, preinfusion, preinfusionPause, brewTime * 1000);
            }
            else {
                backflush();
            }

            break;

        case kPreinfusion: // preinfusioon
            LOG(INFO, "Preinfusion");
            valveRelay.on();
            pumpHandler.setPower(10); // Set pump to 10% power during preinfusion
            pumpHandler.update();
            startOfPreinfusionWeight = weight;
            currBrewState = kWaitPreinfusion;

            break;

            // TODO: Add preinfusion ripple

        case kWaitPreinfusion: // waiting time preinfusion
            static int dripFilterCount = 0;

            // increase pumpHandler power by 3.64% every 100ms
            if (timeBrewed % 100 == 0) {
                pumpHandler.setPower(ceil(1.0364 * pumpHandler.getPower()));
            }

            pumpHandler.update();

            // Check if preinfusion time is reached OR first drip is detected (0.3g increase after 1.5s)
            if (timeBrewed < 1500) {
                startOfPreinfusionWeight = weight;
            }
            else if ((timeBrewed > (preinfusion * 1000)) ||
                (FEATURE_SCALE == 1 && (weight - startOfPreinfusionWeight) > 0.3f)) {
                
                // Count drip filter every 30ms => 30ms * 5 = 150ms
                if (timeBrewed % 30 == 0) {
                    dripFilterCount++;
                }

                if (dripFilterCount > 5) {
                    preinfusionFinishTime = timeBrewed;
                    currBrewState = kPreinfusionPause;                    
                }
            } else {
                dripFilterCount = 0;
            }

            break;

        case kPreinfusionPause: // preinfusion pause
            LOG(INFO, "Preinfusion pause");
            valveRelay.on();
            if (preinfusionPause > 0) {
                pumpHandler.setPower(0); // Set pump to 0% power during preinfusion pause
            }
            pumpHandler.update();
            currBrewState = kWaitPreinfusionPause;

            break;

        case kWaitPreinfusionPause: // waiting time preinfusion pause
            if (timeBrewed > (preinfusionFinishTime + preinfusionPause * 1000)) {
                currBrewState = kBrewRunning;
            }

            break;

        case kBrewRunning: // brew running
            LOG(INFO, "Brew started");
            valveRelay.on();
#if (FEATURE_SCALE == 1)
            // if no preinfusion pause, keep pump power as it was during preinfusion ramp.
            // otherwise, set pump to 60% power at start of main brew
            if (preinfusionPause > 0) {
                pumpHandler.setPower(60); // Set pump to 60% power at start of main brew
            }
#else
            pumpHandler.setPower(100); // Set pump to 100% power at start of main brew
#endif
            pumpHandler.update();
            currBrewState = kWaitBrew;

            break;

        case kWaitBrew: // waiting time or weight brew
            lastBrewTime = timeBrewed;

            // Adjust pump power based on flow rate if scale is enabled
#if (FEATURE_SCALE == 1)
            if ((totalBrewTime - timeBrewed) <= 0) {
                targetFlowRate = weightSetpoint - weightBrew;
            }
            else {
                targetFlowRate = (weightSetpoint - weightBrew) / ((totalBrewTime - timeBrewed) / 1000);
            }

            // Adjust pump power every 50ms
            if (timeBrewed % 50 == 0) {
                pumpHandler.adjustPowerForFlowRate(flowRate, targetFlowRate);
            }

            pumpHandler.update();
#endif

            // stop brew if target-time is reached --> No stop if stop by time is deactivated via Parameter (0)
            if ((timeBrewed > totalBrewTime) && ((brewTime > 0))) {
                currBrewState = kBrewFinished;
            }
#if (FEATURE_SCALE == 1)
            // stop brew if target-weight is reached --> No stop if stop by weight is deactivated via Parameter (0)
            else if (((FEATURE_SCALE == 1) && (weightBrew > weightSetpoint - flowRate * 0.3)) && (weightSetpoint > 0)) {
                currBrewState = kBrewFinished;
            }
#endif

            break;

        case kBrewFinished: // brew finished
            static unsigned long brewFinishTime = 0;
            if (brewFinishTime == 0) {
                brewFinishTime = millis();

                LOG(INFO, "Brew stopped");
                valveRelay.off();
                pumpHandler.setPower(0);
                pumpHandler.update();
                pumpHandler.resetFilter();
            }
            else if (millis() - brewFinishTime >= 500) { // wait 500ms after brew finished to settle scale
                currBrewState = kWaitBrewOff;
                brewFinishTime = 0;
            }

            break;

        case kWaitBrewOff: // waiting for brewswitch off position
            if (currStateBrewSwitch == LOW) {
                valveRelay.off();
                pumpRelay.off();

                // disarmed button
                currentMillisTemp = 0;
                brewDetected = 0;          // rearm brewDetection
                currBrewState = kBrewIdle;
                lastBrewTime = timeBrewed; // store brewtime to show in Shottimer after brew is finished
                timeBrewed = 0;

                brewStatistics.logStatisticsAsJson();
            }

            break;
    }
}
#endif
