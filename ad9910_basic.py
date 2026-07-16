import tkinter as tk
from tkinter import ttk
from adriq.ad9910 import *
import time
import serial.tools.list_ports
from adriq.Custom_Tkinter import CustomSpinbox, CustomIntSpinbox
import threading

# Global flags and threads
scanning = False
scan_thread = None
flash_thread = None
# New: event to control flashing thread safely
flash_stop_event = threading.Event()


def _bits(value: int, hi: int, lo: int | None = None) -> int:
    """Extract bit(s) from value. If lo is None, extracts single bit hi."""
    if lo is None:
        return (value >> hi) & 0x1
    if hi < lo:
        hi, lo = lo, hi
    mask = (1 << (hi - lo + 1)) - 1
    return (value >> lo) & mask


def _decode_cfr1(value: int) -> list[str]:
    return [
        f"RAM_Enable={_bits(value, 31)}",
        f"RAM_Destination={_bits(value, 30, 29)}",
        f"Manual_OSK_External_Control={_bits(value, 23)}",
        f"Inverse_Sinc_Filter_Enable={_bits(value, 22)}",
        f"OPEN_bit21={_bits(value, 21)}",
        f"Internal_Profile={_bits(value, 20, 17):04b}",
        f"Sin={_bits(value, 16)}",
        f"Load_LRR_At_IO_Update={_bits(value, 15)}",
        f"Autoclear_Digital_Ramp_Accumulator={_bits(value, 14)}",
        f"Autoclear_Phase_Accumulator={_bits(value, 13)}",
        f"Clear_Digital_Ramp_Accumulator={_bits(value, 12)}",
        f"Clear_Phase_Accumulator={_bits(value, 11)}",
        f"Load_ARR_At_IO_Update={_bits(value, 10)}",
        f"OSK_Enable={_bits(value, 9)}",
        f"Select_Auto_OSK={_bits(value, 8)}",
        f"Digital_Power_Down={_bits(value, 7)}",
        f"DAC_Power_Down={_bits(value, 6)}",
        f"REF_CLK_Input_Power_Down={_bits(value, 5)}",
        f"Aux_DAC_Power_Down={_bits(value, 4)}",
        f"External_Power_Down_Control={_bits(value, 3)}",
        f"OPEN_bit2={_bits(value, 2)}",
        f"SDIO_Input_Only={_bits(value, 1)}",
        f"OPEN_bit0={_bits(value, 0)}",
    ]


def _decode_cfr2(value: int) -> list[str]:
    return [
        f"OPEN_bits31_25={_bits(value, 31, 25):07b}",
        f"Enable_Amplitude_Scale={_bits(value, 24)}",
        f"Internal_IO_Update_Active={_bits(value, 23)}",
        f"SYNC_CLK_Enable={_bits(value, 22)}",
        f"Digital_Ramp_Destination={_bits(value, 21, 20):02b}",
        f"Digital_Ramp_Enable={_bits(value, 19)}",
        f"Digital_Ramp_No_Dw_High={_bits(value, 18)}",
        f"Digital_Ramp_No_Dw_Low={_bits(value, 17)}",
        f"Read_Effective_FTW={_bits(value, 16)}",
        f"IO_Update_Rate_Control={_bits(value, 15, 14):02b}",
        f"OPEN_bit13={_bits(value, 13)}",
        f"OPEN_bit12={_bits(value, 12)}",
        f"PDCLK_Enable={_bits(value, 11)}",
        f"PDCLK_Invert={_bits(value, 10)}",
        f"Tx_Enable_Invert={_bits(value, 9)}",
        f"OPEN_bit8={_bits(value, 8)}",
        f"Matched_Latency_Enable={_bits(value, 7)}",
        f"Data_Assembler_Hold_Last_Value={_bits(value, 6)}",
        f"Sync_Timing_Validation_Disable={_bits(value, 5)}",
        f"Parallel_Data_Port_Enable={_bits(value, 4)}",
        f"FM_Gain={_bits(value, 3, 0):04b}",
    ]


