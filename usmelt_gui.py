import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import usmelt
import time

class MelterApp:
    def __init__(self, master):
        self.master = master
        master.title("Melter Control")
        self.init_pg()  # Initialize the pulse generator


        # --- Menu Bar ---
        self.menubar = tk.Menu(master)
        self.filemenu = tk.Menu(self.menubar, tearoff=0)
        self.filemenu.add_command(label="Set Device...", command=self.set_device)
        self.filemenu.add_separator()
        self.filemenu.add_command(label="Exit", command=master.quit)
        self.menubar.add_cascade(label="Settings", menu=self.filemenu)
        master.config(menu=self.menubar)  # Add the menu bar to the window

        # --- Pulse Length ---
        self.pulse_length_label = ttk.Label(master, text="Pulse Length (µs):")
        self.pulse_length_label.grid(row=0, column=0, sticky="w", padx=5, pady=5)

        self.pulse_length_var = tk.StringVar(value="20")  # Default value
        self.pulse_length_entry = ttk.Entry(master, textvariable=self.pulse_length_var, width=10)
        self.pulse_length_entry.grid(row=0, column=1, sticky="e", padx=5, pady=5)
        self.pulse_length_entry.bind("<Return>", self.validate_inputs) # Validate on Enter key

        # --- Melt Button ---
        self.melt_button = ttk.Button(master, text="Melt! (single pulse)", command=self.melt)
        self.melt_button.grid(row=2, column=0, columnspan=2, pady=10)


    def init_pg(self):
        # First find the USB device that corresponds to the pulse generator
        device = usmelt.discover(['TG5012A'])
        self.device_name = device['TG5012A'].device  # Store the device name
        self.pulse_V = 5.0
        self.pg = usmelt.TG5012A(serial_port=self.device_name)
        self.pg.channel(1)        
        self.pg.wave('PULSE')
        # We use a short period so we can repeat the pulse quickly if needed
        self.pg.pulse_period(10e-3)
        self.pg.amplitude(self.pulse_V)
        self.pg.offset(0)
        # 10 ns rise and fall times
        self.pg.pulse_rise(10e-9)
        self.pg.pulse_fall(10e-9)
        # Set in burst mode, with 1 pulse per burst with manual trigger
        self.pg.burst("NCYC")
        self.pg.burst_count(1)
        self.pg.trigger_src("MAN")
        # Turn on output. Nothing will happen until we trigger the pulse.xs
        self.pg.output("ON")

    def validate_inputs(self, event=None):
        """Validates the pulse length and power inputs."""
        try:
            pulse_length = int(self.pulse_length_var.get())
            if pulse_length <= 0:
                raise ValueError("Pulse length must be greater than 0.")

            return pulse_length  # Return the validated values
        except ValueError as e:
            messagebox.showerror("Input Error", str(e))
            return None, None  # Return None if validation fails

    def melt(self):
        """Handles the 'Melt!' button click."""
        pulse_length = self.validate_inputs()

        if pulse_length is not None:
            # In a real application, you would send these values to your hardware here.
            print(f"Melting with pulse length: {pulse_length} µs")
            #messagebox.showinfo("Melting", f"Melting with:\nPulse Length: {pulse_length} µs\n")
            self.pg.pulse_width(pulse_length*1e-6)
            self.pg.trigger()
    


    def set_device(self):
        """Opens a dialog to set the device name."""
        new_device = simpledialog.askstring(
            "Set Device", "Enter device name:", parent=self.master, initialvalue=self.device_name
        )
        if new_device is not None:  # Check if the user clicked Cancel
            self.device_name = new_device
            self.device_label.config(text=f"Device: {self.device_name}")
            self.pg = usmelt.TG5012A(serial_port=new_device)


root = tk.Tk()
app = MelterApp(root)
root.mainloop()

