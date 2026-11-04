"""Operator window for NAO trivia and survey breathing."""
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from queue import Empty, Queue
import socket
import sys

# Optional: set this to the assigned robot's IP to skip the IP prompt.
ROBOT_IP = ""

# Question, choices, correct index, NAO's scripted answer index (zero-based).
ROUNDS = [
    ("Which planet is known as the Red Planet?", ("Venus", "Mars", "Jupiter"), 1, 1),
    ("On which continent is the Sahara Desert?", ("Africa", "Asia", "Australia"), 0, 0),
    ("Which element has the chemical symbol A U?", ("Silver", "Aluminum", "Gold"), 2, 2),
    ("Who painted the Mona Lisa?", ("Vincent van Gogh", "Leonardo da Vinci", "Pablo Picasso"), 1, 0),
    ("Which is Earth's largest ocean?", ("Pacific Ocean", "Atlantic Ocean", "Indian Ocean"), 0, 0),
    ("Which instrument measures atmospheric pressure?", ("Thermometer", "Anemometer", "Barometer"), 2, 2),
    ("How many sides does a hexagon have?", ("Five", "Six", "Seven"), 1, 0),
    ("Which planet is closest to the Sun?", ("Mercury", "Venus", "Earth"), 0, 1),
]
EXPECTED = (True, True, True, False, True, True, False, False)
PRACTICE = ("Which shape has three sides?", ("Circle", "Triangle", "Square"), 1, 1)


class Controller:
    def __init__(self):
        self.session = self.motion = self.tts = None
        self.dry = True

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

    def breathe(self, enabled):
        if not self.dry:
            if enabled and not self.motion.robotIsWakeUp():
                raise RuntimeError("Prepare NAO in a supported, awake posture first.")
            if enabled and self.session.service("ALAutonomousLife").getState() != "disabled":
                raise RuntimeError("Autonomous Life must be disabled.")
            self.motion.setBreathEnabled("Arms", enabled)
            if self.motion.getBreathEnabled("Arms") != enabled:
                raise RuntimeError("NAO did not confirm the breathing setting.")

    def close(self):
        if self.session is not None:
            try:
                self.breathe(False)
            finally:
                self.session.close()


def question(item):
    text, choices, _, _ = item
    return text + " " + " ".join("{}: {}.".format(letter, choice)
                                  for letter, choice in zip("ABC", choices))


def answer(item):
    _, choices, _, index = item
    return "Thanks. I think the answer is {}: {}.".format("ABC"[index], choices[index])


class Window:
    def __init__(self, root):
        self.root = root
        self.robot = Controller()
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.log_queue = Queue()
        self.busy = self.connected = self.closing = self.breathing = False
        self.items = (PRACTICE,) + tuple(ROUNDS)
        self.index = None
        self.waiting = False
        self.ip = tk.StringVar(value=ROBOT_IP)
        self.dry = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Choose dry run or enter the robot IP, then connect.")
        self.spoken = tk.StringVar()
        root.title("NAO Study Controller")
        root.minsize(560, 470)
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
        self.trivia = ttk.Button(actions, text="Start Trivia", command=self.start)
        self.trivia.pack(side="left", padx=(0, 6))
        self.breath = ttk.Button(actions, text="Start Breathing", command=self.toggle_breathing)
        self.breath.pack(side="left", padx=(0, 6))
        self.advance = ttk.Button(actions, text="Reveal Answer", command=self.step)
        self.advance.pack(side="left")
        self.repeat = ttk.Button(frame, text="Repeat Question", command=self.repeat_question)
        self.repeat.pack(anchor="w", pady=6)
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
        ready = self.connected and not self.busy and not self.closing
        idle = ready and self.index is None
        for widget, enabled in (
            (self.connect_button, not self.connected and not self.busy and not self.closing),
            (self.entry, not self.connected and not self.busy and not self.closing),
            (self.check, not self.connected and not self.busy and not self.closing),
            (self.trivia, idle and not self.breathing),
            (self.breath, idle),
            (self.advance, ready and self.index is not None),
            (self.repeat, ready and self.index is not None and self.waiting),
        ):
            widget.configure(state="normal" if enabled else "disabled")
        self.breath.configure(text="Stop Breathing" if self.breathing else "Start Breathing")
        self.advance.configure(text="Reveal Answer" if self.waiting else "Next Question")

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

    def speak(self, line, success):
        self.spoken.set("NAO: " + line)
        self.run(lambda: self.robot.say(line), success, self.reset_round)

    def reset_round(self):
        self.index = None
        self.waiting = False

    def start(self):
        self.index = 0
        self.waiting = True
        line = ("Hello! I'm NAO. I'll read a question and three choices. Say an answer aloud. "
                "You can ask for a repeat or say pass. Let's practice. " + question(self.items[0]))
        self.speak(line, lambda: self.status.set("Practice: click Reveal Answer after the participant responds."))

    def step(self):
        if self.waiting:
            line = answer(self.items[self.index])
            last = self.index == len(self.items) - 1
            if last:
                line += " That's the end of the trivia activity. Thank you for playing."

            def answered():
                self.waiting = False
                if last:
                    self.reset_round()
                    self.status.set("Trivia complete. For Robot Present, start breathing before the survey. "
                                    "For Robot Absent, remove NAO and leave breathing off.")
                else:
                    self.status.set("Click Next Question when ready.")

            self.speak(line, answered)
        else:
            self.index += 1
            self.waiting = True
            self.speak(question(self.items[self.index]),
                       lambda: self.status.set("Question {}/8: wait for the participant's reply.".format(self.index)))

    def repeat_question(self):
        self.speak(question(self.items[self.index]), lambda: self.status.set("Wait for the participant's reply."))

    def toggle_breathing(self):
        target = not self.breathing

        def changed():
            self.breathing = target
            self.spoken.set("")
            self.status.set("Silent arm breathing is on. Check it from the participant's seat."
                            if target else "Breathing stopped.")

        self.run(lambda: self.robot.breathe(target), changed)

    def close(self):
        if self.closing:
            return
        self.closing = True
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
    if tuple(correct == spoken for _, _, correct, spoken in ROUNDS) != EXPECTED:
        raise ValueError("Trivia answer sequence changed.")
    root = tk.Tk()
    Window(root)
    root.mainloop()