def _decode_cfr3(value: int) -> list[str]:
    return [
        f"OPEN_bits31_30={_bits(value, 31, 30):02b}",
        f"DRV0={_bits(value, 29, 28):02b}",
        f"OPEN_bit27={_bits(value, 27)}",
        f"VCO_SEL={_bits(value, 26, 24):03b}",
        f"OPEN_bits23_22={_bits(value, 23, 22):02b}",
        f"Icp={_bits(value, 21, 19):03b}",
        f"OPEN_bits18_16={_bits(value, 18, 16):03b}",
        f"REFCLK_Input_Divider_Bypass={_bits(value, 15)}",
        f"REFCLK_Input_Divider_ResetB={_bits(value, 14)}",
        f"OPEN_bits13_11={_bits(value, 13, 11):03b}",
        f"PFD_Reset={_bits(value, 10)}",
        f"OPEN_bit9={_bits(value, 9)}",
        f"PLL_Enable={_bits(value, 8)}",
        f"PLL_Multiplier={_bits(value, 7, 1)}",
        f"OPEN_bit0={_bits(value, 0)}",
    ]


def _decode_mcsr(value: int) -> list[str]:
    return [
        f"Sync_Validation_Delay={_bits(value, 31, 28)}",
        f"Sync_Receiver_Enable={_bits(value, 27)}",
        f"Sync_Generator_Enable={_bits(value, 26)}",
        f"Sync_Generator_Polarity={_bits(value, 25)}",
        f"OPEN_bit24={_bits(value, 24)}",
        f"Sync_State_Preset_Value={_bits(value, 23, 18)}",
        f"OPEN_bits17_16={_bits(value, 17, 16):02b}",
        f"Output_Sync_Generator_Delay={_bits(value, 15, 11)}",
        f"OPEN_bits10_8={_bits(value, 10, 8):03b}",
        f"Input_Sync_Receiver_Delay={_bits(value, 7, 3)}",
        f"OPEN_bits2_0={_bits(value, 2, 0):03b}",
    ]


def _decode_ad(value: int) -> list[str]:
    return [
        f"AuxDAC_Code={_bits(value, 7, 0)}",
        f"OPEN_bits31_8={_bits(value, 31, 8):024b}",
    ]


def _decode_register(reg: str, value: int) -> list[str]:
    if reg == "CFR1":
        return _decode_cfr1(value)
    if reg == "CFR2":
        return _decode_cfr2(value)
    if reg == "CFR3":
        return _decode_cfr3(value)
    if reg == "MCSR":
        return _decode_mcsr(value)
    if reg == "AD":
        return _decode_ad(value)
    return []


def _readback_and_print_registers(port: str, board: int, mode: str, stage: str = "AFTER"):
    mode_norm = mode.strip().lower()
    regs = ["CFR1", "CFR2", "CFR3", "AD"]
    if mode_norm in {"master", "slave"}:
        regs.append("MCSR")

    print(f"\n--- AD9910 General Settings Readback ({stage}) ---")
    print(f"Port={port} Board={board} Mode={mode}")
    for reg in regs:
        last_exc = None
        value = None
        raw = None
        for attempt in range(3):
            try:
                value, raw = read_from_ad9910(port, reg, board, Verbose=False)
                last_exc = None
                break
            except Exception as e:
                last_exc = e
                time.sleep(0.05)

        if last_exc is not None or value is None:
            print(f"{reg}: READ FAILED ({type(last_exc).__name__}): {last_exc}")
            continue

        try:
            raw_hex = raw.hex() if hasattr(raw, "hex") else str(raw)
        except Exception:
            raw_hex = str(raw)

        value_int = int(value)
        print(f"{reg}: 0x{value_int:08X}  raw={raw_hex}")

        decoded_lines = _decode_register(reg, value_int)
        if decoded_lines:
            for line in decoded_lines:
                print(f"  {line}")

    print("--- End Readback ---\n")

# Function to apply settings
def apply_settings(event=None):
    Standalone_Boards = com_port_var.get()
    Board = int(board_var.get())
    profile = int(profile_var.get())
    A = amplitude_slider.get()
    f = frequency_slider.get() / 10.0  # Scale down the frequency value
    p = 0  # Assuming phase is fixed at 0

    print("Profile Setting profile:", profile, "of Board:", Board, "on COM port:", Standalone_Boards, "Amplitude:", A, "Frequency:", f, "Phase:", p)
    single_tone_profile_setting(Standalone_Boards, Board, profile, PLL_Multiplier=40, Amplitude=A, Phase_Offset=p, Frequency=f, Verbose=True)

