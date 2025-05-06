"""
Espresso brewing evaluation and visualization tool.

This module processes, analyzes, and visualizes data from espresso brewing sessions.
It supports loading data from JSON files or directly from an ESP32 controller.
"""

from __future__ import annotations
import json
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import scipy.signal
import requests
import sys
from dataclasses import dataclass
from enum import IntEnum
from typing import Dict, List, Optional, Tuple, Union, Any


class Config:
    """Centralized configuration for the brew statistics application."""
    
    # File and connection settings
    JSON_FILENAME = "new.json"
    ESP_URL = "http://silvia.local/brewstatistics"
    REQUEST_TIMEOUT = 10  # Timeout for ESP request in seconds
    
    # Data processing settings
    SAMPLING_FREQUENCY_HZ = 20
    MEDIAN_FILTER_KERNEL_SIZE = 5
    
    # Plot settings
    FIGURE_SIZE = (12, 16)
    GRID_HEIGHT_RATIOS = [2.5, 3, 3, 3, 3]
    BACKGROUND_COLOR = 'white'
    STATS_Y_POSITION = 0.70
    STATS_LINE_SPACING = 0.2
    
    class BrewState(IntEnum):
        """Enumeration of brew states matching the C++ controller implementation."""
        IDLE = 10
        PREINFUSION = 20
        WAIT_PREINFUSION = 21
        PREINFUSION_PAUSE = 30
        WAIT_PREINFUSION_PAUSE = 31
        BREW_RUNNING = 40
        WAIT_BREW = 41
        BREW_FINISHED = 42
        WAIT_BREW_OFF = 43
        
    # Map brew state codes to names and colors for plotting
    BREW_STATE_MAP = {
        BrewState.IDLE: {"name": "Idle", "color": "grey"},
        BrewState.PREINFUSION: {"name": "Preinfusion", "color": "lightblue"},
        BrewState.WAIT_PREINFUSION: {"name": "Preinfusion", "color": "cornflowerblue"},
        BrewState.PREINFUSION_PAUSE: {"name": "Preinfusion Pause", "color": "lightcoral"},
        BrewState.WAIT_PREINFUSION_PAUSE: {"name": "Preinfusion Pause", "color": "indianred"},
        BrewState.BREW_RUNNING: {"name": "Brew", "color": "lightgreen"},
        BrewState.WAIT_BREW: {"name": "Brew", "color": "mediumseagreen"},
        BrewState.BREW_FINISHED: {"name": "Finished", "color": "gold"},
        BrewState.WAIT_BREW_OFF: {"name": "Off", "color": "darkgoldenrod"},
        # Default for unknown states
        "unknown": {"name": "Unknown", "color": "white"}
    }
    
    # Lists of state codes for specific brew phases
    PREINFUSION_STATES = [BrewState.PREINFUSION, BrewState.WAIT_PREINFUSION]
    PREINFUSION_PAUSE_STATES = [BrewState.PREINFUSION_PAUSE, BrewState.WAIT_PREINFUSION_PAUSE]
    BREWING_STATES = [BrewState.BREW_RUNNING, BrewState.WAIT_BREW]


