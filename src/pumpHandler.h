/**
 * @file pumpHandler.h
 *
 * @brief Handler for pump control
 *
 */

#pragma once

#include <hardware/pinmapping.h>
#include "kalmanFilter.h"

class PumpHandler {
private:
    unsigned long lastPumpPulseTime = 0;
    bool pumpPulseState = false;
    uint8_t pumpPower = 100;  // Default to 100% power
    static constexpr float MAX_FLOW_RATE = 1.8f; // Maximum allowed flow rate in g/s

    // Constants for power control
    static constexpr unsigned long CYCLE_TIME = 100;       // Total cycle time in ms
    static constexpr unsigned long MIN_PULSE_TIME = 10;    // Minimum pulse time in ms
    static constexpr unsigned long MAX_PULSE_TIME = CYCLE_TIME;   // Maximum pulse time in ms

    // Adjustment filtering
    KalmanFilter powerAdjustFilter{0.05, 0.4}; // Increased measurement noise for more dampening
    KalmanFilter flowRateDeltaFilter{0.05, 0.9}; // Increased measurement noise for more dampening
    KalmanFilter flowRateFilter{0.05, 0.9}; // Increased measurement noise for more dampening

    float walkingAverageFlowRate = 0.0f;

public:
    /**
     * @brief Set the pump power percentage
     * @param power Percentage of power (0-100)
     */
    void setPower(uint8_t power) {
        if (power > 100) power = 100;
        pumpPower = power;

        LOGF(INFO, "Pump power set to %d", pumpPower);
    }

    /**
     * @brief Get the current pump power percentage
     * @return Current power percentage (0-100)
     */
    uint8_t getPower() const {
        return pumpPower;
    }

    void resetFilter() {
        powerAdjustFilter.reset();
        flowRateDeltaFilter.reset();
        flowRateFilter.reset();
        walkingAverageFlowRate = 0.0f;
    }

    /**
     * @brief Adjust pump power based on flow rate
     * @param currentFlowRate Current flow rate in g/s
     * @param targetFlowRate Target flow rate in g/s
     */
    void adjustPowerForFlowRate(float currentFlowRate, float targetFlowRate) {
        // Calculate flow rate difference (negative if flow is too high)
        walkingAverageFlowRate = (walkingAverageFlowRate * 0.9f) + (currentFlowRate * 0.1f);
        float flowRateDelta = targetFlowRate - walkingAverageFlowRate;
        
        // Exit early if we're within acceptable range (within 20% below target)
        if (flowRateDelta >= 0 && flowRateDelta <= 0.2f * targetFlowRate) {
            return;
        }

        // Calculate raw power adjustment (1-10%)
        static const float ADJUSTMENT_SCALE = 2.0f;
        int rawAdjustment = constrain(
            int(abs(flowRateDelta) * ADJUSTMENT_SCALE), 
            1,
            10
        );

        // Apply direction
        if (flowRateDelta < 0) {
            rawAdjustment = -rawAdjustment;
        }
        
        // Run the raw adjustment through Kalman filter
        float filteredAdjustment = powerAdjustFilter.update(rawAdjustment);
        
        // Apply the filtered adjustment
        uint8_t newPower = constrain(pumpPower + round(rawAdjustment), 10, 100);
        setPower(newPower);
    }

    /**
     * @brief Update the pump state based on power setting
     * Should be called in the main loop
     */
    void update() {
        if (pumpPower == 0) {
            pumpRelay.off();
            return;
        }

        if (pumpPower == 100) {
            pumpRelay.on();
            return;
        }

        unsigned long currentTime = millis();
        unsigned long onTime = map(pumpPower, 0, 100, MIN_PULSE_TIME, MAX_PULSE_TIME);
        
        if (pumpPulseState) {
            // Pump is on
            if (currentTime - lastPumpPulseTime >= onTime) {
                pumpPulseState = false;
                lastPumpPulseTime = currentTime;
                pumpRelay.off();
            }
        } else {
            // Pump is off
            if (currentTime - lastPumpPulseTime >= (CYCLE_TIME - onTime)) {
                pumpPulseState = true;
                lastPumpPulseTime = currentTime;
                pumpRelay.on();
            }
        }
    }
};

// Global instance
PumpHandler pumpHandler; 