# Function to apply general settings
def apply_general_settings():
    Standalone_Boards = com_port_var.get()
    Board = int(board_var.get())
    mode = mode_var.get().strip().lower()
    print("General Setting Mode:", mode_var.get(), "Board:", Board, "on COM port:", Standalone_Boards)

    # Read back registers BEFORE applying settings.
    threading.Thread(
        target=_readback_and_print_registers,
        args=(Standalone_Boards, Board, mode_var.get(), "BEFORE"),
        daemon=True,
    ).start()

    mode_to_fn = {
        "standalone": general_setting_standalone,
        "master": general_setting_master,
        "slave": general_setting_slave,
        "standalone weak": general_setting_standalone_weak,
    }

    fn = mode_to_fn.get(mode)
    if fn is None:
        raise ValueError(f"Unknown general settings mode: {mode_var.get()!r}")
    fn(Standalone_Boards, Board, Verbose=True)

    # Read back registers AFTER applying settings.
    threading.Thread(
        target=_readback_and_print_registers,
        args=(Standalone_Boards, Board, mode_var.get(), "AFTER"),
        daemon=True,
    ).start()

# Function to get available COM ports
def get_com_ports():
    ports = serial.tools.list_ports.comports()
    return [port.device for port in ports]

# Function to reset the upper limit of the slider
def reset_upper_limit(event=None):
    upper_limit_spinbox.set(5000)
    amplitude_slider.config(to=5000)

# Function to scan frequency
def scan_frequency():
    global scanning
    scanning = True
    Standalone_Boards = com_port_var.get()
    Board = int(board_var.get())
    profile = int(profile_var.get())
    A = amplitude_slider.get()
    f_start = float(frequency_start_entry.get())
    f_end = float(frequency_end_entry.get())
    points = int(points_entry.get())
    timestep = float(timestep_entry.get())

    f_step = (f_end - f_start) / (points - 1)
    while scanning:
        # Scan up
        for i in range(points):
            if not scanning:
                break
            f = f_start + i * f_step
            print(f"Scanning frequency: {f} Hz")
            single_tone_profile_setting(Standalone_Boards, Board, profile, PLL_Multiplier=40, Amplitude=A, Phase_Offset=0, Frequency=f, Verbose=False)
            time.sleep(timestep)
        # Scan down
        for i in range(points):
            if not scanning:
                break
            f = f_end - i * f_step
            print(f"Scanning frequency: {f} Hz")
            single_tone_profile_setting(Standalone_Boards, Board, profile, PLL_Multiplier=40, Amplitude=A, Phase_Offset=0, Frequency=f, Verbose=False)
            time.sleep(timestep)

# Function to start scanning in a new thread
def start_scan_thread():
    global scan_thread
    if scan_thread is None or not scan_thread.is_alive():
        scan_thread = threading.Thread(target=scan_frequency)
        scan_thread.start()

# Function to stop scanning
def stop_scanning():
    global scanning
    scanning = False
    if scan_thread is not None:
        scan_thread.join()

# Function to flash amplitude (thread worker) - no Tk access here
def flash_amplitude(Standalone_Boards, Board, profile, flash_amp, on_time, off_time, freq):
    # Loop until stop requested
    while not flash_stop_event.is_set():
        # Amplitude ON
        single_tone_profile_setting(Standalone_Boards, Board, profile, PLL_Multiplier=40, Amplitude=flash_amp, Phase_Offset=0, Frequency=freq, Verbose=False)
        if flash_stop_event.wait(on_time):
            break
        # Amplitude OFF
        single_tone_profile_setting(Standalone_Boards, Board, profile, PLL_Multiplier=40, Amplitude=0, Phase_Offset=0, Frequency=freq, Verbose=False)
        if flash_stop_event.wait(off_time):
            break

# Function to start flashing in a new thread
def start_flash_thread():
    global flash_thread
    # Cache all Tk values on the main thread (thread-safe)
    Standalone_Boards = com_port_var.get()
    Board = int(board_var.get())
    profile_val = int(profile_var.get())
    flash_amp = int(flash_amplitude_entry.get())
    on_time = float(on_time_entry.get())
    off_time = float(off_time_entry.get())
    freq = frequency_slider.get() / 10.0  # scale down

    if flash_thread is None or not flash_thread.is_alive():
        flash_stop_event.clear()
        flash_thread = threading.Thread(
            target=flash_amplitude,
            args=(Standalone_Boards, Board, profile_val, flash_amp, on_time, off_time, freq),
            daemon=True
        )
        flash_thread.start()

# Function to stop flashing
def stop_flashing():
    global flash_thread
    flash_stop_event.set()
    if flash_thread is not None and flash_thread.is_alive():
        flash_thread.join()
    flash_thread = None
    flash_stop_event.clear()

# Function to update the displayed frequency value
def update_frequency_label(event=None):
    frequency_value = frequency_slider.get() / 10.0
    frequency_label_var.set(f"Frequency: {frequency_value:.1f} Hz")

# Create main window
root = tk.Tk()
root.title("AD9910 Profile Settings")