@dataclass
class BrewData:
    """Container for processed brew data with helpful properties and calculations."""
    
    # Raw data from JSON
    raw_data: Dict[str, Any]
    
    # Processed arrays
    brew_states: np.ndarray
    temperatures: np.ndarray
    flow_rates_raw: np.ndarray
    weights: np.ndarray
    powers: np.ndarray
    time_seconds: np.ndarray
    
    @property
    def sample_count(self) -> int:
        """Get the number of samples in the data."""
        return len(self.brew_states)
    
    @property
    def final_weight(self) -> float:
        """Get the final weight from the brew data."""
        if len(self.weights) == 0:
            return 0.0
        return self.weights[-1]
    
    @property
    def average_temperature(self) -> float:
        """Calculate the average temperature over the entire brew time."""
        if len(self.temperatures) == 0:
            return 0.0
        return float(np.mean(self.temperatures))
    
    @property
    def preinfusion_time(self) -> float:
        """Calculate the actual preinfusion time from brew data."""
        if len(self.brew_states) == 0:
            return 0.0
        
        preinfusion_samples = sum(1 for state in self.brew_states 
                                if state in Config.PREINFUSION_STATES)
        return preinfusion_samples / Config.SAMPLING_FREQUENCY_HZ
    
    @property
    def preinfusion_pause_time(self) -> float:
        """Calculate the actual preinfusion pause time from brew data."""
        if len(self.brew_states) == 0:
            return 0.0
        
        pause_samples = sum(1 for state in self.brew_states 
                          if state in Config.PREINFUSION_PAUSE_STATES)
        return pause_samples / Config.SAMPLING_FREQUENCY_HZ
    
    @property
    def brew_time(self) -> float:
        """Calculate the actual brewing time from brew data."""
        if len(self.brew_states) == 0:
            return 0.0
        
        brew_samples = sum(1 for state in self.brew_states 
                          if state in Config.BREWING_STATES)
        return brew_samples / Config.SAMPLING_FREQUENCY_HZ
    
    @property
    def average_power(self) -> float:
        """Calculate the average pump power during actual brewing."""
        if len(self.brew_states) == 0 or len(self.powers) == 0:
            return 0.0
        
        # Filter powers during brewing phases
        brewing_powers = [self.powers[i] for i, state in enumerate(self.brew_states)
                         if state in Config.BREWING_STATES]
        
        if not brewing_powers:
            return 0.0
        
        return float(np.mean(brewing_powers))
    
    @property
    def actual_flow_rate(self) -> float:
        """Calculate the actual flow rate using final weight and total brew time."""
        if self.brew_time <= 0:
            return 0.0
        
        return self.final_weight / self.brew_time
    
    @property
    def set_flow_rate(self) -> float:
        """Calculate the set flow rate using set weight and brew time."""
        if (not self.raw_data or 'setWeight' not in self.raw_data 
                or 'setBrewTime' not in self.raw_data):
            return 0.0
        
        set_weight = self.raw_data.get('setWeight', 0.0)
        set_brew_time = abs(self.raw_data.get('setBrewTime', 0.0))
        
        if set_brew_time <= 0:
            return 0.0
        
        return set_weight / set_brew_time * 1000
    
    def get_brew_state_info(self, state_code: int) -> Dict[str, str]:
        """Get name and color for a given brew state code."""
        return Config.BREW_STATE_MAP.get(state_code, Config.BREW_STATE_MAP["unknown"])
    
    def clean_flow_rate(self) -> np.ndarray:
        """Clean the flow rate data by clipping negatives and applying a median filter."""
        flow_rates_clipped = np.maximum(0, self.flow_rates_raw)
        filter_size = Config.MEDIAN_FILTER_KERNEL_SIZE
        
        if filter_size % 2 == 0:
            print(f"Warning: Median filter kernel size ({filter_size}) should be odd. Adjusting to {filter_size + 1}.")
            filter_size += 1
            
        if len(flow_rates_clipped) < filter_size:
            print(f"Warning: Data length ({len(flow_rates_clipped)}) is less than filter size ({filter_size}). Skipping filter.")
            return flow_rates_clipped
            
        return scipy.signal.medfilt(flow_rates_clipped, kernel_size=filter_size)


