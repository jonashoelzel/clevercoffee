/**
 * @file pumpHandler.h
 *
 * @brief Handler for pump control
 *
 */

#pragma once

#include <hardware/pinmapping.h>

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

public:
    /**
     * @brief Set the pump power percentage
     * @param power Percentage of power (0-100)
     */
    void setPower(uint8_t power) {
        if (power > 100) power = 100;
        pumpPower = power;
    }

    /**
     * @brief Get the current pump power percentage
     * @return Current power percentage (0-100)
     */
    uint8_t getPower() const {
        return pumpPower;
    }

    /**
     * @brief Adjust pump power based on flow rate
     * @param currentFlowRate Current flow rate in g/s
     */
    void adjustPowerForFlowRate(float currentFlowRate) {
        if (currentFlowRate > MAX_FLOW_RATE) {
            // Reduce power if flow rate is too high
            uint8_t newPower = pumpPower - 5;
            if (newPower < 10) newPower = 10; // Don't go below 10% power
            setPower(newPower);
        } else if (currentFlowRate < MAX_FLOW_RATE * 0.8f) {
            // Increase power if flow rate is too low
            uint8_t newPower = pumpPower + 5;
            if (newPower > 100) newPower = 100; // Don't exceed 100% power
            setPower(newPower);
        }
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