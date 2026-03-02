import time
import serial
import struct
import matplotlib.pyplot as plt

def set_lo_amplitude(port, amp_frac):
    print(f"Set LO amplitude to {amp_frac}")
    AMP = int(amp_frac * 0x3FF) & 0x3FF
    msg = struct.pack('>cH', b'l', AMP)
    send_byte_array_to_pic(port, msg)

def set_trap_amplitude(port, amp_frac):
    print(f"Set trap amplitude to {amp_frac}")
    AMP = int(amp_frac * 0x3FF) & 0x3FF
    msg = struct.pack('>cH', b't', AMP)
    send_byte_array_to_pic(port, msg)

def with_serial(port, baudrate, timeout, func, *args, **kwargs):
    """Helper to open a serial port, run a function, and handle retries."""
    for attempt in range(10):
        try:
            with serial.Serial(port, baudrate, timeout=timeout) as ser:
                return func(ser, *args, **kwargs)
        except Exception as e:
            print(f"Serial error (attempt {attempt+1}): {e}")
            time.sleep(0.001)
    print("Failed to open serial port after 10 attempts.")
    return None

def send_byte_array_to_pic(port, byte_array):
    def inner(ser):
        ser.write(byte_array)
        time.sleep(0.001)
        return ser.read(64)
    return with_serial(port, 9600, 1, inner)

def write_channel_phase(port, channel, phase_deg):
    print(f"Set channel {channel} phase to {phase_deg} degrees")
    POW = int((phase_deg / 360.0) * (2**14)) & 0x3FFF
    msg = struct.pack('>cBH', b'q', channel, POW)
    send_byte_array_to_pic(port, msg)

def send_scan_command(ser, f_lo, f_hi, n_steps, k):
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    cmd = bytearray([ord('s')])
    cmd += int(f_lo).to_bytes(4, 'big')
    cmd += int(f_hi).to_bytes(4, 'big')
    cmd += int(n_steps).to_bytes(2, 'big')
    cmd.append(int(k) & 0xFF)
    cmd += bytes(64 - len(cmd))
    ser.write(cmd)

    expected = n_steps * 8  # 4B freq + 2B ch0 + 2B ch1
    resp = bytearray()
    deadline = time.time() + 60
    while len(resp) < expected:
        if time.time() > deadline:
            raise TimeoutError("USB read timeout")
        chunk = ser.read(expected - len(resp))
        if chunk:
            resp += chunk

    out = []
    for i in range(n_steps):
        base = 8 * i
        freq = int.from_bytes(resp[base:base+4], 'big')
        ch0  = int.from_bytes(resp[base+4:base+6], 'big')
        ch1  = int.from_bytes(resp[base+6:base+8], 'big')
        out.append((freq, ch0, ch1))
    return out


def code_to_volts(code, k, vref=3.3):
    resolution = 1023 * (4 ** k)  # 10-bit ADC, oversampled by 4^k
    return code * vref / (resolution)     # codes are scaled by 2^k

# ...existing code...
import io
from PIL import Image

def main():
    port = 'COM7'
    f_lo, f_hi = 20_300_000, 20_900_000  # 20.3 to 20.6 MHz
    n_steps, k = 128, 3
    set_lo_amplitude(port, 0.5)      # Set LO amplitude to 0.5
    trap_amp = 1
    set_trap_amplitude(port, trap_amp)  # Set trap amplitude to 0.5

    phases = list(range(0, 361, 10))  # 0, 10, ..., 360
    images = []

    for phase in phases:
        write_channel_phase(port, 3, phase)
        print(f"\nscan {f_lo/1e6:.2f}→{f_hi/1e6:.2f} MHz, steps={n_steps}, k={k}, phase={phase}")
        def scan_with_ser(ser):
            return send_scan_command(ser, f_lo, f_hi, n_steps, k)
        results = with_serial(port, 9600, 60, scan_with_ser)
        print(results)
        if results is None:
            print(f"Scan failed for phase {phase}.")
            continue
        freqs = []
        v0s = []
        v1s = []
        for freq, ch0, ch1 in results:
            v0 = code_to_volts(ch0, k)
            v1 = code_to_volts(ch1, k)
            freqs.append(freq / 1e6)  # MHz
            v0s.append(v0)
            v1s.append(v1)
        print(freqs)

        # Plot and save each phase as an image in memory
        plt.figure(figsize=(8, 5))
        plt.plot(freqs, v0s, label='ch0')
        plt.plot(freqs, v1s, label='ch1', linestyle='--')
        plt.axhline(3.3/2, color='gray', linestyle=':', linewidth=1, label='Center (1.65 V)')
        plt.ylim(0, 3.5)
        plt.xlabel('Frequency (MHz)')
        plt.ylabel('Voltage (V)')
        plt.title(f'Voltage vs Frequency (phase={phase}°, amp=0.5)')
        plt.legend()
        plt.grid(True)
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close()
        buf.seek(0)
        images.append(Image.open(buf).convert('RGB'))
        buf.close()

    # Save all images as a GIF
    if images:
        images[0].save('scan_phases.gif', save_all=True, append_images=images[1:], duration=400, loop=0)
        print("Saved scan_phases.gif")

# ...existing code...

if __name__ == "__main__":
    main()