# COM port selection
tk.Label(root, text="COM Port").pack()
com_port_var = tk.StringVar()
com_port_menu = ttk.Combobox(root, textvariable=com_port_var)
com_port_menu['values'] = get_com_ports()
com_port_menu.current(0)  # Default to the first available COM port
com_port_menu.pack()
com_port_menu.bind("<<ComboboxSelected>>", reset_upper_limit)

# Amplitude slider
tk.Label(root, text="Amplitude").pack()
amplitude_slider = tk.Scale(root, from_=0, to=5000, orient=tk.HORIZONTAL, length=400)
amplitude_slider.set(1500)
amplitude_slider.pack()
amplitude_slider.bind("<ButtonRelease-1>", apply_settings)

# Frequency slider
tk.Label(root, text="Frequency").pack()
frequency_slider = tk.Scale(root, from_=1000, to=4000, orient=tk.HORIZONTAL, length=400, resolution=1)  # Scale up by 10
frequency_slider.set(2000)
frequency_slider.pack()
frequency_slider.bind("<ButtonRelease-1>", apply_settings)
frequency_slider.bind("<Motion>", update_frequency_label)

# Frequency label
frequency_label_var = tk.StringVar()
frequency_label_var.set(f"Frequency: {frequency_slider.get() / 10.0:.1f} Hz")
frequency_label = tk.Label(root, textvariable=frequency_label_var)
frequency_label.pack()

# Upper limit spinbox
tk.Label(root, text="Amplitude Upper Limit").pack()
upper_limit_spinbox = CustomSpinbox(root, from_=0, to=2**14-1, increment=100) #14 bit ASF
upper_limit_spinbox.set(5000)
upper_limit_spinbox.pack()
upper_limit_spinbox.bind("<ButtonRelease-1>", lambda event: amplitude_slider.config(to=int(upper_limit_spinbox.get())))

# Board selection
tk.Label(root, text="Board").pack()
board_var = tk.StringVar()
board_menu = ttk.Combobox(root, textvariable=board_var)
board_menu['values'] = [str(i) for i in range(10)]
board_menu.current(3)  # Default to Board 3
board_menu.pack()
board_menu.bind("<<ComboboxSelected>>", reset_upper_limit)

# General settings mode selection
tk.Label(root, text="General Settings Mode").pack()
mode_var = tk.StringVar()
mode_menu = ttk.Combobox(root, textvariable=mode_var, state="readonly")
mode_menu['values'] = ["Standalone", "Standalone Weak", "Master", "Slave"]
mode_menu.current(0)  # Default to Standalone
mode_menu.pack()

# Profile selection
tk.Label(root, text="Profile").pack()
profile_var = tk.StringVar()
profile_menu = ttk.Combobox(root, textvariable=profile_var)
profile_menu['values'] = [str(i) for i in range(8)]
profile_menu.current(0)  # Default to Profile 7
profile_menu.pack()

# Frequency scan settings
tk.Label(root, text="Frequency Start (Hz)").pack()
frequency_start_entry = tk.Entry(root)
frequency_start_entry.pack()

tk.Label(root, text="Frequency End (Hz)").pack()
frequency_end_entry = tk.Entry(root)
frequency_end_entry.pack()

tk.Label(root, text="Number of Points").pack()
points_entry = tk.Entry(root)
points_entry.pack()

tk.Label(root, text="Timestep (s)").pack()
timestep_entry = tk.Entry(root)
timestep_entry.pack()

# Flash amplitude settings
tk.Label(root, text="Flash Amplitude").pack()
flash_amplitude_entry = tk.Entry(root)
flash_amplitude_entry.pack()

tk.Label(root, text="On Time (s)").pack()
on_time_entry = tk.Entry(root)
on_time_entry.pack()

tk.Label(root, text="Off Time (s)").pack()
off_time_entry = tk.Entry(root)
off_time_entry.pack()

# Apply General Settings button
general_settings_button = tk.Button(root, text="Apply General Settings", command=apply_general_settings)
general_settings_button.pack()

# Frequency Scan button
scan_button = tk.Button(root, text="Scan Frequency", command=start_scan_thread)
scan_button.pack()

# Stop Scan button
stop_button = tk.Button(root, text="Stop Scan", command=stop_scanning)
stop_button.pack()

# Flash Amplitude button
flash_button = tk.Button(root, text="Flash Amplitude", command=start_flash_thread)
flash_button.pack()

# Stop Flash button
stop_flash_button = tk.Button(root, text="Stop Flash", command=stop_flashing)
stop_flash_button.pack()

# Run the GUI loop
root.mainloop()