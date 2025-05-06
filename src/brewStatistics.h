#pragma once

#define BREW_STATISTICS_HISTORY_LENGTH 90 // in seconds
#define BREW_STATISTICS_HISTORY_FREQUENCY 20 // in Hz
#define BREW_STATISTICS_HISTORY_SIZE (BREW_STATISTICS_HISTORY_LENGTH * BREW_STATISTICS_HISTORY_FREQUENCY)

struct BrewStatisticItem {
    BrewState brewState;
    float temperature; // in degrees Celsius
    float flowRate; // in grams per second
    float weight; // in grams
    uint8_t power; // in percent
};

class BrewStatistics {
private:
    unsigned long id;
    float setTemperature; // in degrees Celsius
    float setWeight; // in grams
    float setPreinfusion; // time in milliseconds
    float setPreinfusionPause; // time in milliseconds
    float setBrewTime; // time in milliseconds
    BrewStatisticItem brewStatistics[BREW_STATISTICS_HISTORY_SIZE];
    int length;

public:
    BrewStatistics() : setTemperature(0), setWeight(0), setPreinfusion(0), 
                       setPreinfusionPause(0), setBrewTime(0), length(0) {}
    
    void initNewBrew(float temperature, float weightSetpoint, float preinfusion, 
                     float preinfusionPause, float brewTime) {
        setTemperature = temperature;
        setWeight = weightSetpoint;
        setPreinfusion = preinfusion;
        setPreinfusionPause = preinfusionPause;
        setBrewTime = brewTime;
        length = 0;

        useRealRandomGenerator(true);
        id = random(0, ULONG_MAX);
    }
    
    void update(BrewState brewState, float temperature, float flowRate, float weight, uint8_t power) {
        brewStatistics[length] = {brewState, temperature, flowRate, weight, power};
        length++;
    }

    float getAverageFlowRate() const {
        if (length == 0) return 0.0f;
        
        float sum = 0.0f;
        int validSamples = 0;
        
        for (int i = 0; i < length; i++) {
            // Only include samples from main brew phase, not preinfusion
            if (brewStatistics[i].brewState == kWaitBrew || 
                brewStatistics[i].brewState == kBrewRunning) {
                sum += brewStatistics[i].flowRate;
                validSamples++;
            }
        }
        
        return validSamples > 0 ? sum / validSamples : 0.0f;
    }

    float getAveragePower() const {
        if (length == 0) return 0.0f;
        
        float sum = 0.0f;
        int validSamples = 0;
        
        for (int i = 0; i < length; i++) {
            // Only include samples from main brew phase, not preinfusion
            if (brewStatistics[i].brewState == kWaitBrew || 
                brewStatistics[i].brewState == kBrewRunning) {
                sum += brewStatistics[i].power;
                validSamples++;
            }
        }
        
        return validSamples > 0 ? sum / validSamples : 0.0f;
    }

    String toJson() const {
        if (length == 0) return "{}";

        String json = "{";
        json += "\"id\":" + String(id) + ",";
        json += "\"setTemp\":" + String(setTemperature) + ",";
        json += "\"setWeight\":" + String(setWeight) + ",";
        json += "\"setPreinf\":" + String(setPreinfusion) + ",";
        json += "\"setPreinfPause\":" + String(setPreinfusionPause) + ",";
        json += "\"setBrewTime\":" + String(setBrewTime) + ",";
        json += "\"length\":" + String(length) + ",";
        json += "\"values\":{";
        json += "\"brewState\":[";
        for (int i = 0; i < length; i++) {
            json += String(brewStatistics[i].brewState);
            if (i < length - 1) json += ",";
            else json += "],";
        }
        json += "\"temp\":[";
        for (int i = 0; i < length; i++) {
            json += String(brewStatistics[i].temperature);
            if (i < length - 1) json += ",";
            else json += "],";
        }
        json += "\"flowRate\":[";
        for (int i = 0; i < length; i++) {
            json += String(brewStatistics[i].flowRate);
            if (i < length - 1) json += ",";
            else json += "],";
        }
        json += "\"weight\":[";
        for (int i = 0; i < length; i++) {
            json += String(brewStatistics[i].weight);
            if (i < length - 1) json += ",";
            else json += "],";
        }
        json += "\"power\":[";
        for (int i = 0; i < length; i++) {
            json += String(brewStatistics[i].power);
            if (i < length - 1) json += ",";
            else json += "]";
        }
        json += "}}";
        return json;
    }

    void logStatisticsAsJson() const {
        LOG(INFO, toJson().c_str());
    }
};

// Global brew statistics instance
BrewStatistics brewStatistics;