class BrewDataLoader:
    """Responsible for loading brew data from different sources."""
    
    def __init__(self, file_path: Optional[str] = None, esp_url: Optional[str] = None):
        """
        Initialize the data loader with configured sources.
        
        Args:
            file_path: Path to a JSON file containing brew data
            esp_url: URL of the ESP32 web server providing brew data
        """
        self.file_path = file_path
        self.esp_url = esp_url
    
    def load_from_file(self) -> Optional[Dict[str, Any]]:
        """
        Attempt to load brew data from a JSON file.
        
        Returns:
            Dictionary containing the brew data or None if loading failed
        """
        if not self.file_path:
            return None
            
        try:
            with open(self.file_path, 'r') as f:
                data = json.load(f)
            print(f"Loaded data from file: {self.file_path}")
            return data
        except FileNotFoundError:
            print(f"Warning: File not found '{self.file_path}'.")
            return None
        except json.JSONDecodeError as e:
            print(f"Error: Could not decode JSON from '{self.file_path}': {e}.")
            return None
    
    def load_from_esp(self, timeout: int = Config.REQUEST_TIMEOUT) -> Optional[Dict[str, Any]]:
        """
        Attempt to load brew data from the ESP32 web server.
        
        Args:
            timeout: Request timeout in seconds
            
        Returns:
            Dictionary containing the brew data or None if loading failed
        """
        if not self.esp_url:
            return None
            
        print(f"Attempting to fetch data from: {self.esp_url}")
        try:
            response = requests.get(self.esp_url, timeout=timeout)
            response.raise_for_status()
            try:
                data = response.json()
                print("Successfully fetched and parsed JSON data.")
                return data
            except requests.exceptions.JSONDecodeError:
                print("Error: Failed to decode JSON response from ESP32.")
                print("Received content:", response.text[:500])  # Print beginning of content
                return None
        except requests.exceptions.ConnectionError as e:
            print(f"Error: Could not connect to ESP32 at {self.esp_url}. Details: {e}")
            return None
        except requests.exceptions.Timeout:
            print(f"Error: Request to {self.esp_url} timed out after {timeout} seconds.")
            return None
        except requests.exceptions.HTTPError as e:
            print(f"Error: HTTP error: {response.status_code} {response.reason}. Details: {e}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"Error: An unexpected error occurred during the request: {e}")
            return None
    
    def load_data(self) -> Optional[Dict[str, Any]]:
        """
        Load brew data from file or ESP, with file given precedence.
        
        Returns:
            Dictionary containing the brew data or None if loading failed
        """
        # Try file first
        data = self.load_from_file()
        
        # If file loading failed, try ESP
        if data is None and self.esp_url:
            print("Attempting to fetch from ESP.")
            data = self.load_from_esp()
        
        return data


class BrewDataProcessor:
    """Processes raw brew data into analyzed and usable formats."""
    
    def __init__(self):
        """Initialize the brew data processor."""
        pass
    
    def process_data(self, raw_data: Dict[str, Any]) -> Optional[BrewData]:
        """
        Process raw JSON data into a structured BrewData object.
        
        Args:
            raw_data: Dictionary containing the raw brew data from JSON
            
        Returns:
            BrewData object or None if processing failed
        """
        if not raw_data or 'values' not in raw_data or not raw_data['values']:
            print("Error: No valid brew data found in JSON structure.")
            return None
        
        values = raw_data['values']
        
        # Extract arrays from the JSON format
        brew_states = np.array(values.get('brewState', []))
        temperatures = np.array(values.get('temp', []))
        flow_rates_raw = np.array(values.get('flowRate', []))
        weights = np.array(values.get('weight', []))
        powers = np.array(values.get('power', []))
        
        # Ensure all arrays have the same length
        min_length = min(len(brew_states), len(temperatures), len(flow_rates_raw), 
                        len(weights), len(powers))
        
        if min_length == 0:
            print("Error: Empty data arrays found.")
            return None
        
        # Trim arrays to the minimum length
        brew_states = brew_states[:min_length]
        temperatures = temperatures[:min_length]
        flow_rates_raw = flow_rates_raw[:min_length]
        weights = weights[:min_length]
        powers = powers[:min_length]
        
        print(f"Using {min_length} data points (trimmed to match shortest array)")
        
        # Create time array
        time_seconds = np.array([i / Config.SAMPLING_FREQUENCY_HZ for i in range(min_length)])
        
        # Create and return the BrewData object
        return BrewData(
            raw_data=raw_data,
            brew_states=brew_states,
            temperatures=temperatures,
            flow_rates_raw=flow_rates_raw,
            weights=weights,
            powers=powers,
            time_seconds=time_seconds
        )


class BrewStatePlotter:
    """Handles visualization of brew data through various plots and charts."""
    
    def __init__(self, brew_data: BrewData):
        """
        Initialize the brew state plotter with processed data.
        
        Args:
            brew_data: Processed brew data to visualize
        """
        self.brew_data = brew_data
        self.flow_rates_cleaned = brew_data.clean_flow_rate()
    
    def create_plot(self) -> None:
        """Create and display the complete brew analysis plot."""
        # Set up the figure with a more reasonable default size
        # Default to a smaller height that fits most screens but preserves layout
        fig_width = min(Config.FIGURE_SIZE[0], 12)  # Cap width at 12 inches
        fig_height = min(Config.FIGURE_SIZE[1], 10)  # Initial height of 10 inches
        
        # Create the figure
        fig = plt.figure(figsize=(fig_width, fig_height))
        
        # Create gridspec with fixed height ratios
        gs = fig.add_gridspec(5, 1, height_ratios=Config.GRID_HEIGHT_RATIOS)
        
        # Stats area at the top
        ax_stats = fig.add_subplot(gs[0])
        
        # Main plots below
        ax1 = fig.add_subplot(gs[1])  # Temperature
        ax2 = fig.add_subplot(gs[2], sharex=ax1)  # Flow Rate
        ax3 = fig.add_subplot(gs[3], sharex=ax1)  # Weight
        ax4 = fig.add_subplot(gs[4], sharex=ax1)  # Power
        
        axes = [ax1, ax2, ax3, ax4]  # List of plot axes
        fig.set_facecolor(Config.BACKGROUND_COLOR)

        # Create plots
        self._create_stats_display(ax_stats)
        self._create_temperature_plot(ax1)
        self._create_flow_rate_plot(ax2)
        self._create_weight_plot(ax3)
        self._create_power_plot(ax4)
        self._add_brew_state_visualization(axes, ax1)
        
        # Set title for the entire figure
        fig.suptitle("Coffee Brew Analysis", fontsize=16, y=0.98)
        
        # Use tight layout to ensure good spacing
        plt.tight_layout(rect=[0, 0, 1, 0.96])
        
        # Apply figure manager settings to ensure proper display
        try:
            # Get the backend and figure manager
            import matplotlib
            backend = matplotlib.get_backend()
            manager = plt.get_current_fig_manager()
            
            if backend == 'TkAgg':
                # Reset geometry to avoid issues with window size
                if hasattr(manager, 'window') and hasattr(manager.window, 'wm_geometry'):
                    manager.window.wm_geometry("")
                    
                # Make the window resizable
                if hasattr(manager, 'window') and hasattr(manager.window, 'wm_resizable'):
                    manager.window.wm_resizable(True, True)
                    
            elif backend.startswith('Qt'):
                # Ensure window is resizable
                if hasattr(manager, 'window'):
                    try:
                        # Set window to be maximizable and resizable
                        manager.window.setWindowTitle("Coffee Brew Analysis")
                        # Ensure scrollbars appear when needed
                        manager.canvas.setMinimumSize(100, 100)
                    except:
                        pass
                        
        except Exception as e:
            print(f"Note: Could not configure window display settings. Details: {e}")
        
        # Instead of making the figure itself scrollable, let's make the window resizable
        # This works better across all matplotlib backends
        
        # Show the plot
        plt.show()
    
    # Add a new method to create a scrollable plot (optional alternative)
    def create_scrollable_plot(self) -> None:
        """Create and display a scrollable brew analysis plot that works on all platforms."""
        import matplotlib
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        import tkinter as tk
        from tkinter import ttk

        # Create a Tkinter root window
        root = tk.Tk()
        root.title("Coffee Brew Analysis - Scrollable View")
        root.state('zoomed')  # Start maximized
        
        # Create a frame with scrollbars
        main_frame = ttk.Frame(root)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Add Canvas 
        canvas = tk.Canvas(main_frame)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Add Scrollbars
        v_scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=canvas.yview)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        h_scrollbar = ttk.Scrollbar(root, orient=tk.HORIZONTAL, command=canvas.xview)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Configure the canvas
        canvas.configure(xscrollcommand=h_scrollbar.set, yscrollcommand=v_scrollbar.set)
        canvas.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        
        # Create a frame inside the canvas for the matplotlib figure
        frame_plots = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=frame_plots, anchor="nw")
        
        # Create the matplotlib figure at original size
        fig = plt.figure(figsize=Config.FIGURE_SIZE)
        gs = fig.add_gridspec(5, 1, height_ratios=Config.GRID_HEIGHT_RATIOS)
        
        # Stats area at the top
        ax_stats = fig.add_subplot(gs[0])
        
        # Main plots below
        ax1 = fig.add_subplot(gs[1])  # Temperature
        ax2 = fig.add_subplot(gs[2], sharex=ax1)  # Flow Rate
        ax3 = fig.add_subplot(gs[3], sharex=ax1)  # Weight
        ax4 = fig.add_subplot(gs[4], sharex=ax1)  # Power
        
        axes = [ax1, ax2, ax3, ax4]  # List of plot axes
        fig.set_facecolor(Config.BACKGROUND_COLOR)

        # Create plots
        self._create_stats_display(ax_stats)
        self._create_temperature_plot(ax1)
        self._create_flow_rate_plot(ax2)
        self._create_weight_plot(ax3)
        self._create_power_plot(ax4)
        self._add_brew_state_visualization(axes, ax1)
        
        # Set title for the entire figure
        fig.suptitle("Coffee Brew Analysis", fontsize=16, y=0.98)
        plt.tight_layout(rect=[0, 0, 1, 0.96])
        
        # Embed the figure in the tkinter window
        canvas_fig = FigureCanvasTkAgg(fig, master=frame_plots)
        canvas_fig.draw()
        canvas_fig.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # Add navigation toolbar
        toolbar_frame = ttk.Frame(root)
        toolbar_frame.pack(side=tk.BOTTOM, fill=tk.X)
        toolbar = NavigationToolbar2Tk(canvas_fig, toolbar_frame)
        toolbar.update()
        
        # Start the event loop
        root.mainloop()
        
        # Close the matplotlib figure when Tkinter window is closed
        plt.close(fig)
    
    def _create_stats_display(self, ax: plt.Axes) -> None:
        """
        Create the statistics display panel at the top of the figure.
        
        Args:
            ax: The matplotlib axes object to draw on
        """
        ax.axis('off')  # Hide axes
        
        # Collect statistics
        set_values = []
        actual_values = []
        
        # Set values (left column)
        if 'setTemp' in self.brew_data.raw_data: 
            set_values.append(f"Temperature: {self.brew_data.raw_data['setTemp']:.1f}°C")
        else: 
            set_values.append("Temperature: N/A")
        
        if 'setWeight' in self.brew_data.raw_data: 
            set_values.append(f"Weight: {self.brew_data.raw_data['setWeight']:.1f}g")
        else: 
            set_values.append("Weight: N/A")
        
        if 'setPreinf' in self.brew_data.raw_data: 
            set_values.append(f"Preinfusion: {self.brew_data.raw_data['setPreinf']:.1f}s")
        else: 
            set_values.append("Preinfusion: N/A")
        
        if 'setPreinfPause' in self.brew_data.raw_data: 
            set_values.append(f"Preinfusion Pause: {self.brew_data.raw_data['setPreinfPause']:.1f}s")
        else: 
            set_values.append("Preinfusion Pause: N/A")
        
        if 'setBrewTime' in self.brew_data.raw_data: 
            set_values.append(f"Brew Time: {abs(self.brew_data.raw_data['setBrewTime'] / 1000):.1f}s")
        else: 
            set_values.append("Brew Time: N/A")
        
        # Add set flow rate
        set_flow_rate = self.brew_data.set_flow_rate
        if set_flow_rate > 0: 
            set_values.append(f"Flow Rate: {set_flow_rate:.1f}g/s")
        else: 
            set_values.append("Flow Rate: N/A")
        
        # Actual values (right column)
        actual_values.append(f"Average Temp: {self.brew_data.average_temperature:.1f}°C")
        actual_values.append(f"Weight: {self.brew_data.final_weight:.1f}g")
        actual_values.append(f"Preinfusion: {self.brew_data.preinfusion_time:.1f}s")
        actual_values.append(f"Preinfusion Pause: {self.brew_data.preinfusion_pause_time:.1f}s")
        actual_values.append(f"Brew Time: {self.brew_data.brew_time:.1f}s")
        actual_values.append(f"Average Flow Rate: {self.brew_data.actual_flow_rate:.1f}g/s")
        actual_values.append(f"Average Pump Power: {self.brew_data.average_power:.1f}%")
        
        # Create modern, clean statistics display
        # Column headers
        ax.text(0.25, 0.9, "Set Values", fontsize=14, weight='bold', ha='center')
        ax.text(0.75, 0.9, "Actual Values", fontsize=14, weight='bold', ha='center')
        
        # Add horizontal separator line
        ax.axhline(y=0.82, xmin=0.05, xmax=0.95, color='#cccccc', linewidth=1)
        
        # Add values with padding and larger font
        max_rows = max(len(set_values), len(actual_values))
        start_y_pos = Config.STATS_Y_POSITION
        
        for i in range(max_rows):
            y_pos = start_y_pos - (i * Config.STATS_LINE_SPACING)
            
            # Set value (left)
            if i < len(set_values):
                ax.text(0.25, y_pos, set_values[i], fontsize=13, ha='center')
            
            # Actual value (right)
            if i < len(actual_values):
                ax.text(0.75, y_pos, actual_values[i], fontsize=13, ha='center')
    
    def _create_temperature_plot(self, ax: plt.Axes) -> None:
        """
        Create the temperature plot.
        
        Args:
            ax: The matplotlib axes object to draw on
        """
        ax.plot(self.brew_data.time_seconds, self.brew_data.temperatures, 
                label='Measured Temp', color='red', zorder=5)
        
        if 'setTemp' in self.brew_data.raw_data:
            ax.axhline(self.brew_data.raw_data['setTemp'], color='r', linestyle='--', 
                      label=f'Set Temp ({self.brew_data.raw_data["setTemp"]:.1f}°C)', zorder=6)
        
        # Add average temperature line
        avg_temp = self.brew_data.average_temperature
        ax.axhline(avg_temp, color='darkred', linestyle=':', 
                  label=f'Avg Temp ({avg_temp:.1f}°C)', zorder=7)
        
        ax.set_ylabel('Temperature (°C)')
        ax.set_title('Brew Temperature')
        ax.legend(loc='upper right')
        ax.grid(True, linestyle=':', linewidth=0.5)
    
    def _create_flow_rate_plot(self, ax: plt.Axes) -> None:
        """
        Create the flow rate plot.
        
        Args:
            ax: The matplotlib axes object to draw on
        """
        ax.plot(self.brew_data.time_seconds, self.brew_data.flow_rates_raw, 
                label='Original Flow', color='lightblue', alpha=0.7, linewidth=1, zorder=5)
        
        ax.plot(self.brew_data.time_seconds, self.flow_rates_cleaned, 
                label=f'Cleaned Flow (Median k={Config.MEDIAN_FILTER_KERNEL_SIZE})', 
                color='blue', linewidth=1.5, zorder=6)
        
        # Add calculated flow rate lines
        actual_flow_rate = self.brew_data.actual_flow_rate
        if actual_flow_rate > 0:
            ax.axhline(actual_flow_rate, color='darkgreen', linestyle='--', 
                      label=f'Calculated Flow Rate ({actual_flow_rate:.1f}g/s)', zorder=7)
        
        set_flow_rate = self.brew_data.set_flow_rate
        if set_flow_rate > 0:
            ax.axhline(set_flow_rate, color='purple', linestyle=':', 
                      label=f'Set Flow Rate ({set_flow_rate:.1f}g/s)', zorder=8)
        
        ax.set_ylabel('Flow Rate (g/s)')
        ax.set_title('Flow Rate (Original vs. Cleaned)')
        ax.legend(loc='upper right')
        ax.grid(True, linestyle=':', linewidth=0.5)
        ax.set_ylim(bottom=min(np.min(self.flow_rates_cleaned), -0.5))
    
    def _create_weight_plot(self, ax: plt.Axes) -> None:
        """
        Create the weight plot.
        
        Args:
            ax: The matplotlib axes object to draw on
        """
        ax.plot(self.brew_data.time_seconds, self.brew_data.weights, 
                color='green', label='Measured Weight', zorder=5)
        
        if 'setWeight' in self.brew_data.raw_data:
           ax.axhline(self.brew_data.raw_data['setWeight'], color='green', linestyle='--', 
                     label=f'Target Weight ({self.brew_data.raw_data["setWeight"]:.1f} g)', zorder=6)
        
        ax.set_ylabel('Weight (g)')
        ax.set_title('Coffee Weight')
        ax.legend(loc='upper left')
        ax.grid(True, linestyle=':', linewidth=0.5)
    
    def _create_power_plot(self, ax: plt.Axes) -> None:
        """
        Create the power plot.
        
        Args:
            ax: The matplotlib axes object to draw on
        """
        ax.plot(self.brew_data.time_seconds, self.brew_data.powers, 
                label='Power', color='orange', zorder=5)
        
        ax.set_ylabel('Power (%)')
        ax.set_title('Pump Power')
        ax.set_xlabel('Time (s)')
        ax.legend(loc='upper right')
        ax.grid(True, linestyle=':', linewidth=0.5)
        ax.set_ylim(0, 105)
    
    def _add_brew_state_visualization(self, axes: List[plt.Axes], ax1: plt.Axes) -> None:
        """
        Add brew state background shading and text labels to all plots.
        
        Args:
            axes: List of matplotlib axes objects to add state background to
            ax1: The top plot axes used for adding text labels
        """
        last_state = None
        start_time = self.brew_data.time_seconds[0]
        added_state_labels = set()  # Keep track of labels to avoid clutter

        for i in range(self.brew_data.sample_count + 1):
            current_time = (self.brew_data.time_seconds[i] if i < self.brew_data.sample_count 
                           else self.brew_data.time_seconds[-1] + (1 / Config.SAMPLING_FREQUENCY_HZ))
            
            current_state = (self.brew_data.brew_states[i] if i < self.brew_data.sample_count 
                            else last_state)

            if current_state != last_state and i > 0:
                # State changed, process the *previous* state
                state_info = self.brew_data.get_brew_state_info(last_state)
                span_end_time = self.brew_data.time_seconds[i-1] + (0.5 / Config.SAMPLING_FREQUENCY_HZ)

                # Draw the background span on all axes
                for plot_ax in axes:
                    plot_ax.axvspan(start_time, span_end_time, 
                                   color=state_info["color"], alpha=0.2, lw=0, zorder=1)

                # Add text annotation for the previous state
                duration = span_end_time - start_time
                label_key = (last_state, round(start_time))

                # Only add text if duration is reasonable and label not added recently
                if duration > 1.0 and label_key not in added_state_labels:
                    ymin_temp, ymax_temp = ax1.get_ylim()
                    y_pos = ymax_temp - 0.05 * (ymax_temp - ymin_temp)

                    ax1.text(
                        start_time + duration * 0.1,  # X position: slightly into the span
                        y_pos,                        # Y position: near the top
                        state_info["name"],           # The state name text
                        verticalalignment='top',
                        horizontalalignment='left',
                        fontsize=9,
                        color='dimgray',
                        zorder=10
                    )
                    added_state_labels.add(label_key)

                start_time = span_end_time  # Start time for the *next* span

            if i < self.brew_data.sample_count:
                last_state = current_state

        # Add text for the final state segment
        state_info = self.brew_data.get_brew_state_info(last_state)
        span_end_time = self.brew_data.time_seconds[-1] + (0.5 / Config.SAMPLING_FREQUENCY_HZ)
        duration = span_end_time - start_time
        label_key = (last_state, round(start_time))
        
        if duration > 1.0 and label_key not in added_state_labels:
            ymin_temp, ymax_temp = ax1.get_ylim()
            y_pos = ymax_temp - 0.05 * (ymax_temp - ymin_temp)
            
            ax1.text(
                start_time + duration * 0.1, y_pos, state_info["name"],
                verticalalignment='top', horizontalalignment='left',
                fontsize=9, color='dimgray', zorder=10
            )


