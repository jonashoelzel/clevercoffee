/**
 * @file kalmanFilter.h
 *
 * @brief Implementation of a 1D Kalman filter
 */

#pragma once

/**
 * @brief Kalman filter implementation for 1D measurements
 */
class KalmanFilter {
private:
    float filteredValue;
    float kalmanGain;
    float errorCovariance;
    float processNoise;
    float measurementNoise;

public:
    /**
     * @brief Constructor for KalmanFilter
     * @param pNoise Process noise covariance -> increase for more dampening
     * @param mNoise Measurement noise covariance -> increase for more dampening
     */
    KalmanFilter(float pNoise = 0.08, float mNoise = 0.05) 
        : filteredValue(0.0), 
          kalmanGain(0.0), 
          errorCovariance(1.0),
          processNoise(pNoise),
          measurementNoise(mNoise) {}

    /**
     * @brief Update the filter with a new measurement
     * @param measurement New measurement value
     * @return Filtered value
     */
    float update(float measurement) {
        // Prediction step
        float predictedErrorCovariance = errorCovariance + processNoise;
        
        // Update step
        kalmanGain = predictedErrorCovariance / (predictedErrorCovariance + measurementNoise);
        filteredValue = filteredValue + kalmanGain * (measurement - filteredValue);
        errorCovariance = (1 - kalmanGain) * predictedErrorCovariance;
        
        return filteredValue;
    }

    /**
     * @brief Get the current filtered value
     * @return Current filtered value
     */
    float getFilteredValue() const {
        return filteredValue;
    }

    /**
     * @brief Reset the filter to initial state
     */
    void reset() {
        filteredValue = 0.0;
        kalmanGain = 0.0;
        errorCovariance = 1.0;
    }
}; 