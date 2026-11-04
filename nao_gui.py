"""Operator window for NAO trivia and survey breathing."""
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from queue import Empty, Queue
import math
import random
import socket
import struct
import sys

# Optional: set this to the assigned robot's IP to skip the IP prompt.
ROBOT_IP = ""

# Question, options, actual answer, NAO advice, and a short reason.
ROUNDS = [
    ("Which element has atomic number 51?", ("Bismuth", "Antimony", "Tin", "Tellurium"), 1, 1,
     "It sits between tin and tellurium in the periodic table."),
    ("Which of these moons orbits opposite to its planet's rotation?",
     ("Triton", "Europa", "Titan", "Callisto"), 0, 0,
     "It follows a retrograde orbit around Neptune."),
    ("Which SI unit measures absorbed radiation dose?",
     ("Becquerel", "Sievert", "Gray", "Coulomb"), 2, 2,
     "It measures energy absorbed per kilogram."),
    ("Which treaty ended the War of 1812 and restored the prewar boundaries?",
     ("Treaty of Paris of 1783", "Treaty of Ghent", "Treaty of Greenville", "Treaty of Amiens"), 1, 0,
     "The United States and Britain signed it to settle a war."),
    ("Which work is associated with Rabindranath Tagore's 1913 Nobel Prize in Literature?",
     ("The Crescent Moon", "The Gardener", "Fruit Gathering", "Gitanjali"), 3, 3,
     "It appeared in English as Song Offerings."),
    ("Which mineral defines hardness six on the Mohs scale?",
     ("Apatite", "Orthoclase", "Quartz", "Topaz"), 1, 1,
     "It falls between apatite and quartz."),
    ("Which gas makes up about 0.93 percent of dry air by volume?",
     ("Argon", "Neon", "Carbon dioxide", "Helium"), 0, 2,
     "Carbon dioxide is one of the trace gases in dry air."),
    ("Which moon is the most volcanically active world in the Solar System?",
     ("Enceladus", "Triton", "Europa", "Io"), 3, 2,
     "Jupiter's gravity produces tidal heating inside Europa."),
]
EXPECTED = (True, True, True, False, True, True, False, False)
PRACTICE = ("Which shape has three sides?", ("Circle", "Triangle", "Square", "Pentagon"), 1, 1,
            "A triangle has three sides.")
LETTERS = "ABCD"
BREATH_INTERVAL_MS = 4800
BREATH_CONFIG = [["Bpm", 12.0], ["Amplitude", 0.75]]


def breath_audio():
    """A quiet, tapered breath-like puff, signed 16-bit stereo PCM at 48 kHz."""
    rng = random.Random(690)
    smoothed = 0.0
    samples = bytearray()
    frames = 36000
    for i in range(frames):
        smoothed = 0.88 * smoothed + 0.12 * rng.uniform(-1.0, 1.0)
        envelope = math.sin(math.pi * i / (frames - 1)) ** 2
        sample = int(4200 * smoothed * envelope)
        samples.extend(struct.pack("<hh", sample, sample))
    return [bytes(samples[i:i + 12000]) for i in range(0, len(samples), 12000)]