def main() -> None:
    """Main execution of the brew statistics program."""
    print("--- Python Executable Running Script ---")
    print(sys.executable)
    print("--------------------------------------")

    # 1. Initialize data loader
    data_loader = BrewDataLoader(
        file_path=Config.JSON_FILENAME, 
        esp_url=Config.ESP_URL
    )
    
    # 2. Load raw data
    raw_data = data_loader.load_data()
    if not raw_data:
        print("Failed to get brew data. Cannot generate plot.")
        sys.exit(1)
    
    print(raw_data)
    
    # 3. Process the raw data
    processor = BrewDataProcessor()
    brew_data = processor.process_data(raw_data)
    if not brew_data:
        print("Failed to process data arrays.")
        sys.exit(1)
    
    # 4. Create and show plots
    plotter = BrewStatePlotter(brew_data)
    
    # Try the scrollable plot first if -s or --scrollable flag is provided
    import argparse
    parser = argparse.ArgumentParser(description='Coffee Brew Analysis Tool')
    parser.add_argument('-s', '--scrollable', action='store_true', 
                        help='Use scrollable Tkinter window for display')
    args, unknown = parser.parse_known_args()
    
    if args.scrollable:
        try:
            plotter.create_scrollable_plot()
        except Exception as e:
            print(f"Failed to create scrollable plot: {e}")
            print("Falling back to standard plot.")
            plotter.create_plot()
    else:
        plotter.create_plot()


if __name__ == "__main__":
    main()