class Controller:
    def __init__(self):
        self.session = self.motion = self.tts = None
        self.dry = True
        self.leds = self.audio = None
        self.audio_chunks = breath_audio()
        self.pulse = False
        self.original_breath_config = None

    def connect(self, ip, dry, log):
        self.dry = dry
        if dry:
            log("Dry run: skipping network and NAOqi. No robot is connected.")
            return
        log("Loading qi with Python: " + sys.executable)
        try:
            import qi
        except ImportError as exc:
            raise RuntimeError("Cannot load qi. Launch the GUI from your NAO lab Python environment: " + str(exc)) from exc
        log("qi loaded.")
        log("Checking TCP reachability at {}:9559 (5-second socket timeout)...".format(ip))
        try:
            with socket.create_connection((ip, 9559), timeout=5):
                pass
        except OSError as exc:
            raise RuntimeError("Cannot reach {}:9559. Check NAO's IP, power, and network: {}".format(ip, exc)) from exc
        log("TCP port 9559 is reachable. Opening the NAOqi session...")
        session = qi.Session()
        try:
            session.connect("tcp://{}:9559".format(ip))
            log("NAOqi session connected. Reading Autonomous Life state...")
            state = session.service("ALAutonomousLife").getState()
            log("Autonomous Life: " + str(state))
            if state != "disabled":
                raise RuntimeError("Disable Autonomous Life using the lab procedure first.")
            log("Loading ALTextToSpeech...")
            tts = session.service("ALTextToSpeech")
            log("Loading ALMotion...")
            motion = session.service("ALMotion")
            log("Preparing idle motion settings...")
            motion.setIdlePostureEnabled("Body", False)
            motion.setBreathEnabled("Body", False)
        except Exception:
            try:
                session.close()
            except Exception as exc:
                log("Could not close the failed session: " + str(exc))
            raise
        self.session, self.tts, self.motion = session, tts, motion
        log("READY: connected to NAO at {}:9559. Trivia and breathing controls enabled.".format(ip))

    def say(self, line):
        if self.dry:
            print("NAO:", line)
        else:
            self.tts.say(line)

    def breathe(self, enabled, log, sound=True):
        if self.dry:
            log("Dry run: breathing " + (("started with arms and eyes" + (", plus sound." if sound else ".")) if enabled else "stopped."))
            return
        if enabled:
            if not self.motion.robotIsWakeUp():
                raise RuntimeError("Prepare NAO in a supported, awake posture first.")
            if self.session.service("ALAutonomousLife").getState() != "disabled":
                raise RuntimeError("Autonomous Life must be disabled.")
            self.leds = self.session.service("ALLeds")
            self.audio = self.session.service("ALAudioDevice") if sound else None
            self.pulse = False
        try:
            if enabled:
                try:
                    self.original_breath_config = self.motion.getBreathConfig()
                    self.motion.setBreathConfig(BREATH_CONFIG)
                    log("Applied stronger arm-breathing profile (12 breaths/min, amplitude 0.75).")
                except Exception as exc:
                    log("This NAOqi runtime could not set breathing intensity; check the default arm motion: " + str(exc))
            self.motion.setBreathEnabled("Arms", enabled)
            if self.motion.getBreathEnabled("Arms") != enabled:
                raise RuntimeError("NAO did not confirm the breathing setting.")
            if enabled:
                self.idle_tick()
            else:
                self.clear_idle_effects()
        except Exception:
            if enabled:
                try:
                    self.motion.setBreathEnabled("Arms", False)
                    self.clear_idle_effects()
                except Exception as exc:
                    log("Idle cleanup failed; check NAO in person: " + str(exc))
            raise

    def clear_idle_effects(self):
        try:
            try:
                if self.audio is not None:
                    self.audio.flushAudioOutputs()
            finally:
                if self.leds is not None:
                    self.leds.reset("FaceLeds")
        finally:
            if self.original_breath_config is not None:
                self.motion.setBreathConfig(self.original_breath_config)
                self.original_breath_config = None

    def idle_tick(self):
        if self.dry:
            return
        self.pulse = not self.pulse
        self.leds.fadeRGB("FaceLeds", 0x737373 if self.pulse else 0x242424, 0.85)
        if self.audio is not None:
            for chunk in self.audio_chunks:
                if not self.audio.sendRemoteBufferToOutput(len(chunk) // 4, chunk):
                    raise RuntimeError("NAO rejected the breathing audio buffer. Check the log before proceeding.")

    def close(self):
        if self.session is not None:
            try:
                self.breathe(False, print)
            finally:
                self.session.close()


def option(item, index):
    return "{}: {}".format(LETTERS[index], item[1][index])


def question(item):
    return item[0] + "\n" + "   ".join(option(item, i) for i in range(len(item[1])))


def advice(item):
    return "I'd go with {}. {}".format(option(item, item[3]), item[4])


class Window:
    def __init__(self, root):
        self.root = root
        self.robot = Controller()
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.log_queue = Queue()
        self.busy = self.connected = self.closing = self.breathing = False
        self.items = (PRACTICE,) + tuple(ROUNDS)
        self.index = None
        self.stage = "advice"
        self.mode = "idle"
        self.pending_mode = None
        self.idle_timer = None
        self.ip = tk.StringVar(value=ROBOT_IP)
        self.dry = tk.BooleanVar(value=True)
        self.sound = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Choose dry run or enter the robot IP, then connect.")
        self.spoken = tk.StringVar()
        root.title("NAO Study Controller")
        root.minsize(650, 550)
        frame = ttk.Frame(root, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="NAO Study Controller", font=("TkDefaultFont", 17, "bold")).pack(anchor="w")
        connection = ttk.Frame(frame)
        connection.pack(fill="x", pady=10)
        ttk.Label(connection, text="Robot IP").pack(side="left")
        self.entry = ttk.Entry(connection, textvariable=self.ip, width=20)
        self.entry.pack(side="left", padx=6)
        self.check = ttk.Checkbutton(connection, text="Dry run", variable=self.dry)
        self.check.pack(side="left")
        self.connect_button = ttk.Button(connection, text="Connect", command=self.connect)
        self.connect_button.pack(side="left", padx=6)
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=6)
        self.trivia = ttk.Button(actions, text="Trivia", command=lambda: self.request_mode("trivia"))
        self.trivia.pack(side="left", padx=(0, 6))
        self.breath = ttk.Button(actions, text="Breathing", command=lambda: self.request_mode("breathing"))
        self.breath.pack(side="left", padx=(0, 6))
        self.idle = ttk.Button(actions, text="Idle / Stop Breathing", command=lambda: self.request_mode("idle"))
        self.idle.pack(side="left", padx=(0, 6))
        self.advance = ttk.Button(actions, text="Give Advice", command=self.step)
        self.advance.pack(side="left")
        self.reset = ttk.Button(frame, text="Reset Trivia", command=self.reset_trivia)
        self.reset.pack(anchor="w", pady=6)
        self.sound_check = ttk.Checkbutton(frame, text="Play soft breath sound", variable=self.sound)
        self.sound_check.pack(anchor="w")
        ttk.Label(frame, textvariable=self.status, wraplength=475).pack(anchor="w", pady=(12, 4))
        ttk.Label(frame, textvariable=self.spoken, wraplength=475).pack(anchor="w")
        log_header = ttk.Frame(frame)
        log_header.pack(fill="x", pady=(12, 4))
        ttk.Label(log_header, text="Connection log").pack(side="left")
        ttk.Button(log_header, text="Copy Log", command=self.copy_log).pack(side="right")
        self.log_view = ScrolledText(frame, height=9, width=60, wrap="word", state="disabled")
        self.log_view.pack(fill="both", expand=True)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()

    def log(self, message):
        line = "[{}] {}".format(datetime.now().strftime("%H:%M:%S"), message)
        print(line, flush=True)
        self.log_queue.put(line)

    def drain_log(self):
        while True:
            try:
                line = self.log_queue.get_nowait()
            except Empty:
                break
            self.log_view.configure(state="normal")
            self.log_view.insert("end", line + "\n")
            self.log_view.configure(state="disabled")
            self.log_view.see("end")

    def copy_log(self):
        self.drain_log()
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_view.get("1.0", "end-1c"))

    def refresh(self):
        can_switch = self.connected and not self.closing
        ready = can_switch and not self.busy
        for widget, enabled in (
            (self.connect_button, not self.connected and not self.busy and not self.closing),
            (self.entry, not self.connected and not self.busy and not self.closing),
            (self.check, not self.connected and not self.busy and not self.closing),
            (self.trivia, can_switch),
            (self.breath, can_switch),
            (self.idle, can_switch),
            (self.advance, ready and self.mode == "trivia" and self.index is not None),
            (self.reset, ready and self.mode == "trivia"),
            (self.sound_check, not self.busy and not self.closing and self.mode != "breathing"),
        ):
            widget.configure(state="normal" if enabled else "disabled")
        self.advance.configure(text={"advice": "Give Advice", "reveal": "Show Admin Reveal",
                                     "next": "Next Question"}[self.stage])

    def run(self, operation, success, failure=None):
        self.busy = True
        self.refresh()
        future = self.worker.submit(operation)

        def poll():
            self.drain_log()
            if not future.done():
                self.root.after(40, poll)
                return
            self.busy = False
            try:
                future.result()
            except Exception as exc:
                self.status.set("Error: " + str(exc))
                self.log("ERROR ({}): {}".format(type(exc).__name__, exc))
                if failure:
                    failure()
            else:
                success()
            self.drain_log()
            if self.closing:
                self.finish_close()
            else:
                self.refresh()
                if self.pending_mode is not None:
                    target, self.pending_mode = self.pending_mode, None
                    self.request_mode(target)

        self.root.after(40, poll)

    def connect(self):
        ip, dry = self.ip.get().strip(), self.dry.get()
        if not ip and not dry:
            self.status.set("Enter the IP of a stable, supported NAO with Autonomous Life disabled.")
            self.log("Connection not started: robot IP is empty.")
            self.drain_log()
            return

        def connected():
            self.connected = True
            self.status.set("Dry run ready." if dry else "Connected to NAO.")

        self.status.set("Connecting...")
        self.log("Connect clicked ({})".format("dry run" if dry else "live: " + ip))
        self.drain_log()
        self.run(lambda: self.robot.connect(ip, dry, self.log), connected)

    def show_round(self):
        label = "Practice" if self.index == 0 else "Question {}/8".format(self.index)
        item = self.items[self.index]
        lines = [label + " — admin reads:", question(item)]
        if self.stage == "advice":
            self.status.set("Have the participant ask NAO for advice, then click Give Advice.")
        elif self.stage == "reveal":
            lines.append("NAO said: " + advice(item))
            self.status.set("Wait for the participant's final choice, then click Show Admin Reveal.")
        else:
            lines.append("Admin: Your answer was [correct/incorrect]. The correct answer is "
                         + option(item, item[2]) + ". NAO's advice was "
                         + ("correct." if item[2] == item[3] else "incorrect."))
            self.status.set("Read the reveal aloud, regardless of the participant's answer.")
        self.spoken.set("\n".join(lines))

    def start_trivia(self):
        if self.index is not None:
            self.show_round()
            return
        self.index = 0
        self.stage = "advice"
        self.run(lambda: self.robot.say("Hi, I'm NAO. I'll be your trivia teammate. "
                                         "Ask me what I think before you choose an answer."), self.show_round)

    def reset_trivia(self):
        self.index = None
        self.start_trivia()

    def step(self):
        item = self.items[self.index]
        if self.stage == "advice":
            def advised():
                self.stage = "reveal"
                self.show_round()
            self.run(lambda: self.robot.say(advice(item)), advised)
        elif self.stage == "reveal":
            self.stage = "next"
            self.show_round()
            self.refresh()
        elif self.index == len(self.items) - 1:
            self.index = None
            self.mode = "idle"
            self.spoken.set("")
            self.status.set("Trivia complete. Choose Breathing for Robot Present, or leave NAO idle and remove it for Robot Absent.")
            self.refresh()
        else:
            self.index += 1
            self.stage = "advice"
            self.show_round()
            self.refresh()

    def request_mode(self, target):
        if self.closing:
            return
        if self.busy:
            self.pending_mode = target
            self.status.set("Queued mode: " + target + " (after the current robot command).")
            return
        if target == self.mode:
            return
        self.cancel_idle_timer()
        sound = self.sound.get()

        def transition():
            if self.mode == "breathing":
                self.robot.breathe(False, self.log)
            elif target == "breathing":
                self.robot.breathe(True, self.log, sound)

        def switched():
            self.mode = target
            self.breathing = target == "breathing"
            if target == "trivia":
                self.start_trivia()
            else:
                self.spoken.set("")
                self.status.set(("Breathing: arm motion, dim eye changes" + (", and soft puffs." if sound else ".")
                                 + " Check from the participant's seat.")
                                if self.breathing else "Idle. Trivia progress preserved.")
                if self.breathing:
                    self.schedule_idle_tick()

        self.run(transition, switched)

    def cancel_idle_timer(self):
        if self.idle_timer is not None:
            self.root.after_cancel(self.idle_timer)
            self.idle_timer = None

    def schedule_idle_tick(self):
        if self.mode == "breathing" and not self.closing:
            self.idle_timer = self.root.after(BREATH_INTERVAL_MS, self.idle_tick)

    def idle_tick(self):
        self.idle_timer = None
        if self.mode != "breathing" or self.closing:
            return
        if self.busy:
            self.schedule_idle_tick()
            return

        def failed():
            self.pending_mode = None
            self.request_mode("idle")

        self.run(self.robot.idle_tick, self.schedule_idle_tick, failed)

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.cancel_idle_timer()
        self.refresh()
        if not self.busy:
            self.finish_close()

    def finish_close(self):
        future = self.worker.submit(self.robot.close)

        def poll():
            if not future.done():
                self.root.after(40, poll)
                return
            try:
                future.result()
            except Exception as exc:
                print("Could not stop breathing on close. Check NAO in person:", exc)
            self.worker.shutdown(wait=False)
            self.root.destroy()

        self.root.after(40, poll)


if __name__ == "__main__":
    if tuple(correct == spoken for _, _, correct, spoken, _ in ROUNDS) != EXPECTED:
        raise ValueError("Trivia answer sequence changed.")
    root = tk.Tk()
    Window(root)
    root.mainloop()
